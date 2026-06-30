import inspect
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from voice_agent.config.settings import Settings, get_settings
from voice_agent.core.audio_session_manager import AudioSessionManager
from voice_agent.core.logging import RequestLoggingMiddleware, configure_logging
from voice_agent.core.session_manager import (
    SessionConflictError,
    SessionManager,
    SessionNotFoundError,
)
from voice_agent.core.version import get_version
from voice_agent.hermes.factory import build_hermes_client
from voice_agent.models.schemas import (
    AudioFrameAcceptedResponse,
    AudioFrameRequest,
    CallEndedRequest,
    CallMetadataResponse,
    CloseSessionResponse,
    CreateSessionResponse,
    HealthResponse,
    IncomingCallRequest,
    LiveKitWebhookResponse,
    MessageAcceptedResponse,
    MessageRequest,
    ReadyResponse,
    RoomMetadataResponse,
)
from voice_agent.telephony.gateway import CallNotFoundError, VoiceGateway
from voice_agent.telephony.livekit import LiveKitAdapter
from voice_agent.telephony.provider import (
    AudioFrameEvent,
    CallEndedEvent,
    CallState,
    IncomingCallEvent,
    RoomState,
)


def _session_manager(request: Request) -> SessionManager:
    return cast(SessionManager, request.app.state.session_manager)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _voice_gateway(request: Request) -> VoiceGateway:
    return cast(VoiceGateway, request.app.state.voice_gateway)


def _call_response(call: CallState) -> CallMetadataResponse:
    return CallMetadataResponse(
        call_id=call.call_id,
        livekit_room_id=call.livekit_room_id,
        runtime_session_id=call.runtime_session_id,
        caller_id=call.caller_id,
        created_at=call.created_at,
        connected_at=call.connected_at,
        ended_at=call.ended_at,
        status=str(call.status),
        packet_count=call.packet_count,
        disconnect_reason=call.disconnect_reason,
        duration_seconds=call.duration_seconds,
    )


def _room_response(room: RoomState) -> RoomMetadataResponse:
    return RoomMetadataResponse(
        livekit_room_id=room.livekit_room_id,
        call_id=room.call_id,
        runtime_session_id=room.runtime_session_id,
        status=str(room.status),
        created_at=room.created_at,
    )


def _livekit_webhook_event_name(payload: dict[str, Any]) -> str:
    return str(payload.get("event") or payload.get("type") or "")


def _livekit_webhook_room_name(payload: dict[str, Any]) -> str | None:
    room = payload.get("room")
    if isinstance(room, dict):
        value = room.get("name") or room.get("sid")
        return str(value) if value else None
    if isinstance(room, str):
        return room
    return None


def _livekit_webhook_participant_attrs(payload: dict[str, Any]) -> dict[str, str]:
    participant = payload.get("participant")
    attrs = participant.get("attributes", {}) if isinstance(participant, dict) else {}
    if isinstance(attrs, dict):
        return {str(key): str(value) for key, value in attrs.items()}
    return {}


def _livekit_webhook_call_id(payload: dict[str, Any], room_id: str) -> str:
    participant = payload.get("participant")
    attrs = _livekit_webhook_participant_attrs(payload)
    for key in ("sip.callID", "sip.callId", "callId", "call_id"):
        value = attrs.get(key)
        if value:
            return value
    if isinstance(participant, dict):
        identity = participant.get("identity")
        if identity:
            return str(identity)
    return f"livekit-{room_id}"


def _livekit_webhook_caller_id(payload: dict[str, Any]) -> str | None:
    participant = payload.get("participant")
    attrs = _livekit_webhook_participant_attrs(payload)
    for key in ("sip.phoneNumber", "sip.from", "callerId", "caller_id"):
        value = attrs.get(key)
        if value:
            return value
    if isinstance(participant, dict):
        name = participant.get("name")
        if name:
            return str(name)
    return None


def _livekit_webhook_is_sip_participant(payload: dict[str, Any]) -> bool:
    participant = payload.get("participant")
    attrs = _livekit_webhook_participant_attrs(payload)
    if any(key.startswith("sip.") for key in attrs):
        return True
    if isinstance(participant, dict):
        identity = str(participant.get("identity") or "")
        name = str(participant.get("name") or "")
        return identity.startswith("sip") or name.startswith("sip")
    return False


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return None


