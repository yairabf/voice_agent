from voice_agent.config.settings import Settings
from voice_agent.hermes.api_client import HermesApiClient
from voice_agent.hermes.client import HermesClient
from voice_agent.hermes.fake import FakeHermesClient


def build_hermes_client(settings: Settings) -> HermesClient:
    if settings.hermes_integration_mode == "fake":
        return FakeHermesClient()
    return HermesApiClient()
