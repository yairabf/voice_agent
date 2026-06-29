# Coordinator-triggered deployment

Deployment is intentionally not automatic in PRD-001. After Yair approves and merges the PR, coordinator verifies `main` and runs deployment from the merged repository.

Recommended runtime path:

```text
/opt/hermes-voice-runtime/
```

## Prerequisites

- Merged `main` checked out locally or pulled by the coordinator.
- Docker available on the target Hermes instance if deploying via Compose.
- Dedicated Hermes profile/API wiring is not required for the local smoke path because `HERMES_INTEGRATION_MODE=fake` is supported.
- If future production API mode is requested, set `HERMES_INTEGRATION_MODE=api` only after the dedicated Hermes API/profile integration exists; today it fails clearly.

## Deploy from merged main

```bash
git checkout main
git pull --ff-only origin main
scripts/deploy.sh /opt/hermes-voice-runtime
```

The script copies the repository to the target directory, builds the Docker image, and prints the next command.

## Run

```bash
cd /opt/hermes-voice-runtime
docker compose up -d --build
```

## Smoke test

```bash
scripts/smoke_test.sh http://127.0.0.1:8088
```

The smoke test checks:

- `GET /health`
- `GET /ready`
- `GET /version`
- `POST /sessions`
- rejection of a second concurrent session
- `POST /sessions/{id}/messages`
- `GET /sessions/{id}/stream` SSE event structure
- `DELETE /sessions/{id}`

## Rollback

Stop the service and restore a previous deployment directory backup if coordinator made one before replacing files. PRD-001 does not include automatic CD or automatic rollback.
