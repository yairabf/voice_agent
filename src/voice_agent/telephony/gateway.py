import asyncio
from datetime import UTC, datetime

from voice_agent.core.audio_session_manager import AudioSessionManager
from voice_agent.core.session_manager import SessionConflictError, SessionManager
from voice_agent.telephony.provider import (
    AudioFrameEvent,
    CallEndedEvent,
    CallState,
    CallStatus,
    IncomingCallEvent,
    RoomState,
    TelephonyProvider,
)


class CallNotFoundError(RuntimeError):
    pass


class VoiceGateway:
    """Maps provider call/room events to runtime sessions and raw-audio counters."""

    def __init__(
        self,
        *,
        provider: TelephonyProvider,
        session_manager: SessionManager,
        audio_manager: AudioSessionManager,
        max_calls: int = 8,
        max_call_history: int = 100,
    ) -> None:
        self._provider = provider
        self._session_manager = session_manager
        self._audio_manager = audio_manager
        self._max_calls = max_calls
        self._max_call_history = max_call_history
        self._calls: dict[str, CallState] = {}
        self._rooms: dict[str, RoomState] = {}
        self._incoming_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        bind_gateway = getattr(provider, "bind_gateway", None)
        if callable(bind_gateway):
            bind_gateway(self)

    async def handle_incoming_call(self, event: IncomingCallEvent) -> tuple[CallState, bool]:
        async with self._incoming_lock:
            existing = self._calls.get(event.call_id)
            if existing is not None:
                return existing, False
            existing_room = self._rooms.get(event.room_id)
            if existing_room is not None and existing_room.call_id != event.call_id:
                now = datetime.now(UTC)
                call = CallState(
                    call_id=event.call_id,
                    livekit_room_id=event.room_id,
                    runtime_session_id=None,
                    caller_id=event.caller_id,
                    created_at=event.received_at,
                    connected_at=None,
                    ended_at=now,
                    status=CallStatus.FAILED,
                    disconnect_reason="livekit_room_already_bound",
                )
                self._record_call(call)
                return call, True

            resource_owning_calls = [
                call
                for call in self._calls.values()
                if call.status in {CallStatus.CONNECTED, CallStatus.RUNTIME_UNAVAILABLE}
            ]
            if len(resource_owning_calls) >= self._max_calls:
                now = datetime.now(UTC)
                call = CallState(
                    call_id=event.call_id,
                    livekit_room_id=event.room_id,
                    runtime_session_id=None,
                    caller_id=event.caller_id,
                    created_at=event.received_at,
                    connected_at=None,
                    status=CallStatus.FAILED,
                    disconnect_reason="telephony_concurrency_limit",
                    ended_at=now,
                )
                self._record_call(call)
                return call, True

            room_id = await self._provider.prepare_room(event)
            runtime_session_id: str | None = None
            status = CallStatus.CONNECTED
            connected_at: datetime | None = datetime.now(UTC)
            disconnect_reason: str | None = None
            try:
                runtime_session = await self._session_manager.create_session()
                runtime_session_id = runtime_session.session_id
            except SessionConflictError:
                status = CallStatus.RUNTIME_UNAVAILABLE
                connected_at = None
                disconnect_reason = "runtime_concurrency_limit"
            except Exception:
                try:
                    await self._provider.close_room(room_id)
                    call = CallState(
                        call_id=event.call_id,
                        livekit_room_id=room_id,
                        runtime_session_id=None,
                        caller_id=event.caller_id,
                        created_at=event.received_at,
                        connected_at=None,
                        ended_at=datetime.now(UTC),
                        status=CallStatus.FAILED,
                        disconnect_reason="runtime_session_creation_failed",
                    )
                    self._record_call(call)
                except Exception:
                    call = CallState(
                        call_id=event.call_id,
                        livekit_room_id=room_id,
                        runtime_session_id=None,
                        caller_id=event.caller_id,
                        created_at=event.received_at,
                        connected_at=None,
                        status=CallStatus.CLEANUP_FAILED,
                        disconnect_reason="runtime_session_creation_cleanup_failed",
                    )
                    self._record_call(call)
                    self._rooms[room_id] = RoomState(
                        livekit_room_id=room_id,
                        call_id=call.call_id,
                        runtime_session_id=None,
                        status=CallStatus.CLEANUP_FAILED,
                        created_at=event.received_at,
                    )
                return call, True

            call = CallState(
                call_id=event.call_id,
                livekit_room_id=room_id,
                runtime_session_id=runtime_session_id,
                caller_id=event.caller_id,
                created_at=event.received_at,
                connected_at=connected_at,
                status=status,
                disconnect_reason=disconnect_reason,
            )
            self._record_call(call)
            self._rooms[room_id] = RoomState(
                livekit_room_id=room_id,
                call_id=call.call_id,
                runtime_session_id=runtime_session_id,
                status=status,
                created_at=event.received_at,
            )
            self._audio_manager.start_session(call.call_id)
            return call, True

    def receive_audio_frame(self, event: AudioFrameEvent) -> CallState:
        call = self._require_active_call(event.call_id)
        audio = self._audio_manager.receive_frame_size(
            event.call_id,
            event.payload_size,
            timestamp_ms=event.timestamp_ms,
        )
        call.packet_count = audio.packet_count
        return call

    def receive_audio_frame_payload(
        self,
        call_id: str,
        *,
        payload_size: int,
        timestamp_ms: int | None,
    ) -> CallState:
        return self.receive_audio_frame(
            AudioFrameEvent(call_id=call_id, payload_size=payload_size, timestamp_ms=timestamp_ms)
        )

    async def end_call_id(
        self,
        call_id: str,
        *,
        disconnect_reason: str | None = None,
    ) -> CallState:
        return await self.end_call(
            CallEndedEvent(call_id=call_id, disconnect_reason=disconnect_reason)
        )

    async def end_call(self, event: CallEndedEvent) -> CallState:
        async with self._lifecycle_lock:
            call = self._require_call(event.call_id)
            if call.status == CallStatus.ENDED:
                return call
            call.status = CallStatus.CLOSING

        runtime_error: Exception | None = None
        provider_error: Exception | None = None
        if call.runtime_session_id is not None:
            try:
                await self._session_manager.close_session(call.runtime_session_id)
                call.runtime_session_id = None
                room = self._rooms.get(call.livekit_room_id)
                if room is not None:
                    self._rooms[call.livekit_room_id] = RoomState(
                        livekit_room_id=room.livekit_room_id,
                        call_id=room.call_id,
                        runtime_session_id=None,
                        status=CallStatus.CLOSING,
                        created_at=room.created_at,
                    )
            except Exception as exc:  # pragma: no cover - defensive cleanup path
                runtime_error = exc
        if runtime_error is not None:
            call.disconnect_reason = event.disconnect_reason or "runtime_cleanup_failed"
            call.status = CallStatus.CLEANUP_FAILED
            raise runtime_error

        try:
            await self._provider.close_room(call.livekit_room_id)
        except Exception as exc:
            provider_error = exc
        if provider_error is not None:
            call.status = CallStatus.CLEANUP_FAILED
            call.disconnect_reason = event.disconnect_reason or "provider_cleanup_failed"
            raise provider_error

        call.status = CallStatus.ENDED
        call.ended_at = datetime.now(UTC)
        call.disconnect_reason = event.disconnect_reason or call.disconnect_reason
        self._rooms.pop(call.livekit_room_id, None)
        self._audio_manager.close_session(call.call_id)
        self._prune_call_history()
        return call

    def list_calls(self) -> list[CallState]:
        return sorted(self._calls.values(), key=lambda call: call.created_at)

    def get_call(self, call_id: str) -> CallState:
        return self._require_call(call_id)

    def get_call_by_room(self, room_id: str) -> CallState:
        room = self._rooms.get(room_id)
        if room is not None:
            return self._require_call(room.call_id)
        for call in self._calls.values():
            if call.livekit_room_id == room_id:
                return call
        raise CallNotFoundError(f"No call found for room '{room_id}'.")

    def list_rooms(self) -> list[RoomState]:
        return sorted(self._rooms.values(), key=lambda room: room.created_at)

    def orphan_session_count(self) -> int:
        active_runtime = self._session_manager.active_session
        if active_runtime is None:
            return 0
        active_call_sessions = {
            call.runtime_session_id
            for call in self._calls.values()
            if call.status == CallStatus.CONNECTED and call.runtime_session_id is not None
        }
        return 0 if active_runtime.session_id in active_call_sessions else 1

    def _require_call(self, call_id: str) -> CallState:
        call = self._calls.get(call_id)
        if call is None:
            raise CallNotFoundError(f"No call found for id '{call_id}'.")
        return call

    def _require_active_call(self, call_id: str) -> CallState:
        call = self._require_call(call_id)
        if call.status in {
            CallStatus.CLOSING,
            CallStatus.ENDED,
            CallStatus.CLEANUP_FAILED,
            CallStatus.FAILED,
        }:
            raise CallNotFoundError(f"Call '{call_id}' is not active (status={call.status}).")
        return call

    def _record_call(self, call: CallState) -> None:
        self._calls[call.call_id] = call
        self._prune_call_history()

    def _prune_call_history(self) -> None:
        overflow = len(self._calls) - self._max_call_history
        if overflow <= 0:
            return
        prunable = sorted(
            (
                call
                for call in self._calls.values()
                if call.status in {CallStatus.ENDED, CallStatus.FAILED, CallStatus.CLEANUP_FAILED}
            ),
            key=lambda call: call.ended_at or call.created_at,
        )
        for call in prunable[:overflow]:
            self._calls.pop(call.call_id, None)
