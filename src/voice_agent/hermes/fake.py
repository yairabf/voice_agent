from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from voice_agent.models.schemas import RuntimeEvent


@dataclass
class FakeHermesClient:
    """Deterministic HermesClient for local development and tests.

    This is not a fake hidden in business logic; it is a swappable integration
    implementation behind the HermesClient protocol. It keeps milestone 001
    runnable while the dedicated Hermes profile/API is created later.
    """

    calls: list[tuple[str, str]] = field(default_factory=list)
    _messages: dict[str, list[str]] = field(default_factory=dict)

    async def create_session(self, *, profile: str, session_id: str) -> None:
        self.calls.append(("create_session", session_id))
        self._messages[session_id] = []

    async def send_message(self, session_id: str, message: str) -> None:
        self.calls.append(("send_message", session_id))
        self._messages.setdefault(session_id, []).append(message)

    async def stream_responses(self, session_id: str) -> AsyncIterator[RuntimeEvent]:
        self.calls.append(("stream_responses", session_id))
        messages = self._messages.get(session_id, [])
        latest = messages[-1] if messages else ""
        yield RuntimeEvent(event="thinking", data="processing message")
        yield RuntimeEvent(event="delta", data=f"Fake Hermes response to: {latest}")
        yield RuntimeEvent(event="completed", data="done")

    async def close_session(self, session_id: str) -> None:
        self.calls.append(("close_session", session_id))
        self._messages.pop(session_id, None)
