# Architecture

PRD-001 implements the runtime foundation only. It exposes a transport-agnostic HTTP API that future LiveKit, CLI, web, and mobile clients can call.

```text
Future clients
  ├── LiveKit (future)
  ├── CLI (future)
  ├── Web/mobile (future)
  └── Tests
        │
        ▼
FastAPI Runtime API
        │
        ▼
SessionManager (exactly one active session)
        │
        ▼
HermesClient protocol
        │
        ├── FakeHermesClient (local/CI milestone-001 smoke tests)
        └── HermesApiClient (reserved; fails clearly until API/profile is wired)
```

## Runtime-owned responsibilities

- HTTP API and OpenAPI schema.
- Session lifecycle.
- Configured Hermes profile name pass-through.
- SSE streaming contract.
- Health/readiness/version endpoints.
- Structured request logging.
- Docker/Compose/CI/deployment scaffolding.

## Not runtime-owned in PRD-001

- Hermes reasoning, prompts, skills, memory, and tool orchestration.
- Dedicated Hermes profile creation.
- Authentication.
- Audio/telephony/LiveKit/STT/TTS.

## Hermes integration boundary

Business logic only depends on `voice_agent.hermes.client.HermesClient`. API handlers call `SessionManager`; `SessionManager` calls the protocol. No handler or session lifecycle code shells out to Hermes CLI.

`HERMES_INTEGRATION_MODE=fake` is intentionally the default so the milestone can be run and validated before Yair creates/wires the dedicated Hermes profile. `HERMES_INTEGRATION_MODE=api` currently raises a clear startup error. That is the documented integration gap for PRD-001, preserving the API-oriented design rather than creating a CLI-wrapper compromise.

## Session behavior

- `POST /sessions` creates one UUID-backed active session.
- Another `POST /sessions` while active returns HTTP 409 with a clear error.
- `POST /sessions/{id}/messages` accepts non-empty messages for the active session.
- `GET /sessions/{id}/stream` returns SSE events.
- `DELETE /sessions/{id}` closes the active session and permits a new one.
