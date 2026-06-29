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
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
    voice_runtime_port: int = Field(default=8088, validation_alias="VOICE_RUNTIME_PORT")
    hermes_integration_mode: Literal["fake", "api"] = Field(
        default="fake",
        validation_alias="HERMES_INTEGRATION_MODE",
    )
    deployed_at: str | None = Field(default=None, validation_alias="DEPLOYED_AT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
