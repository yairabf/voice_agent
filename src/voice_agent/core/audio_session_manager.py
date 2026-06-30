from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class AudioFrameMetadata:
    size_bytes: int
    received_at: datetime
    timestamp_ms: int | None = None


@dataclass(slots=True)
class AudioSessionState:
    call_id: str
    packet_count: int = 0
    first_packet_at: datetime | None = None
    last_packet_at: datetime | None = None
    closed_at: datetime | None = None
    _frames: list[AudioFrameMetadata] = field(default_factory=list)

    @property
    def buffered_frame_count(self) -> int:
        return len(self._frames)


class AudioSessionManager:
    """Counts and briefly buffers raw telephony frames, then discards them on cleanup."""

    def __init__(self, *, max_buffered_frames: int = 16) -> None:
        if max_buffered_frames < 0:
            raise ValueError("max_buffered_frames must be non-negative")
        self._max_buffered_frames = max_buffered_frames
        self._sessions: dict[str, AudioSessionState] = {}

    def start_session(self, call_id: str) -> AudioSessionState:
        state = self._sessions.get(call_id)
        if state is None:
            state = AudioSessionState(call_id=call_id)
            self._sessions[call_id] = state
        return state

    def receive_frame(
        self,
        call_id: str,
        frame: bytes,
        *,
        timestamp_ms: int | None = None,
    ) -> AudioSessionState:
        return self.receive_frame_size(call_id, len(frame), timestamp_ms=timestamp_ms)

    def receive_frame_size(
        self,
        call_id: str,
        size_bytes: int,
        *,
        timestamp_ms: int | None = None,
    ) -> AudioSessionState:
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        state = self.start_session(call_id)
        now = datetime.now(UTC)
        state.packet_count += 1
        state.first_packet_at = state.first_packet_at or now
        state.last_packet_at = now
        if self._max_buffered_frames:
            state._frames.append(
                AudioFrameMetadata(
                    size_bytes=size_bytes,
                    received_at=now,
                    timestamp_ms=timestamp_ms,
                )
            )
            del state._frames[: max(0, len(state._frames) - self._max_buffered_frames)]
        return state

    def get_state(self, call_id: str) -> AudioSessionState:
        return self.start_session(call_id)

    def close_session(self, call_id: str) -> AudioSessionState:
        state = self.start_session(call_id)
        state.closed_at = datetime.now(UTC)
        state._frames.clear()
        return state
