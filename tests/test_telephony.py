import asyncio
import base64
import hashlib
import json

import pytest
from httpx import ASGITransport, AsyncClient

from voice_agent.api.app import create_app
from voice_agent.config.settings import get_settings
from voice_agent.core.audio_session_manager import AudioSessionManager
from voice_agent.telephony.provider import IncomingCallEvent

AUTH_HEADERS = {"authorization": "Bearer change-me-local-dev-token"}


@pytest.mark.asyncio
async def test_audio_session_manager_counts_discards_and_cleans_frames() -> None:
    manager = AudioSessionManager(max_buffered_frames=2)
    manager.start_session("call-1")

    manager.receive_frame("call-1", b"one", timestamp_ms=100)
    manager.receive_frame("call-1", b"two", timestamp_ms=120)
    manager.receive_frame("call-1", b"three", timestamp_ms=140)

    state = manager.get_state("call-1")
    assert state.packet_count == 3
    assert state.first_packet_at is not None
    assert state.last_packet_at is not None
    assert state.buffered_frame_count == 2

    manager.close_session("call-1")
    closed = manager.get_state("call-1")
    assert closed.packet_count == 3
    assert closed.buffered_frame_count == 0


@pytest.mark.asyncio
async def test_livekit_simulated_call_lifecycle_exposes_metadata_and_cleanup() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        incoming = await client.post(
            "/telephony/livekit/events/incoming-call",
            headers=AUTH_HEADERS,
            json={"callId": "call-1", "roomId": "room-1", "callerId": "+15551234567"},
        )
        assert incoming.status_code == 201
        body = incoming.json()
        assert body["callId"] == "call-1"
        assert body["livekitRoomId"] == "room-1"
        assert body["runtimeSessionId"]
        assert body["status"] == "connected"

        frame = await client.post(
            "/telephony/livekit/events/audio-frame",
            headers=AUTH_HEADERS,
            json={"callId": "call-1", "payloadSize": 320, "timestampMs": 1234},
        )
        assert frame.status_code == 202
        assert frame.json()["packetCount"] == 1

        calls = await client.get("/calls", headers=AUTH_HEADERS)
        assert calls.status_code == 200
        assert calls.json()[0]["callId"] == "call-1"
        assert calls.json()[0]["packetCount"] == 1

        call = await client.get("/calls/call-1", headers=AUTH_HEADERS)
        assert call.status_code == 200
        assert call.json()["callerId"] == "+15551234567"

        rooms = await client.get("/rooms", headers=AUTH_HEADERS)
        assert rooms.status_code == 200
        assert rooms.json()[0]["livekitRoomId"] == "room-1"
        assert rooms.json()[0]["callId"] == "call-1"

        ended = await client.post(
            "/telephony/livekit/events/call-ended",
            headers=AUTH_HEADERS,
            json={"callId": "call-1", "disconnectReason": "caller_hangup"},
        )
        assert ended.status_code == 200
        assert ended.json()["status"] == "ended"
        assert ended.json()["endedAt"] is not None

        ready = await client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["ready"] is True


