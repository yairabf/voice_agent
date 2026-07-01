# Coordinator-triggered deployment

Deployment is not automatic from feature branches. After Yair approves merge to `main`, the coordinator verifies `main` and deploys from the merged repository.

Recommended runtime path:

```text
/opt/hermes-voice-runtime/
```

## Prerequisites

- Merged `main` checked out locally or pulled by the coordinator.
- Docker and Docker Compose available on the target Hermes instance.
- `HERMES_INTEGRATION_MODE=fake` is supported for local smoke validation.
- Replace the `.env.example` telephony bearer value before exposing the service.
- For real phone acceptance, provision a SIP-compatible inbound path (LiveKit Cloud Number, Twilio Elastic SIP trunk, or another SIP trunk/forwarding provider) that can route calls to LiveKit SIP ingress. A normal consumer eSIM generally cannot route directly to self-hosted LiveKit unless the carrier provides SIP trunking/forwarding.

## Deploy from merged main

```bash
git checkout main
git pull --ff-only origin main
scripts/deploy.sh /opt/hermes-voice-runtime
```

The script copies the repository to the target directory, builds the Docker image, and prints the next command.

## Local run: runtime + LiveKit server

```bash
cd /opt/hermes-voice-runtime
docker compose up -d --build livekit voice-agent
```

The compose file binds the runtime and LiveKit dev ports to `127.0.0.1` by default.

## Optional local SIP worker

```bash
docker compose --profile sip up -d livekit livekit-sip
```

`configs/livekit-sip.yaml` configures the SIP worker to connect to the local LiveKit server with the dev key/secret. Real deployments still need provider-specific SIP trunk and dispatch-rule setup with the LiveKit CLI/API. The expected dispatch target is a LiveKit room; LiveKit webhooks then notify `/telephony/livekit/webhook`, and the SDK-mode `LiveKitAdapter` joins that room to count audio frames.

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
- authenticated simulated incoming LiveKit call event
- authenticated simulated raw audio frame event and `packetCount` increment
- authenticated `GET /calls` and `GET /rooms`
- authenticated simulated call-ended cleanup

## Real-call acceptance procedure

1. Run LiveKit, LiveKit SIP, and voice-agent with `LIVEKIT_CONTROL_MODE=sdk` and real LiveKit API credentials.
2. Configure LiveKit webhook delivery to `POST /telephony/livekit/webhook`. Real LiveKit sends a signed webhook JWT in `Authorization`; local/dev proxies can instead send the bearer value expected by `TELEPHONY_EVENT_TOKEN`.
3. Configure the SIP provider/trunk/dispatch rule so an inbound phone call joins a LiveKit room reachable by the voice-agent service.
4. Place one inbound call.
5. Verify `GET /calls` shows the call id, LiveKit room id, caller metadata where available, a runtime session id or explicit runtime-unavailable status, and `packetCount > 0` once audio is present.
6. Hang up and verify `GET /rooms` no longer lists the room and `/ready` returns ready with no orphaned runtime session.

## Rollback

Stop the service and restore a previous deployment directory backup if coordinator made one before replacing files. PRD-002 does not include automatic rollback.
