import asyncio

import pytest

from voice_agent.core.session_manager import (
    SessionConflictError,
    SessionManager,
    SessionNotFoundError,
)
from voice_agent.hermes.fake import FakeHermesClient


class SlowCreateHermesClient(FakeHermesClient):
    async def create_session(self, *, profile: str, session_id: str) -> None:
        await asyncio.sleep(0)
        await super().create_session(profile=profile, session_id=session_id)


@pytest.mark.asyncio
async def test_session_lifecycle_uses_hermes_client_and_preserves_context() -> None:
    client = FakeHermesClient()
    manager = SessionManager(
        hermes_client=client,
        default_profile="voice-agent",
        max_sessions=1,
    )

    session = await manager.create_session()
    await manager.send_message(session.session_id, "Hello")
    events = [event async for event in manager.stream_responses(session.session_id)]
    await manager.close_session(session.session_id)

    assert session.profile == "voice-agent"
    expected_calls = ["create_session", "send_message", "stream_responses", "close_session"]
    assert [call[0] for call in client.calls] == expected_calls
    assert events[0].event == "thinking"
    assert any(event.event == "delta" and "Hello" in event.data for event in events)
    assert events[-1].event == "completed"
    assert manager.active_session is None


@pytest.mark.asyncio
async def test_concurrent_session_creation_allows_only_one_success() -> None:
    manager = SessionManager(
        hermes_client=SlowCreateHermesClient(),
        default_profile="voice-agent",
        max_sessions=1,
    )

    results = await asyncio.gather(
        manager.create_session(),
        manager.create_session(),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, Exception)]
    conflicts = [result for result in results if isinstance(result, SessionConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1


@pytest.mark.asyncio
async def test_invalid_stream_session_id_errors_before_streaming() -> None:
    manager = SessionManager(
        hermes_client=FakeHermesClient(),
        default_profile="voice-agent",
        max_sessions=1,
    )

    with pytest.raises(SessionNotFoundError):
        manager.validate_session("missing")


@pytest.mark.asyncio
async def test_second_concurrent_session_is_rejected_clearly() -> None:
    manager = SessionManager(
        hermes_client=FakeHermesClient(),
        default_profile="voice-agent",
        max_sessions=1,
    )

    first = await manager.create_session()

    with pytest.raises(SessionConflictError) as exc:
        await manager.create_session()

    assert first.session_id in str(exc.value)
    assert "only one active session" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_invalid_session_id_errors_are_clear() -> None:
    manager = SessionManager(
        hermes_client=FakeHermesClient(),
        default_profile="voice-agent",
        max_sessions=1,
    )

    with pytest.raises(SessionNotFoundError) as exc:
        await manager.send_message("missing", "Hello")

    assert "missing" in str(exc.value)
