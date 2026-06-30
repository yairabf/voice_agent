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


class IncomingCallRequest(BaseModel):
    call_id: str | None = Field(default=None, validation_alias="callId")
    room_id: str = Field(validation_alias="roomId")
    caller_id: str | None = Field(default=None, validation_alias="callerId")


class AudioFrameRequest(BaseModel):
    call_id: str = Field(validation_alias="callId")
    payload_size: int = Field(validation_alias="payloadSize", ge=0, le=1_048_576)
    timestamp_ms: int | None = Field(default=None, validation_alias="timestampMs")


class CallEndedRequest(BaseModel):
    call_id: str = Field(validation_alias="callId")
    disconnect_reason: str | None = Field(default=None, validation_alias="disconnectReason")


class CallMetadataResponse(BaseModel):
    call_id: str = Field(serialization_alias="callId")
    livekit_room_id: str = Field(serialization_alias="livekitRoomId")
    runtime_session_id: str | None = Field(default=None, serialization_alias="runtimeSessionId")
    caller_id: str | None = Field(default=None, serialization_alias="callerId")
    created_at: datetime = Field(serialization_alias="createdAt")
    connected_at: datetime | None = Field(default=None, serialization_alias="connectedAt")
    ended_at: datetime | None = Field(default=None, serialization_alias="endedAt")
    status: str
    packet_count: int = Field(serialization_alias="packetCount")
    disconnect_reason: str | None = Field(default=None, serialization_alias="disconnectReason")
    duration_seconds: float | None = Field(default=None, serialization_alias="durationSeconds")


class RoomMetadataResponse(BaseModel):
    livekit_room_id: str = Field(serialization_alias="livekitRoomId")
    call_id: str = Field(serialization_alias="callId")
    runtime_session_id: str | None = Field(default=None, serialization_alias="runtimeSessionId")
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")


class AudioFrameAcceptedResponse(BaseModel):
    accepted: bool = True
    call_id: str = Field(serialization_alias="callId")
    packet_count: int = Field(serialization_alias="packetCount")
