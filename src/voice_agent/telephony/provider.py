from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class CallStatus(StrEnum):
    CONNECTED = "connected"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    CLEANUP_FAILED = "cleanup_failed"
    ENDED = "ended"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IncomingCallEvent:
    room_id: str
    call_id: str = field(default_factory=lambda: f"call_{uuid4().hex}")
    caller_id: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class AudioFrameEvent:
    call_id: str
    payload_size: int
    timestamp_ms: int | None = None


@dataclass(frozen=True, slots=True)
class CallEndedEvent:
    call_id: str
    disconnect_reason: str | None = None


@dataclass(slots=True)
class CallState:
    call_id: str
    livekit_room_id: str
    runtime_session_id: str | None
    caller_id: str | None
    created_at: datetime
    connected_at: datetime | None = None
    ended_at: datetime | None = None
    status: CallStatus = CallStatus.CONNECTED
    packet_count: int = 0
    disconnect_reason: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        end = self.ended_at
        start = self.connected_at or self.created_at
        if end is None:
            return None
        return max(0.0, (end - start).total_seconds())


@dataclass(frozen=True, slots=True)
class RoomState:
    livekit_room_id: str
    call_id: str
    runtime_session_id: str | None
    status: CallStatus
    created_at: datetime


class TelephonyProvider:
    """Provider abstraction for telephony adapters."""

    name: str

    async def prepare_room(self, event: IncomingCallEvent) -> str:
        raise NotImplementedError

    async def close_room(self, room_id: str) -> None:
        raise NotImplementedError
