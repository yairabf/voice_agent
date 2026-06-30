# Architecture

PRD-002 extends the PRD-001 runtime foundation with a telephony boundary for self-hosted LiveKit. The runtime still does not own STT, TTS, LLM prompts, Hermes reasoning, memory, or tool execution.

```text
Phone/SIP provider
        │
        ▼
LiveKit SIP ingress (self-hosted livekit/sip)
        │ creates/joins LiveKit rooms
        ▼
LiveKit server
        │ webhooks + RTC audio tracks
        ▼
FastAPI Voice Gateway
        │
        ├── TelephonyProvider interface
        │     └── LiveKitAdapter
        │           ├── simulated mode: CI/local HTTP events
        │           └── sdk mode: LiveKit API room control + RTC audio listener
        │
        ├── VoiceGateway room/call/session mapping
        │     ├── one CallState per provider call id
        │     ├── one RoomState per LiveKit room id
        │     ├── no global single-caller assumption
        │     └── bounded terminal call-history retention
        │
        ├── AudioSessionManager
        │     ├── counts raw frame sizes/timestamps at gateway boundary
        │     ├── keeps only a small verification buffer
        │     └── discards buffered audio on cleanup
        │
        ▼
SessionManager (currently one active runtime session)
        │
        ▼
HermesClient protocol
        ├── FakeHermesClient (local/CI)
        └── HermesApiClient (reserved; fails clearly until wired)
```

## Runtime-owned responsibilities

- Health/readiness/version endpoints and request logging.
- Runtime session lifecycle and concurrency guard (`MAX_SESSIONS=1` in this milestone).
- LiveKit telephony event ingestion:
  - `/telephony/livekit/webhook` for LiveKit participant events.
  - `/telephony/livekit/events/*` for simulated CI/local event injection.
- Room -> runtime session mapping with independent per-call state.
- Raw audio packet/frame counting and verification-buffer discard.
- Metadata APIs:
  - `GET /calls`
  - `GET /calls/{callId}`
  - `GET /rooms`
- Cleanup of runtime session, LiveKit room, audio buffers, and active room mapping.

## LiveKit modes

`LIVEKIT_CONTROL_MODE=simulated` is the default CI/local mode. It does not contact LiveKit; tests and smoke checks drive the same gateway boundary via authenticated HTTP event endpoints.

`LIVEKIT_CONTROL_MODE=sdk` uses configured `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` to create/delete LiveKit rooms and starts an RTC room listener. The listener subscribes to LiveKit audio tracks and forwards frame sizes to `VoiceGateway.receive_audio_frame_payload()`. Audio payloads are not persisted.

LiveKit webhooks create/end call lifecycle records from real SIP participant events. The gateway ignores non-SIP participants (including the voice-agent participant) to avoid bogus calls. For SIP participants, it prefers `sip.callID` as the call id and `sip.phoneNumber`/`sip.from` as caller metadata when those attributes are present.

## Security and retention

`TELEPHONY_EVENT_TOKEN` protects simulated event endpoints and call/room metadata APIs. `/telephony/livekit/webhook` accepts real LiveKit signed webhook JWTs when `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` are configured, and also accepts the bearer token for local development and non-LiveKit test proxies. Requests must include the configured bearer value or LiveKit JWT in the HTTP `Authorization` header.

Local Docker binds service ports to `127.0.0.1` by default. Operators must replace the dev token before exposing the service or accepting real webhooks.

Call metadata is bounded by `TELEPHONY_CALL_HISTORY_LIMIT` (default 100). Active calls are never pruned; terminal calls are pruned oldest-first when the limit is exceeded.

## Not runtime-owned in PRD-002

- Speech-to-text.
- Text-to-speech.
- OpenAI Realtime.
- Hermes reasoning, prompts, skills, memory, and tool orchestration.
- Dashboard UI.
- Production SIP trunk purchase/number provisioning; docs provide a real-call acceptance path.
