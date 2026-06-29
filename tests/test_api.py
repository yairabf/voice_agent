import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from voice_agent.api.app import create_app


@pytest.mark.asyncio
async def test_health_ready_version_endpoints_return_expected_contract() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/health")
        ready = await client.get("/ready")
        version = await client.get("/version")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert version.status_code == 200
    assert version.json()["service"] == "voice_agent"
    assert version.json()["version"] == "0.1.0"
    assert "commit" in version.json()


@pytest.mark.asyncio
async def test_api_session_message_stream_close_and_second_session_rejection() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/sessions")
        assert created.status_code == 201
        session_id = created.json()["sessionId"]

        second = await client.post("/sessions")
        assert second.status_code == 409
        assert "only one active session" in second.json()["detail"].lower()

        message = await client.post(f"/sessions/{session_id}/messages", json={"message": "Hello"})
        assert message.status_code == 202
        assert message.json() == {"accepted": True}

        stream = await client.get(f"/sessions/{session_id}/stream")
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        body = stream.text
        assert "event: thinking" in body
        assert "event: delta" in body
        assert "event: completed" in body

        closed = await client.delete(f"/sessions/{session_id}")
        assert closed.status_code == 200
        assert closed.json() == {"closed": True}

        recreated = await client.post("/sessions")
        assert recreated.status_code == 201


@pytest.mark.asyncio
async def test_api_concurrent_session_creation_allows_only_one_success() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first, second = await asyncio.gather(client.post("/sessions"), client.post("/sessions"))

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [201, 409]


@pytest.mark.asyncio
async def test_api_rejects_unknown_session_ids() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/sessions/missing/messages", json={"message": "Hello"})

    assert response.status_code == 404
    assert "missing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_stream_rejects_unknown_session_before_sse_response() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/sessions/missing/stream")

    assert response.status_code == 404
    assert "missing" in response.json()["detail"]
