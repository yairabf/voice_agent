# voice_agent

Hermes Voice Runtime Foundation for PRD-001. This milestone is a Python/FastAPI backend runtime API for future voice transports. It intentionally excludes LiveKit, phone calls, audio, STT/TTS, auth, UI, automatic Hermes profile creation, and runtime-owned Hermes tool orchestration.

## Status

- Service: `voice_agent`
- Version: `0.1.0`
- Default port: `8088`
- Default profile name: `voice-agent`
- Active sessions: exactly one for PRD-001
- Hermes integration: `HermesClient` abstraction with a deterministic `fake` implementation for local/CI smoke tests. `api` mode is reserved and fails clearly until Yair wires the dedicated Hermes profile/API.

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
