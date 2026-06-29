from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SessionStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class SessionState(BaseModel):
    session_id: str = Field(serialization_alias="sessionId")
    profile: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        serialization_alias="createdAt",
    )
    last_activity: datetime = Field(
        default_factory=lambda: datetime.now(UTC), serialization_alias="lastActivity"
    )
    status: SessionStatus = SessionStatus.ACTIVE


class RuntimeEvent(BaseModel):
    event: str
    data: str


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)


class CreateSessionResponse(BaseModel):
    session_id: str = Field(serialization_alias="sessionId")


class MessageAcceptedResponse(BaseModel):
    accepted: bool = True


class CloseSessionResponse(BaseModel):
    closed: bool = True


class HealthResponse(BaseModel):
    status: str = "ok"


class ReadyResponse(BaseModel):
    ready: bool
    reason: str | None = None


class VersionResponse(BaseModel):
    service: str = "voice_agent"
    version: str
    commit: str
    branch: str
    deployed_at: str | None = Field(default=None, serialization_alias="deployedAt")
