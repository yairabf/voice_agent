# voice_agent

Hermes Voice Runtime Foundation for PRD-001 plus the PRD-002 LiveKit telephony boundary. The current backend receives simulated/self-hosted LiveKit call events, maps rooms to runtime sessions, counts raw audio frames for verification, exposes call/room metadata APIs, and cleans up resources. It intentionally excludes STT/TTS, AI conversation, OpenAI Realtime, Hermes reasoning/memory/tool execution, auth, and UI.

## Status

- Service: `voice_agent`
- Version: `0.1.0`
- Default port: `8088`
- Default profile name: `voice-agent`
- Active runtime sessions: exactly one for PRD-001/PRD-002 runtime processing
- Telephony mappings: independent per-call state with overflow calls marked `runtime_unavailable`
- Hermes integration: `HermesClient` abstraction with a deterministic `fake` implementation for local/CI smoke tests. `api` mode is reserved and fails clearly until Yair wires the dedicated Hermes profile/API.
- LiveKit integration: `TelephonyProvider` abstraction with `LiveKitAdapter` implemented for PRD-002 simulated/self-hosted event flow.

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

## Run locally

```bash
. .venv/bin/activate
uvicorn voice_agent.api.app:app --host 0.0.0.0 --port 8088
```

or:

```bash
. .venv/bin/activate
python -m voice_agent
```

## API

FastAPI serves generated OpenAPI docs at `/docs` and schema at `/openapi.json`.

Core endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `POST /sessions`
- `POST /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/stream` (Server-Sent Events: `thinking`, `delta`, `completed`, `error`)
- `DELETE /sessions/{session_id}`
- `GET /calls`
- `GET /calls/{call_id}`
- `GET /rooms`
- `POST /telephony/livekit/events/incoming-call` (simulated CI/acceptance event)
- `POST /telephony/livekit/events/audio-frame` (counts and discards raw frame payload metadata)
- `POST /telephony/livekit/events/call-ended`

See `docs/PRD-002-LiveKit-Telephony-Integration.md` for LiveKit setup assumptions, SIP/eSIM feasibility, simulated event payloads, and real-call acceptance procedure.

## Smoke test

With the server running:

```bash
scripts/smoke_test.sh http://127.0.0.1:8088
```

## Verification

```bash
ruff check .
mypy src
pytest -q
docker build -t voice-agent:local .
```

## Docker Compose

```bash
docker compose up --build
```

## Deployment

Coordinator-triggered deployment docs and scripts are in:

- `docs/architecture.md`
- `docs/deployment.md`
- `scripts/deploy.sh`
- `scripts/smoke_test.sh`

Do not deploy/merge until Yair approves the PR and coordinator performs the post-merge gate.
