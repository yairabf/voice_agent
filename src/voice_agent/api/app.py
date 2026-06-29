from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from voice_agent.config.settings import Settings, get_settings
from voice_agent.core.logging import RequestLoggingMiddleware, configure_logging
from voice_agent.core.session_manager import (
    SessionConflictError,
    SessionManager,
    SessionNotFoundError,
)
from voice_agent.core.version import get_version
from voice_agent.hermes.factory import build_hermes_client
from voice_agent.models.schemas import (
    CloseSessionResponse,
    CreateSessionResponse,
    HealthResponse,
    MessageAcceptedResponse,
    MessageRequest,
    ReadyResponse,
)


def _session_manager(request: Request) -> SessionManager:
    return cast(SessionManager, request.app.state.session_manager)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _sse(event: str, data: str) -> str:
    safe_data = data.replace("\r", " ").replace("\n", "\\n")
    return f"event: {event}\ndata: {safe_data}\n\n"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger = configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.logger = logger
    app.state.session_manager = SessionManager(
        hermes_client=build_hermes_client(settings),
        default_profile=settings.default_profile,
        max_sessions=settings.max_sessions,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hermes Voice Runtime Foundation",
        version="0.1.0",
        description="Transport-agnostic runtime API foundation for a future Hermes voice profile.",
        lifespan=_lifespan,
    )
    logger = configure_logging(get_settings().log_level)
    settings = get_settings()
    app.state.settings = settings
    app.state.logger = logger
    app.state.session_manager = SessionManager(
        hermes_client=build_hermes_client(settings),
        default_profile=settings.default_profile,
        max_sessions=settings.max_sessions,
    )
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

    return app


app = create_app()