def _authorize_telephony_event(request: Request) -> None:
    settings = _settings(request)
    token = settings.telephony_event_token
    if token:
        received = _bearer_token(request)
        if received is None or not secrets.compare_digest(received, token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid telephony event bearer token is required.",
            )
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="TELEPHONY_EVENT_TOKEN must be configured for telephony event and metadata APIs.",
    )


def _authorize_livekit_webhook(request: Request, body: bytes) -> None:
    """Accept real LiveKit webhook JWTs, with the local event token as a dev fallback."""
    settings = _settings(request)
    bearer = _bearer_token(request)
    if bearer and settings.livekit_api_key and settings.livekit_api_secret:
        try:
            from livekit import api

            verifier = api.TokenVerifier(settings.livekit_api_key, settings.livekit_api_secret)
            api.WebhookReceiver(verifier).receive(body.decode(), bearer)
            return
        except Exception:
            # Fall back to TELEPHONY_EVENT_TOKEN below so local/simulated deployments and tests can
            # keep using the runtime's control-plane token. Invalid LiveKit JWTs still fail there.
            pass
    _authorize_telephony_event(request)


def _sse(event: str, data: str) -> str:
    safe_data = data.replace("\r", " ").replace("\n", "\\n")
    return f"event: {event}\ndata: {safe_data}\n\n"


