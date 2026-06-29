import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from voice_agent.hermes.client import HermesClient
from voice_agent.models.schemas import RuntimeEvent, SessionState, SessionStatus


class SessionConflictError(RuntimeError):
    pass


class SessionNotFoundError(RuntimeError):
    pass


class SessionManager:
    """Owns the one-active-session milestone-001 lifecycle."""

    def __init__(
        self,
        *,
        hermes_client: HermesClient,
        default_profile: str,
        max_sessions: int,
    ) -> None:
        if max_sessions != 1:
            raise ValueError("PRD-001 supports exactly one active session")
        self._hermes_client = hermes_client
        self._default_profile = default_profile
        self._max_sessions = max_sessions
        self._create_lock = asyncio.Lock()
        self.active_session: SessionState | None = None

    async def create_session(self) -> SessionState:
        async with self._create_lock:
            active = self.active_session
            if active is not None and active.status == SessionStatus.ACTIVE:
                raise SessionConflictError(
                    f"Only one active session is supported; close session "
                    f"{active.session_id} before creating another."
                )

            session = SessionState(session_id=str(uuid4()), profile=self._default_profile)
            await self._hermes_client.create_session(
                profile=session.profile,
                session_id=session.session_id,
            )
            self.active_session = session
            return session

    async def send_message(self, session_id: str, message: str) -> None:
        session = self._require_active_session(session_id)
        await self._hermes_client.send_message(session_id, message)
        session.last_activity = datetime.now(UTC)

    async def stream_responses(self, session_id: str) -> AsyncIterator[RuntimeEvent]:
        session = self._require_active_session(session_id)
        async for event in self._hermes_client.stream_responses(session_id):
            session.last_activity = datetime.now(UTC)
            yield event

    async def close_session(self, session_id: str) -> None:
        session = self._require_active_session(session_id)
        await self._hermes_client.close_session(session_id)
        session.status = SessionStatus.CLOSED
        session.last_activity = datetime.now(UTC)
        self.active_session = None

    def readiness(self) -> tuple[bool, str | None]:
        if self.active_session is None:
            return True, None
        return (
            False,
            f"Session {self.active_session.session_id} is active; "
            f"max_sessions={self._max_sessions}.",
        )

    def validate_session(self, session_id: str) -> SessionState:
        return self._require_active_session(session_id)

    def _require_active_session(self, session_id: str) -> SessionState:
        if self.active_session is None or self.active_session.session_id != session_id:
            raise SessionNotFoundError(f"No active session found for id '{session_id}'.")
        if self.active_session.status != SessionStatus.ACTIVE:
            raise SessionNotFoundError(f"Session '{session_id}' is not active.")
        return self.active_session
