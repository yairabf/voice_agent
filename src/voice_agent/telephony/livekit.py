import asyncio
import contextlib
import importlib
from collections.abc import Awaitable, Callable
from typing import Any

from voice_agent.telephony.provider import IncomingCallEvent, TelephonyProvider


class LiveKitAdapter(TelephonyProvider):
    """Self-hosted LiveKit control/media-plane adapter.

    ``control_mode="simulated"`` is used by local smoke tests and CI. ``control_mode="sdk"``
    uses LiveKit API credentials to create/delete rooms and launches a LiveKit RTC listener
    per call room. SIP ingress events arrive through LiveKit webhooks, and audio frames are
    counted at the gateway boundary then discarded.
    """

    name = "livekit"

    def __init__(
        self,
        *,
        livekit_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        control_mode: str = "simulated",
        rtc_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.livekit_url = livekit_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.control_mode = control_mode
        self.rooms: set[str] = set()
        self._gateway: Any | None = None
        self._rtc_factory = rtc_factory
        self._room_tasks: dict[str, asyncio.Task[None]] = {}
        self._rtc_rooms: dict[str, Any] = {}
        self._track_tasks: set[asyncio.Task[None]] = set()

    def bind_gateway(self, gateway: Any) -> None:
        self._gateway = gateway

    async def prepare_room(self, event: IncomingCallEvent) -> str:
        if self.control_mode == "sdk":
            try:
                if not event.room_already_exists:
                    await self._create_livekit_room(event.room_id)
                await self._start_room_audio_listener(event)
            except Exception:
                with contextlib.suppress(Exception):
                    await self._close_room_resources(
                        event.room_id,
                        delete_livekit_room=not event.room_already_exists,
                    )
                raise
        self.rooms.add(event.room_id)
        return event.room_id

    async def close_room(self, room_id: str) -> None:
        await self._close_room_resources(room_id, delete_livekit_room=True)

    async def _close_room_resources(self, room_id: str, *, delete_livekit_room: bool) -> None:
        try:
            task = self._room_tasks.pop(room_id, None)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            rtc_room = self._rtc_rooms.pop(room_id, None)
            if rtc_room is not None:
                disconnect = getattr(rtc_room, "disconnect", None)
                if callable(disconnect):
                    result = disconnect()
                    if isinstance(result, Awaitable):
                        await result
            if self.control_mode == "sdk" and delete_livekit_room:
                await self._delete_livekit_room(room_id)
        finally:
            self.rooms.discard(room_id)

    async def close(self) -> None:
        for room_id in list(self._room_tasks):
            await self.close_room(room_id)
        for task in list(self._track_tasks):
            task.cancel()
        self._track_tasks.clear()

    async def _start_room_audio_listener(self, event: IncomingCallEvent) -> None:
        if self._gateway is None:
            raise RuntimeError("LiveKitAdapter must be bound to VoiceGateway before SDK calls.")
        ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(self._run_room_audio_listener(event, ready))
        self._room_tasks[event.room_id] = task
        task.add_done_callback(lambda completed: self._room_listener_done(event.room_id, completed))
        await ready

    def _room_listener_done(self, room_id: str, task: asyncio.Task[None]) -> None:
        self._room_tasks.pop(room_id, None)
        if task.cancelled():
            return
        with contextlib.suppress(Exception):
            task.result()

    async def _run_room_audio_listener(
        self,
        event: IncomingCallEvent,
        ready: asyncio.Future[None],
    ) -> None:
        try:
            livekit_url, api_key, api_secret = self._require_sdk_config()
            room = self._build_rtc_room()
            self._rtc_rooms[event.room_id] = room
            token = self._room_join_token(event.room_id, api_key, api_secret)

            on = getattr(room, "on", None)
            if callable(on):
                on("track_subscribed", self._make_track_subscribed_handler(event.call_id))
                on(
                    "participant_disconnected",
                    self._make_participant_disconnected_handler(event.call_id),
                )

            connect = room.connect
            result = connect(livekit_url, token)
            if isinstance(result, Awaitable):
                await result
            if not ready.done():
                ready.set_result(None)
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise

        # Real LiveKit rooms stay connected until cancelled/closed. Tests may use a fake room
        # whose connect() returns immediately; keep the listener task alive so close_room() owns
        # lifecycle cleanup in both cases.
        await asyncio.Event().wait()

    def _build_rtc_room(self) -> Any:
        if self._rtc_factory is not None:
            return self._rtc_factory()
        try:
            rtc: Any = importlib.import_module("livekit.rtc")
        except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "The livekit realtime client is required for LIVEKIT_CONTROL_MODE=sdk. "
                "Install the LiveKit RTC Python package in the runtime image."
            ) from exc
        return rtc.Room()

    def _make_track_subscribed_handler(self, call_id: str) -> Callable[..., None]:
        def handler(track: Any, *_args: Any) -> None:
            task = asyncio.create_task(self._consume_audio_track(call_id, track))
            self._track_tasks.add(task)
            task.add_done_callback(self._track_tasks.discard)

        return handler

    def _make_participant_disconnected_handler(self, call_id: str) -> Callable[..., None]:
        def handler(*_args: Any) -> None:
            if self._gateway is not None:
                asyncio.create_task(
                    self._gateway.end_call_id(call_id, disconnect_reason="livekit_participant_left")
                )

        return handler

    async def _consume_audio_track(self, call_id: str, track: Any) -> None:
        stream = self._build_audio_stream(track)
        async for frame_event in stream:
            payload_size = self._frame_payload_size(frame_event)
            timestamp_ms = getattr(frame_event, "timestamp_ms", None)
            if self._gateway is not None:
                self._gateway.receive_audio_frame_payload(
                    call_id,
                    payload_size=payload_size,
                    timestamp_ms=timestamp_ms,
                )

    def _build_audio_stream(self, track: Any) -> Any:
        audio_stream_factory = getattr(track, "audio_stream_factory", None)
        if callable(audio_stream_factory):
            return audio_stream_factory(track)
        rtc: Any = importlib.import_module("livekit.rtc")
        return rtc.AudioStream(track)

    @staticmethod
    def _frame_payload_size(frame_event: Any) -> int:
        frame = getattr(frame_event, "frame", frame_event)
        data = getattr(frame, "data", None)
        if data is not None:
            return len(data)
        samples = getattr(frame, "samples_per_channel", 0) or 0
        channels = getattr(frame, "num_channels", 1) or 1
        return int(samples) * int(channels) * 2

    def _room_join_token(self, room_id: str, api_key: str, api_secret: str) -> str:
        from livekit import api

        return (
            api.AccessToken(api_key, api_secret)
            .with_identity(f"voice-agent-{room_id}")
            .with_name("voice-agent")
            .with_grants(api.VideoGrants(room_join=True, room=room_id))
            .to_jwt()
        )

    def _require_sdk_config(self) -> tuple[str, str, str]:
        if not self.livekit_url or not self.api_key or not self.api_secret:
            raise RuntimeError(
                "LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are required "
                "when LIVEKIT_CONTROL_MODE=sdk."
            )
        return self.livekit_url, self.api_key, self.api_secret

    async def _create_livekit_room(self, room_id: str) -> None:
        livekit_url, api_key, api_secret = self._require_sdk_config()
        from livekit import api

        client: Any = api.LiveKitAPI(livekit_url, api_key, api_secret)
        try:
            await client.room.create_room(api.CreateRoomRequest(name=room_id))
        finally:
            await client.aclose()

    async def _delete_livekit_room(self, room_id: str) -> None:
        livekit_url, api_key, api_secret = self._require_sdk_config()
        from livekit import api

        client: Any = api.LiveKitAPI(livekit_url, api_key, api_secret)
        try:
            await client.room.delete_room(api.DeleteRoomRequest(room=room_id))
        finally:
            await client.aclose()
