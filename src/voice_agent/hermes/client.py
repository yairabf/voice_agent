from collections.abc import AsyncIterator
from typing import Protocol

from voice_agent.models.schemas import RuntimeEvent


class HermesClient(Protocol):
    """Transport-neutral boundary between runtime logic and Hermes.

    Business logic depends on this protocol only. Implementations may use a
    future Hermes API, an in-process SDK, or a test double without changing API
    handlers or session lifecycle code. This milestone intentionally avoids
    ad-hoc direct Hermes CLI calls.
    """

    async def create_session(self, *, profile: str, session_id: str) -> None:
        """Initialize a Hermes-side session for a runtime session id."""
        ...

    async def send_message(self, session_id: str, message: str) -> None:
        """Submit a message to Hermes for the active session."""
        ...

    def stream_responses(self, session_id: str) -> AsyncIterator[RuntimeEvent]:
        """Stream response events for an active session."""
        ...

    async def close_session(self, session_id: str) -> None:
        """Release Hermes-side resources for a session."""
        ...