def _configure_state(app: FastAPI, settings: Settings) -> None:
    session_manager = SessionManager(
        hermes_client=build_hermes_client(settings),
        default_profile=settings.default_profile,
        max_sessions=settings.max_sessions,
    )
    app.state.settings = settings
    app.state.logger = configure_logging(settings.log_level)
    app.state.session_manager = session_manager
    app.state.voice_gateway = VoiceGateway(
        provider=LiveKitAdapter(
            livekit_url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            control_mode=settings.livekit_control_mode,
        ),
        session_manager=session_manager,
        audio_manager=AudioSessionManager(max_buffered_frames=settings.audio_max_buffered_frames),
        max_calls=settings.telephony_max_calls,
        max_call_history=settings.telephony_call_history_limit,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _configure_state(app, get_settings())
    try:
        yield
    finally:
        provider = getattr(app.state.voice_gateway, "_provider", None)
        close = getattr(provider, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hermes Voice Runtime Foundation",
        version="0.1.0",
        description="Transport-agnostic runtime API foundation for a future Hermes voice profile.",
        lifespan=_lifespan,
    )
    settings = get_settings()
    _configure_state(app, settings)
    logger = app.state.logger
    app.add_middleware(RequestLoggingMiddleware, logger=logger)

    @app.exception_handler(SessionConflictError)
    async def session_conflict_handler(
        _request: Request,
        exc: SessionConflictError,
    ) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})

    @app.exception_handler(SessionNotFoundError)
    async def session_not_found_handler(
        _request: Request,
        exc: SessionNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})

    @app.exception_handler(CallNotFoundError)
    async def call_not_found_handler(
        _request: Request,
        exc: CallNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/ready", response_model=ReadyResponse)
    async def ready(request: Request) -> ReadyResponse:
        ready_value, reason = _session_manager(request).readiness()
        return ReadyResponse(ready=ready_value, reason=reason)

    @app.get("/version")
    async def version(request: Request) -> dict[str, Any]:
        return get_version(_settings(request)).model_dump(by_alias=True)

    @app.post(
        "/sessions",
        response_model=CreateSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_session(request: Request) -> CreateSessionResponse:
        session = await _session_manager(request).create_session()
        return CreateSessionResponse(session_id=session.session_id)

    @app.post(
        "/sessions/{session_id}/messages",
        response_model=MessageAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def send_message(
        session_id: str,
        payload: MessageRequest,
        request: Request,
    ) -> MessageAcceptedResponse:
        await _session_manager(request).send_message(session_id, payload.message)
        return MessageAcceptedResponse()

    @app.get("/sessions/{session_id}/stream")
    async def stream(session_id: str, request: Request) -> StreamingResponse:
        manager = _session_manager(request)
        manager.validate_session(session_id)

        async def event_source() -> AsyncIterator[str]:
            async for event in manager.stream_responses(session_id):
                yield _sse(event.event, event.data)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    @app.delete("/sessions/{session_id}", response_model=CloseSessionResponse)
    async def close_session(session_id: str, request: Request) -> CloseSessionResponse:
        await _session_manager(request).close_session(session_id)
        return CloseSessionResponse()

    @app.get("/calls", response_model=list[CallMetadataResponse])
    async def list_calls(request: Request) -> list[CallMetadataResponse]:
        _authorize_telephony_event(request)
        return [_call_response(call) for call in _voice_gateway(request).list_calls()]

    @app.get("/calls/{call_id}", response_model=CallMetadataResponse)
    async def get_call(call_id: str, request: Request) -> CallMetadataResponse:
        _authorize_telephony_event(request)
        return _call_response(_voice_gateway(request).get_call(call_id))

    @app.get("/rooms", response_model=list[RoomMetadataResponse])
    async def list_rooms(request: Request) -> list[RoomMetadataResponse]:
        _authorize_telephony_event(request)
        return [_room_response(room) for room in _voice_gateway(request).list_rooms()]

    @app.post(
        "/telephony/livekit/webhook",
        response_model=LiveKitWebhookResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def livekit_webhook(request: Request) -> LiveKitWebhookResponse:
        body = await request.body()
        _authorize_livekit_webhook(request, body)
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="JSON object required.",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="JSON object required.",
            )
        event_name = _livekit_webhook_event_name(payload)
        room_id = _livekit_webhook_room_name(payload)
        if room_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="LiveKit room name required.",
            )

        call_id: str | None = None
        if event_name in {"participant_joined", "participant_connected"}:
            if _livekit_webhook_is_sip_participant(payload):
                call_id = _livekit_webhook_call_id(payload, room_id)
                call, _created = await _voice_gateway(request).handle_incoming_call(
                    IncomingCallEvent(
                        call_id=call_id,
                        room_id=room_id,
                        caller_id=_livekit_webhook_caller_id(payload),
                    )
                )
                call_id = call.call_id
        elif event_name in {
            "participant_left",
            "participant_disconnected",
        } and _livekit_webhook_is_sip_participant(payload):
            call_id = _livekit_webhook_call_id(payload, room_id)
            try:
                call = _voice_gateway(request).get_call(call_id)
            except CallNotFoundError:
                call = None
            if call is not None and call.livekit_room_id == room_id:
                ended = await _voice_gateway(request).end_call_id(
                    call.call_id,
                    disconnect_reason="livekit_participant_left",
                )
                call_id = ended.call_id
            else:
                call_id = None
        return LiveKitWebhookResponse(event=event_name, call_id=call_id)

    @app.post(
        "/telephony/livekit/events/incoming-call",
        response_model=CallMetadataResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def livekit_incoming_call(
        payload: IncomingCallRequest,
        request: Request,
    ) -> JSONResponse:
        _authorize_telephony_event(request)
        event = IncomingCallEvent(
            call_id=payload.call_id or IncomingCallEvent(room_id=payload.room_id).call_id,
            room_id=payload.room_id,
            caller_id=payload.caller_id,
        )
        call, created = await _voice_gateway(request).handle_incoming_call(event)
        return JSONResponse(
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            content=_call_response(call).model_dump(by_alias=True, mode="json"),
        )

    @app.post(
        "/telephony/livekit/events/audio-frame",
        response_model=AudioFrameAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def livekit_audio_frame(
        payload: AudioFrameRequest,
        request: Request,
    ) -> AudioFrameAcceptedResponse:
        _authorize_telephony_event(request)
        call = _voice_gateway(request).receive_audio_frame(
            AudioFrameEvent(
                call_id=payload.call_id,
                payload_size=payload.payload_size,
                timestamp_ms=payload.timestamp_ms,
            )
        )
        return AudioFrameAcceptedResponse(call_id=call.call_id, packet_count=call.packet_count)

    @app.post("/telephony/livekit/events/call-ended", response_model=CallMetadataResponse)
    async def livekit_call_ended(
        payload: CallEndedRequest,
        request: Request,
    ) -> CallMetadataResponse:
        _authorize_telephony_event(request)
        call = await _voice_gateway(request).end_call(
            CallEndedEvent(
                call_id=payload.call_id,
                disconnect_reason=payload.disconnect_reason,
            )
        )
        return _call_response(call)

    return app


app = create_app()