@pytest.mark.asyncio
async def test_livekit_gateway_supports_concurrent_mappings_and_rejects_runtime_overflow() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/telephony/livekit/events/incoming-call",
            headers=AUTH_HEADERS,
            json={"callId": "call-1", "roomId": "room-1", "callerId": "caller-1"},
        )
        second = await client.post(
            "/telephony/livekit/events/incoming-call",
            headers=AUTH_HEADERS,
            json={"callId": "call-2", "roomId": "room-2", "callerId": "caller-2"},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["status"] == "connected"
        assert second.json()["status"] == "runtime_unavailable"
        assert second.json()["runtimeSessionId"] is None

        calls = await client.get("/calls", headers=AUTH_HEADERS)
        by_id = {item["callId"]: item for item in calls.json()}
        assert by_id["call-1"]["livekitRoomId"] == "room-1"
        assert by_id["call-2"]["livekitRoomId"] == "room-2"
        assert by_id["call-1"]["runtimeSessionId"] != by_id["call-2"]["runtimeSessionId"]

        duplicate = await client.post(
            "/telephony/livekit/events/incoming-call",
            headers=AUTH_HEADERS,
            json={"callId": "call-1", "roomId": "room-1", "callerId": "caller-1"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["callId"] == "call-1"

        end_first = await client.post(
            "/telephony/livekit/events/call-ended",
            headers=AUTH_HEADERS,
            json={"callId": "call-1"},
        )
        assert end_first.status_code == 200

        third = await client.post(
            "/telephony/livekit/events/incoming-call",
            headers=AUTH_HEADERS,
            json={"callId": "call-3", "roomId": "room-3", "callerId": "caller-3"},
        )
        assert third.status_code == 201
        assert third.json()["status"] == "connected"


@pytest.mark.asyncio
async def test_audio_frame_request_rejects_oversized_payload_before_allocation() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        incoming = await client.post(
            "/telephony/livekit/events/incoming-call",
            headers=AUTH_HEADERS,
            json={"callId": "call-big", "roomId": "room-big", "callerId": "caller"},
        )
        assert incoming.status_code == 201

        oversized = await client.post(
            "/telephony/livekit/events/audio-frame",
            headers=AUTH_HEADERS,
            json={"callId": "call-big", "payloadSize": 1_048_577, "timestampMs": 1},
        )

    assert oversized.status_code == 422


@pytest.mark.asyncio
async def test_provider_event_model_normalizes_missing_ids() -> None:
    event = IncomingCallEvent(room_id="room-a")
    assert event.call_id.startswith("call_")
    assert event.room_id == "room-a"


@pytest.mark.asyncio
async def test_livekit_event_endpoints_require_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEPHONY_EVENT_TOKEN", "local-test-token")
    get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            unauthorized = await client.post(
                "/telephony/livekit/events/incoming-call",
                json={"callId": "call-auth", "roomId": "room-auth"},
            )
            assert unauthorized.status_code == 401

            authorized = await client.post(
                "/telephony/livekit/events/incoming-call",
                headers={"authorization": "Bearer local-test-token"},
                json={"callId": "call-auth", "roomId": "room-auth"},
            )
            assert authorized.status_code == 201
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_livekit_sdk_mode_requires_event_token_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVEKIT_CONTROL_MODE", "sdk")
    monkeypatch.setenv("TELEPHONY_EVENT_TOKEN", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/telephony/livekit/events/incoming-call",
                json={"callId": "call-sdk", "roomId": "room-sdk"},
            )
            assert response.status_code == 403
            assert "TELEPHONY_EVENT_TOKEN" in response.json()["detail"]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_metadata_endpoints_require_token_by_default() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/calls")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_livekit_webhook_participant_events_drive_call_lifecycle() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        joined = await client.post(
            "/telephony/livekit/webhook",
            headers=AUTH_HEADERS,
            json={
                "event": "participant_joined",
                "room": {"name": "sip-room-1"},
                "participant": {
                    "identity": "sip-participant-1",
                    "attributes": {
                        "sip.callID": "sip-call-1",
                        "sip.phoneNumber": "+15551234567",
                    },
                },
            },
        )
        assert joined.status_code == 202
        assert joined.json()["callId"] == "sip-call-1"

        call = await client.get("/calls/sip-call-1", headers=AUTH_HEADERS)
        assert call.status_code == 200
        assert call.json()["livekitRoomId"] == "sip-room-1"
        assert call.json()["callerId"] == "+15551234567"

        left = await client.post(
            "/telephony/livekit/webhook",
            headers=AUTH_HEADERS,
            json={
                "event": "participant_left",
                "room": {"name": "sip-room-1"},
                "participant": {
                    "identity": "sip-participant-1",
                    "attributes": {"sip.callID": "sip-call-1"},
                },
            },
        )
        assert left.status_code == 202
        assert left.json()["callId"] == "sip-call-1"

        ended = await client.get("/calls/sip-call-1", headers=AUTH_HEADERS)
        assert ended.json()["status"] == "ended"
        assert ended.json()["disconnectReason"] == "livekit_participant_left"


@pytest.mark.asyncio
async def test_livekit_webhook_accepts_signed_livekit_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from livekit import api

    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "devsecret")
    monkeypatch.setenv("TELEPHONY_EVENT_TOKEN", "fallback-token")
    get_settings.cache_clear()
    try:
        app = create_app()
        payload = {
            "event": "participant_joined",
            "room": {"name": "sip-room-jwt"},
            "participant": {
                "identity": "sip-participant-jwt",
                "attributes": {"sip.callID": "sip-call-jwt"},
            },
        }
        body = json.dumps(payload, separators=(",", ":"))
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        token = api.AccessToken("devkey", "devsecret").with_sha256(digest).to_jwt()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/telephony/livekit/webhook",
                headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
                content=body,
            )
        assert response.status_code == 202
        assert response.json()["callId"] == "sip-call-jwt"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_livekit_webhook_ignores_non_sip_participants() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        joined = await client.post(
            "/telephony/livekit/webhook",
            headers=AUTH_HEADERS,
            json={
                "event": "participant_joined",
                "room": {"name": "room-agent"},
                "participant": {"identity": "voice-agent-room-agent", "name": "voice-agent"},
            },
        )
    assert joined.status_code == 202
    assert joined.json()["callId"] is None


