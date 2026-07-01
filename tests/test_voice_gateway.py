import asyncio

import pytest

from voice_agent.core.audio_session_manager import AudioSessionManager
from voice_agent.core.session_manager import SessionManager
from voice_agent.hermes.fake import FakeHermesClient
from voice_agent.telephony.gateway import CallNotFoundError, VoiceGateway
from voice_agent.telephony.provider import IncomingCallEvent, TelephonyProvider


class FailingCreateHermesClient(FakeHermesClient):
    async def create_session(self, *, profile: str, session_id: str) -> None:
        raise RuntimeError("runtime create failed")


class YieldingProvider(TelephonyProvider):
    name = "yielding"

    def __init__(self, *, fail_close: bool = False) -> None:
        self.rooms: set[str] = set()
        self.fail_close = fail_close

    async def prepare_room(self, event: IncomingCallEvent) -> str:
        await asyncio.sleep(0)
        self.rooms.add(event.room_id)
        return event.room_id

    async def close_room(self, room_id: str) -> None:
        await asyncio.sleep(0)
        if self.fail_close:
            raise RuntimeError("provider close failed")
        self.rooms.discard(room_id)


def build_gateway(
    provider: TelephonyProvider,
    *,
    max_calls: int = 8,
    hermes_client: FakeHermesClient | None = None,
) -> VoiceGateway:
    return VoiceGateway(
        provider=provider,
        session_manager=SessionManager(
            hermes_client=hermes_client or FakeHermesClient(),
            default_profile="voice-agent",
            max_sessions=1,
        ),
        audio_manager=AudioSessionManager(max_buffered_frames=2),
        max_calls=max_calls,
    )


@pytest.mark.asyncio
async def test_duplicate_incoming_events_are_idempotent_under_concurrency() -> None:
    gateway = build_gateway(YieldingProvider())
    event = IncomingCallEvent(call_id="call-dup", room_id="room-dup", caller_id="caller")

    first, second = await asyncio.gather(
        gateway.handle_incoming_call(event),
        gateway.handle_incoming_call(event),
    )

    calls = gateway.list_calls()
    assert len(calls) == 1
    assert calls[0].status == "connected"
    assert first[0].runtime_session_id == second[0].runtime_session_id
    assert first[1] != second[1]
    assert gateway.orphan_session_count() == 0


@pytest.mark.asyncio
async def test_audio_frames_after_call_end_are_rejected() -> None:
    gateway = build_gateway(YieldingProvider())
    call, _created = await gateway.handle_incoming_call(
        IncomingCallEvent(call_id="call-ended", room_id="room-ended")
    )
    gateway.receive_audio_frame_payload("call-ended", payload_size=10, timestamp_ms=None)
    await gateway.end_call_id("call-ended", disconnect_reason="done")

    with pytest.raises(CallNotFoundError):
        gateway.receive_audio_frame_payload("call-ended", payload_size=10, timestamp_ms=None)

    assert call.packet_count == 1


@pytest.mark.asyncio
async def test_provider_close_failure_stays_retryable_until_room_cleanup_succeeds() -> None:
    provider = YieldingProvider(fail_close=True)
    gateway = build_gateway(provider)
    await gateway.handle_incoming_call(IncomingCallEvent(call_id="call-fail", room_id="room-fail"))
    gateway.receive_audio_frame_payload("call-fail", payload_size=10, timestamp_ms=None)

    with pytest.raises(RuntimeError):
        await gateway.end_call_id("call-fail", disconnect_reason="done")

    assert gateway.get_call("call-fail").status == "cleanup_failed"
    assert gateway.list_rooms()[0].livekit_room_id == "room-fail"
    assert gateway.orphan_session_count() == 0

    provider.fail_close = False
    retried = await gateway.end_call_id("call-fail", disconnect_reason="done")
    assert retried.status == "ended"
    assert gateway.list_rooms() == []


@pytest.mark.asyncio
async def test_gateway_rejects_overflow_before_creating_provider_room() -> None:
    provider = YieldingProvider()
    gateway = build_gateway(provider, max_calls=1)

    first, _created = await gateway.handle_incoming_call(
        IncomingCallEvent(call_id="call-1", room_id="room-1")
    )
    second, _created = await gateway.handle_incoming_call(
        IncomingCallEvent(call_id="call-2", room_id="room-2")
    )

    assert first.status == "connected"
    assert second.status == "failed"
    assert second.disconnect_reason == "telephony_concurrency_limit"
    assert second.ended_at is not None
    assert "room-2" not in provider.rooms

    await gateway.end_call_id("call-1", disconnect_reason="done")
    third, _created = await gateway.handle_incoming_call(
        IncomingCallEvent(call_id="call-3", room_id="room-3")
    )
    assert third.status == "connected"


@pytest.mark.asyncio
async def test_runtime_create_failure_closes_provider_room_and_records_failed_call() -> None:
    provider = YieldingProvider()
    gateway = build_gateway(provider, hermes_client=FailingCreateHermesClient())

    call, created = await gateway.handle_incoming_call(
        IncomingCallEvent(call_id="call-runtime-fail", room_id="room-runtime-fail")
    )

    assert created is True
    assert call.status == "failed"
    assert call.ended_at is not None
    assert call.disconnect_reason == "runtime_session_creation_failed"
    assert "room-runtime-fail" not in provider.rooms
    assert gateway.list_rooms() == []
    assert gateway.orphan_session_count() == 0


@pytest.mark.asyncio
async def test_gateway_rejects_room_id_collision_without_overwriting_mapping() -> None:
    provider = YieldingProvider()
    gateway = build_gateway(provider, max_calls=8)

    first, first_created = await gateway.handle_incoming_call(
        IncomingCallEvent(call_id="call-1", room_id="shared-room")
    )
    second, second_created = await gateway.handle_incoming_call(
        IncomingCallEvent(call_id="call-2", room_id="shared-room")
    )

    assert first_created is True
    assert second_created is True
    assert first.status == "connected"
    assert second.status == "failed"
    assert second.disconnect_reason == "livekit_room_already_bound"
    assert second.ended_at is not None

    rooms = gateway.list_rooms()
    assert len(rooms) == 1
    assert rooms[0].call_id == "call-1"
    assert provider.rooms == {"shared-room"}

    await gateway.end_call_id("call-1", disconnect_reason="done")
    assert gateway.list_rooms() == []
