from typing import Any

from voice_agent.telephony.provider import IncomingCallEvent, TelephonyProvider


class LiveKitAdapter(TelephonyProvider):
    """Self-hosted LiveKit control-plane adapter.

    `control_mode="simulated"` is used by local smoke tests and CI. `control_mode="sdk"`
    uses the official `livekit-api` package to create/delete rooms with configured
    self-hosted LiveKit credentials. SIP/audio media events still enter the gateway through
    provider event handling; PRD-002 counts raw frame metadata at that boundary and discards it.
    """

    name = "livekit"

    def __init__(
        self,
        *,
        livekit_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        control_mode: str = "simulated",
    ) -> None:
        self.livekit_url = livekit_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.control_mode = control_mode
        self.rooms: set[str] = set()

    async def prepare_room(self, event: IncomingCallEvent) -> str:
        if self.control_mode == "sdk":
            await self._create_livekit_room(event.room_id)
        self.rooms.add(event.room_id)
        return event.room_id

    async def close_room(self, room_id: str) -> None:
        try:
            if self.control_mode == "sdk":
                await self._delete_livekit_room(room_id)
        finally:
            self.rooms.discard(room_id)

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