@pytest.mark.asyncio
async def test_call_history_prunes_old_terminal_calls() -> None:
    from voice_agent.core.session_manager import SessionManager
    from voice_agent.hermes.fake import FakeHermesClient
    from voice_agent.telephony.gateway import VoiceGateway
    from voice_agent.telephony.provider import TelephonyProvider

    class Provider(TelephonyProvider):
        name = "test"

        async def prepare_room(self, event: IncomingCallEvent) -> str:
            return event.room_id

        async def close_room(self, room_id: str) -> None:
            return None

    gateway = VoiceGateway(
        provider=Provider(),
        session_manager=SessionManager(
            hermes_client=FakeHermesClient(), default_profile="voice-agent", max_sessions=1
        ),
        audio_manager=AudioSessionManager(),
        max_call_history=2,
    )

    for index in range(3):
        await gateway.handle_incoming_call(
            IncomingCallEvent(call_id=f"call-{index}", room_id=f"room-{index}")
        )
        await gateway.end_call_id(f"call-{index}")

    assert [call.call_id for call in gateway.list_calls()] == ["call-1", "call-2"]


@pytest.mark.asyncio
async def test_livekit_sdk_room_listener_counts_rtc_audio_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.core.session_manager import SessionManager
    from voice_agent.hermes.fake import FakeHermesClient
    from voice_agent.telephony.gateway import VoiceGateway
    from voice_agent.telephony.livekit import LiveKitAdapter

    class FakeFrame:
        data = b"123456"

    class FakeAudioStream:
        def __init__(self, _track: object) -> None:
            self._frames = [FakeFrame(), FakeFrame()]

        def __aiter__(self) -> "FakeAudioStream":
            return self

        async def __anext__(self) -> FakeFrame:
            if not self._frames:
                raise StopAsyncIteration
            return self._frames.pop(0)

    class FakeTrack:
        @staticmethod
        def audio_stream_factory(track: object) -> FakeAudioStream:
            return FakeAudioStream(track)

    class FakeRoom:
        def __init__(self) -> None:
            self.handlers: dict[str, object] = {}
            self.disconnected = False

        def on(self, event: str, handler: object) -> None:
            self.handlers[event] = handler

        async def connect(self, _url: str, _token: str) -> None:
            return None

        async def disconnect(self) -> None:
            self.disconnected = True

    fake_room = FakeRoom()
    adapter = LiveKitAdapter(
        livekit_url="ws://livekit:7880",
        api_key="devkey",
        api_secret="secret",
        control_mode="sdk",
        rtc_factory=lambda: fake_room,
    )

    async def no_op_room(_room_id: str) -> None:
        return None

    monkeypatch.setattr(adapter, "_create_livekit_room", no_op_room)
    monkeypatch.setattr(adapter, "_delete_livekit_room", no_op_room)
    monkeypatch.setattr(adapter, "_room_join_token", lambda *_args: "jwt")

    gateway = VoiceGateway(
        provider=adapter,
        session_manager=SessionManager(
            hermes_client=FakeHermesClient(), default_profile="voice-agent", max_sessions=1
        ),
        audio_manager=AudioSessionManager(),
    )

    call, _created = await gateway.handle_incoming_call(
        IncomingCallEvent(call_id="call-sdk-media", room_id="room-sdk-media")
    )
    await asyncio.sleep(0)
    handler = fake_room.handlers["track_subscribed"]
    assert callable(handler)
    handler(FakeTrack())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert call.packet_count == 2
    await gateway.end_call_id("call-sdk-media")
    assert fake_room.disconnected is True


