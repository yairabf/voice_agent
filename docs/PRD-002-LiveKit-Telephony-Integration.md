# PRD-002 LiveKit Telephony Integration

This document describes the PRD-002 backend/runtime telephony milestone. It intentionally stops at transport/session/audio-frame verification: no STT, TTS, OpenAI Realtime, Hermes reasoning, memory, tool execution, prompts, or voice generation are included.

## Architecture

Phone/SIP ingress is modeled behind a `TelephonyProvider` interface:

- `TelephonyProvider`: provider abstraction used by the gateway.
- `LiveKitAdapter`: PRD-002 provider implementation boundary for self-hosted LiveKit.
- `VoiceGateway`: maps provider call/room events to runtime sessions and audio counters.
- `AudioSessionManager`: counts raw audio frames, keeps only a small rolling verification buffer, and discards frames on cleanup.

Runtime logic depends on the provider interface and gateway state, not on LiveKit-specific SDK types. This keeps future Twilio/SIP/browser WebRTC adapters possible without redesigning the runtime.

## Configuration

Required/expected environment values:

```env
LIVEKIT_URL=ws://livekit:7880
LIVEKIT_API_KEY=<managed secret or local dev key>
LIVEKIT_API_SECRET=<managed secret or local dev secret>
LIVEKIT_CONTROL_MODE=simulated  # use sdk for livekit-api room create/delete
TELEPHONY_EVENT_TOKEN=<required bearer token when LIVEKIT_CONTROL_MODE=sdk>
MAX_SESSIONS=1
TELEPHONY_MAX_CALLS=8
AUDIO_MAX_BUFFERED_FRAMES=16
```

Local Docker Compose starts `livekit/livekit-server:latest` in `--dev` mode and passes development credentials to `voice-agent`. Production must provide these through managed environment/secret configuration; do not commit real LiveKit secrets. `LIVEKIT_CONTROL_MODE=simulated` keeps CI/local smoke tests deterministic; `LIVEKIT_CONTROL_MODE=sdk` uses the official `livekit-api` package to create and delete rooms against the configured self-hosted LiveKit server. The simulated/local event endpoints accept unsigned requests only in `simulated` mode; in `sdk` mode `TELEPHONY_EVENT_TOKEN` is required and requests must send `Authorization: Bearer <token>`.

## API

Metadata endpoints:

- `GET /calls` — recent/active/completed call metadata.
- `GET /calls/{id}` — one call's metadata.
- `GET /rooms` — active LiveKit room to runtime-session mappings.

Simulated LiveKit event endpoints for CI/smoke tests:

- `POST /telephony/livekit/events/incoming-call`
  - body: `{"callId":"call-1","roomId":"room-1","callerId":"+155..."}`
- `POST /telephony/livekit/events/audio-frame`
  - body: `{"callId":"call-1","payloadSize":320,"timestampMs":1234}`
- `POST /telephony/livekit/events/call-ended`
  - body: `{"callId":"call-1","disconnectReason":"caller_hangup"}`

The simulated endpoints exercise the same gateway/session/audio lifecycle used by the provider boundary and allow CI to verify behavior without requiring a real phone call.

## Concurrency behavior

The gateway stores independent call state by call ID and room ID. PRD-001 runtime processing still allows exactly one active runtime session (`MAX_SESSIONS=1`). Additional concurrent calls are still represented independently but are marked `runtime_unavailable` with `disconnectReason=runtime_concurrency_limit` until runtime concurrency is expanded in a later milestone.

## Audio handling

AudioFrameRequest rejects `payloadSize` values larger than 1 MiB and the gateway records frame size metadata without allocating request-sized byte buffers. `AudioSessionManager` increments `packetCount`, records first/last packet timestamps, keeps only the latest `AUDIO_MAX_BUFFERED_FRAMES` verification frame metadata entries in memory, and clears the buffer when the call ends.

## eSIM / phone-number feasibility

A normal consumer eSIM/phone number cannot usually be pointed directly at LiveKit by itself. LiveKit SIP expects SIP-compatible ingress: a SIP trunk, SIP forwarding provider, LiveKit Cloud phone number, Twilio Elastic SIP Trunking, or another carrier feature that can route inbound calls to SIP. If Yair's real carrier/eSIM plan supports SIP trunking/forwarding, configure that route to LiveKit SIP. If not, use a SIP-compatible provider or LiveKit Cloud Number for the required real-call acceptance test.

## Real-call acceptance procedure

Before milestone closure, perform one inbound call through a SIP-compatible route:

1. Configure `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` from managed secrets.
2. Configure LiveKit SIP ingress using Yair's carrier SIP trunk/forwarding if supported; otherwise use LiveKit Cloud Number, Twilio SIP trunk, or another SIP-compatible provider.
3. Start/deploy `voice-agent` and LiveKit.
4. Place one inbound call.
5. Verify LiveKit creates a room.
6. Verify `voice-agent` creates or marks a runtime call mapping.
7. Verify `packetCount` increases in `GET /calls/{id}`.
8. Hang up.
9. Verify `status=ended`, `endedAt` is set, `/rooms` no longer lists the room, and `/ready` returns ready when the runtime session was active.

## Local verification

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check .
mypy src
python -m uvicorn voice_agent.api.app:app --host 127.0.0.1 --port 8088
scripts/smoke_test.sh http://127.0.0.1:8088
```
