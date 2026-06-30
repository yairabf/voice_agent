from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven runtime settings.

    The runtime never creates Hermes profiles. It only records the configured
    profile name and passes it through the HermesClient boundary.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    default_profile: str = Field(default="voice-agent", validation_alias="DEFAULT_PROFILE")
    session_timeout: str = Field(default="30m", validation_alias="SESSION_TIMEOUT")
    max_sessions: int = Field(default=1, validation_alias="MAX_SESSIONS", ge=1, le=1)
    telephony_max_calls: int = Field(default=8, validation_alias="TELEPHONY_MAX_CALLS", ge=1)
    audio_max_buffered_frames: int = Field(
        default=16,
        validation_alias="AUDIO_MAX_BUFFERED_FRAMES",
        ge=0,
    )
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
    voice_runtime_port: int = Field(default=8088, validation_alias="VOICE_RUNTIME_PORT")
    livekit_url: str | None = Field(default=None, validation_alias="LIVEKIT_URL")
    livekit_api_key: str | None = Field(default=None, validation_alias="LIVEKIT_API_KEY")
    livekit_api_secret: str | None = Field(default=None, validation_alias="LIVEKIT_API_SECRET")
    livekit_control_mode: Literal["simulated", "sdk"] = Field(
        default="simulated",
        validation_alias="LIVEKIT_CONTROL_MODE",
    )
    telephony_event_token: str | None = Field(
        default=None,
        validation_alias="TELEPHONY_EVENT_TOKEN",
    )
    hermes_integration_mode: Literal["fake", "api"] = Field(
        default="fake",
        validation_alias="HERMES_INTEGRATION_MODE",
    )
    deployed_at: str | None = Field(default=None, validation_alias="DEPLOYED_AT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