@pytest.mark.asyncio
async def test_livekit_sdk_webhook_joins_existing_sip_room_without_creating_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.core.session_manager import SessionManager
    from voice_agent.hermes.fake import FakeHermesClient
    from voice_agent.telephony.gateway import VoiceGateway
    from voice_agent.telephony.livekit import LiveKitAdapter

    class FakeRoom:
        def __init__(self) -> None:
            self.handlers: dict[str, object] = {}
            self.connected = False

        def on(self, event: str, handler: object) -> None:
            self.handlers[event] = handler

        async def connect(self, _url: str, _token: str) -> None:
            self.connected = True

        async def disconnect(self) -> None:
            self.connected = False

    fake_room = FakeRoom()
    adapter = LiveKitAdapter(
        livekit_url="ws://livekit:7880",
        api_key="devkey",
        api_secret="secret",
        control_mode="sdk",
        rtc_factory=lambda: fake_room,
    )

    created_rooms: list[str] = []

    async def create_room(room_id: str) -> None:
        created_rooms.append(room_id)
        raise RuntimeError("room already exists")

    async def delete_room(_room_id: str) -> None:
        return None

    monkeypatch.setattr(adapter, "_create_livekit_room", create_room)
    monkeypatch.setattr(adapter, "_delete_livekit_room", delete_room)
    monkeypatch.setattr(adapter, "_room_join_token", lambda *_args: "jwt")

    app = create_app()
    app.state.voice_gateway = VoiceGateway(
        provider=adapter,
        session_manager=SessionManager(
            hermes_client=FakeHermesClient(), default_profile="voice-agent", max_sessions=1
        ),
        audio_manager=AudioSessionManager(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        joined = await client.post(
            "/telephony/livekit/webhook",
            headers=AUTH_HEADERS,
            json={
                "event": "participant_joined",
                "room": {"name": "sip-room-existing"},
                "participant": {
                    "identity": "sip-participant-1",
                    "attributes": {
                        "sip.callID": "call-sdk-webhook",
                        "sip.phoneNumber": "+15551234567",
                    },
                },
            },
        )
        calls = await client.get("/calls", headers=AUTH_HEADERS)

    assert joined.status_code == 202
    assert joined.json()["callId"] == "call-sdk-webhook"
    assert created_rooms == []
    assert fake_room.connected is True
    assert fake_room.handlers["track_subscribed"]
    assert calls.status_code == 200
    assert calls.json()[0]["callId"] == "call-sdk-webhook"
    assert calls.json()[0]["livekitRoomId"] == "sip-room-existing"

    await app.state.voice_gateway.end_call_id("call-sdk-webhook")


@pytest.mark.asyncio
async def test_livekit_sdk_webhook_existing_room_listener_failure_does_not_delete_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.core.session_manager import SessionManager
    from voice_agent.hermes.fake import FakeHermesClient
    from voice_agent.telephony.gateway import VoiceGateway
    from voice_agent.telephony.livekit import LiveKitAdapter

    class FailingRoom:
        def on(self, _event: str, _handler: object) -> None:
            return None

        async def connect(self, _url: str, _token: str) -> None:
            raise RuntimeError("rtc unavailable")

    adapter = LiveKitAdapter(
        livekit_url="ws://livekit:7880",
        api_key="devkey",
        api_secret="secret",
        control_mode="sdk",
        rtc_factory=FailingRoom,
    )
    deleted_rooms: list[str] = []

    async def create_room(_room_id: str) -> None:
        raise AssertionError("webhook-observed SIP rooms must not be created")

    async def delete_room(room_id: str) -> None:
        deleted_rooms.append(room_id)

    monkeypatch.setattr(adapter, "_create_livekit_room", create_room)
    monkeypatch.setattr(adapter, "_delete_livekit_room", delete_room)
    monkeypatch.setattr(adapter, "_room_join_token", lambda *_args: "jwt")

    app = create_app()
    app.state.voice_gateway = VoiceGateway(
        provider=adapter,
        session_manager=SessionManager(
            hermes_client=FakeHermesClient(), default_profile="voice-agent", max_sessions=1
        ),
        audio_manager=AudioSessionManager(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="rtc unavailable"):
            await client.post(
                "/telephony/livekit/webhook",
                headers=AUTH_HEADERS,
                json={
                    "event": "participant_joined",
                    "room": {"name": "sip-room-listener-fail"},
                    "participant": {
                        "identity": "sip-participant-2",
                        "attributes": {"sip.callID": "call-listener-fail"},
                    },
                },
            )

    assert deleted_rooms == []


@pytest.mark.asyncio
async def test_livekit_sdk_listener_connect_failure_surfaces_before_call_is_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_agent.core.session_manager import SessionManager
    from voice_agent.hermes.fake import FakeHermesClient
    from voice_agent.telephony.gateway import CallNotFoundError, VoiceGateway
    from voice_agent.telephony.livekit import LiveKitAdapter

    class FailingRoom:
        def on(self, _event: str, _handler: object) -> None:
            return None

        async def connect(self, _url: str, _token: str) -> None:
            raise RuntimeError("rtc unavailable")

    adapter = LiveKitAdapter(
        livekit_url="ws://livekit:7880",
        api_key="devkey",
        api_secret="secret",
        control_mode="sdk",
        rtc_factory=FailingRoom,
    )

    created_rooms: list[str] = []
    deleted_rooms: list[str] = []

    async def create_room(room_id: str) -> None:
        created_rooms.append(room_id)

    async def delete_room(room_id: str) -> None:
        deleted_rooms.append(room_id)

    monkeypatch.setattr(adapter, "_create_livekit_room", create_room)
    monkeypatch.setattr(adapter, "_delete_livekit_room", delete_room)
    monkeypatch.setattr(adapter, "_room_join_token", lambda *_args: "jwt")

    gateway = VoiceGateway(
        provider=adapter,
        session_manager=SessionManager(
            hermes_client=FakeHermesClient(), default_profile="voice-agent", max_sessions=1
        ),
        audio_manager=AudioSessionManager(),
    )

    with pytest.raises(RuntimeError, match="rtc unavailable"):
        await gateway.handle_incoming_call(
            IncomingCallEvent(call_id="call-fail", room_id="room-fail")
        )

    assert created_rooms == ["room-fail"]
    assert deleted_rooms == ["room-fail"]
    with pytest.raises(CallNotFoundError):
        gateway.get_call("call-fail")
