from collections.abc import AsyncIterator

from voice_agent.models.schemas import RuntimeEvent


class HermesIntegrationUnavailableError(RuntimeError):
    """Raised when a configured Hermes integration is intentionally unavailable."""


class HermesApiClient:
    """Placeholder for a future programmatic Hermes API integration.

    PRD-001 explicitly prefers an API abstraction and forbids scattering direct
    CLI calls through business logic. A stable Hermes API/profile is not wired
    for this repo yet, so this class fails clearly instead of silently shelling
    out to the Hermes CLI. Local development and CI use FakeHermesClient via
    HERMES_INTEGRATION_MODE=fake until Yair wires the dedicated profile/API.
    """

    def __init__(self) -> None:
        raise HermesIntegrationUnavailableError(
            "HERMES_INTEGRATION_MODE=api is reserved for the future dedicated Hermes API; "
            "use HERMES_INTEGRATION_MODE=fake for milestone-001 local runtime smoke tests."
        )

    async def create_session(self, *, profile: str, session_id: str) -> None:
        raise HermesIntegrationUnavailableError("Hermes API integration is not wired yet.")

    async def send_message(self, session_id: str, message: str) -> None:
        raise HermesIntegrationUnavailableError("Hermes API integration is not wired yet.")

    async def stream_responses(self, session_id: str) -> AsyncIterator[RuntimeEvent]:
        raise HermesIntegrationUnavailableError("Hermes API integration is not wired yet.")
        yield RuntimeEvent(event="error", data="unreachable")

    async def close_session(self, session_id: str) -> None:
        raise HermesIntegrationUnavailableError("Hermes API integration is not wired yet.")
