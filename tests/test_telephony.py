import pytest
from httpx import ASGITransport, AsyncClient

from voice_agent.api.app import create_app
from voice_agent.config.settings import get_settings
from voice_agent.core.audio_session_manager import AudioSessionManager
from voice_agent.telephony.provider import IncomingCallEvent


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
            json={"callId": "call-1", "payloadSize": 320, "timestampMs": 1234},
        )
        assert frame.status_code == 202
        assert frame.json()["packetCount"] == 1

        calls = await client.get("/calls")
        assert calls.status_code == 200
        assert calls.json()[0]["callId"] == "call-1"
        assert calls.json()[0]["packetCount"] == 1

        call = await client.get("/calls/call-1")
        assert call.status_code == 200
        assert call.json()["callerId"] == "+15551234567"

        rooms = await client.get("/rooms")
        assert rooms.status_code == 200
        assert rooms.json()[0]["livekitRoomId"] == "room-1"
        assert rooms.json()[0]["callId"] == "call-1"

        ended = await client.post(
            "/telephony/livekit/events/call-ended",
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
            json={"callId": "call-1", "roomId": "room-1", "callerId": "caller-1"},
        )
        second = await client.post(
            "/telephony/livekit/events/incoming-call",
            json={"callId": "call-2", "roomId": "room-2", "callerId": "caller-2"},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["status"] == "connected"
        assert second.json()["status"] == "runtime_unavailable"
        assert second.json()["runtimeSessionId"] is None

        calls = await client.get("/calls")
        by_id = {item["callId"]: item for item in calls.json()}
        assert by_id["call-1"]["livekitRoomId"] == "room-1"
        assert by_id["call-2"]["livekitRoomId"] == "room-2"
        assert by_id["call-1"]["runtimeSessionId"] != by_id["call-2"]["runtimeSessionId"]

        duplicate = await client.post(
            "/telephony/livekit/events/incoming-call",
            json={"callId": "call-1", "roomId": "room-1", "callerId": "caller-1"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["callId"] == "call-1"

        end_first = await client.post(
            "/telephony/livekit/events/call-ended",
            json={"callId": "call-1"},
        )
        assert end_first.status_code == 200

        third = await client.post(
            "/telephony/livekit/events/incoming-call",
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
            json={"callId": "call-big", "roomId": "room-big", "callerId": "caller"},
        )
        assert incoming.status_code == 201

        oversized = await client.post(
            "/telephony/livekit/events/audio-frame",
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
    monkeypatch.delenv("TELEPHONY_EVENT_TOKEN", raising=False)
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
