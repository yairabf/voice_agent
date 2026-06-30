# PRD-002 — LiveKit Telephony Integration

## Project

- Project: `voice_agent`
- Path: `/home/ubuntu/workspace/projects/voice_agent`
- Branch: `feature/prd-002-livekit-telephony`
- PR title: `feat(prd-002): LiveKit telephony integration`

## Objective

Extend the Hermes Voice Runtime by integrating self-hosted LiveKit as the telephony layer.

The milestone establishes a reliable, production-ready connection between incoming phone calls and the Hermes Voice Runtime.

No AI conversation occurs in this milestone. The gateway receives audio and manages transport/session lifecycle only.

## Problem / user need

`voice_agent` needs a real telephony ingress path so phone calls can reach the runtime. Before STT, TTS, OpenAI Realtime, or Hermes reasoning are added, the system must prove that incoming calls reach LiveKit, rooms are created/managed, the Voice Gateway subscribes to audio, runtime sessions are created and mapped, audio frames reach the runtime boundary, and resources clean up reliably.

## Desired outcome

A real phone call can enter the system through LiveKit, create a runtime session, stream raw audio frames to the Voice Gateway/runtime audio buffer, and clean up without orphaned rooms or sessions when the call ends.

## Current behavior

The runtime foundation exists or is expected from PRD-001, but there is no completed telephony layer connecting real phone calls to runtime sessions.

## Desired behavior

```text
Phone Call
  ↓
Phone Number / SIP Route
  ↓
Self-hosted LiveKit SIP
  ↓
LiveKit Room
  ↓
Voice Gateway
  ↓
Hermes Runtime Session
  ↓
AudioSessionManager
  ↓
Audio Buffer
  ↓
Discard
```

Audio is intentionally discarded in PRD-002 after being counted/buffered enough to verify ingress.

## Scope

### In scope

- Self-hosted LiveKit integration.
- LiveKit SIP / telephony ingress configuration path.
- Voice Gateway connection to LiveKit.
- Incoming call event handling.
- LiveKit room/session lifecycle management.
- Runtime session creation on incoming call.
- Room → Runtime Session mapping.
- Independent per-call state.
- Audio frame subscription and receipt.
- Audio buffering/counting for future STT.
- Audio discard after verification.
- Minimal metadata APIs: `GET /calls`, `GET /calls/{id}`, `GET /rooms`.
- Integration tests using simulated SIP/LiveKit/runtime events.
- Real-world acceptance test using one real phone call.
- Docker/config/deployment updates needed for LiveKit support.
- API documentation.
- Smoke tests after deployment.

### Out of scope

- STT
- TTS
- OpenAI Realtime
- Hermes reasoning
- Memory
- Tool execution
- AI conversation
- LLM prompts
- Voice generation

The gateway should only receive audio and manage telephony/session transport.

## Architecture requirement: provider adapter interface

The Voice Gateway must be designed around a telephony provider abstraction from the start.

```text
TelephonyProvider
├── LiveKitAdapter        # implemented in PRD-002
├── TwilioAdapter         # future
├── SIPAdapter            # future
└── BrowserWebRTCAdapter  # future
```

PRD-002 only implements `LiveKitAdapter`.

The rest of the gateway/runtime code must depend on the provider interface, not on LiveKit-specific APIs. This prevents LiveKit coupling from spreading into runtime logic and allows future providers without redesigning the runtime.

## Components

### LiveKit

Responsible for answering/receiving incoming calls, creating/managing rooms, managing SIP connection flow, emitting participant/track/call lifecycle events, and handling disconnect/reconnect cases where possible.

### Voice Gateway

Responsible for connecting to self-hosted LiveKit, subscribing to incoming call audio, creating runtime sessions, maintaining room/session/caller mapping, receiving raw audio frames, buffering/counting audio frames for future STT, exposing minimal call/room metadata APIs, and cleaning resources on call end.

### Runtime

Add or extend an `AudioSessionManager` responsible for audio buffers, frame timestamps, room/session mapping, per-call state, packet/frame counts, cleanup, and lifecycle status.

## Session mapping

Each call should maintain independent state similar to:

```json
{
  "callId": "...",
  "runtimeSessionId": "...",
  "livekitRoomId": "...",
  "callerId": "...",
  "createdAt": "...",
  "connectedAt": "...",
  "endedAt": null,
  "status": "connected",
  "packetCount": 0,
  "disconnectReason": null
}
```

## Runtime concurrency behavior

From PRD-002 onward, the architecture must support multiple concurrent calls.

The Voice Gateway must never assume a single caller. It must manage Room → Runtime Session mapping, session lifecycle, cleanup, and independent call state.

However, the actual Hermes runtime may initially limit active conversations to one, or to a configurable maximum. That is an implementation constraint, not an architectural constraint. Future versions should be able to increase the concurrency limit without redesigning the system.

If the runtime cannot actively process more than one call, the gateway should still model calls independently and either reject/mark overflow calls clearly, or create mappings but mark runtime processing unavailable, depending on what coder finds safest during implementation.

## Configuration

Required environment/config values:

```env
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
```

Because this is self-hosted LiveKit, coder should determine whether local/dev credentials can be generated automatically for local testing.

Expected behavior:

- Local/dev: generate or document local LiveKit credentials where feasible.
- Production/Hermes VM: use managed secret/env configuration; do not hardcode secrets.
- Tests: use mocks/fakes/simulated events where possible.

## Phone number / eSIM / SIP assumption

Yair has a real eSIM/phone number and wants to know whether it can be used.

Requirement:

- Investigate whether the real eSIM/number can route calls into LiveKit.
- If the carrier/eSIM supports SIP trunking, SIP forwarding, or an equivalent bridge, document and use that path.
- If a normal eSIM cannot directly connect to LiveKit, document why and provide the required alternative: LiveKit Cloud Number, Twilio SIP trunk, or another SIP-compatible provider.

Acceptance should require one real call before milestone closure, but CI should not depend on a real phone call.

## Audio pipeline

```text
Caller
  ↓
LiveKit
  ↓
PCM / raw audio frames
  ↓
Voice Gateway
  ↓
AudioSessionManager buffer/counter
  ↓
Discard
```

Verification of audio arrival may use packet/frame count, timestamps, and metadata logs. No audio transcription or AI response is required.

## Call lifecycle

```text
Incoming Call
  ↓
Create / join LiveKit Room
  ↓
Create Runtime Session
  ↓
Associate Room + Runtime Session
  ↓
Receive Audio
  ↓
Track packet/frame metadata
  ↓
Call Ends
  ↓
Destroy / close Runtime Session
  ↓
Destroy / leave LiveKit Room
  ↓
Remove active mapping
  ↓
Expose final call metadata
```

## Minimal API endpoints

Implement functional endpoints, not stubs.

### `GET /calls`

Returns basic metadata for recent/active calls: call ID, room ID, runtime session ID, status, caller ID if available, start time, end time, duration, packet/frame count, and disconnect reason if available.

### `GET /calls/{id}`

Returns detailed metadata for one call.

### `GET /rooms`

Returns LiveKit/runtime room mapping metadata.

No UI/dashboard is required in PRD-002.

## Error handling

Handle and test where feasible: dropped calls, reconnects, duplicate events, SIP timeouts, unexpected disconnects, runtime shutdown, LiveKit unavailable, runtime session creation failure, cleanup after partial failure, duplicate cleanup calls, and concurrent call mapping.

## Logging

Capture structured logs for caller number/caller ID when available, call ID, LiveKit room ID, runtime session ID, call status, call duration, disconnect reason, packet/frame count, jitter/latency if available from LiveKit, room creation latency, runtime session creation latency, and cleanup result.

## Metrics

Track or prepare counters/gauges for active calls, failed calls, completed calls, room creation latency, runtime session creation latency, audio throughput/packet count, cleanup failures, and orphan session count.

## Testing and verification

### CI tests

CI should use simulated/mocked SIP events, LiveKit events, runtime sessions, and audio frame events.

CI must verify incoming call event creates LiveKit room/session mapping, runtime session is created, call metadata is exposed through APIs, audio frame receipt increments packet/frame metadata, duplicate events are handled safely, call termination cleans resources, no orphan sessions remain after cleanup, multiple concurrent call mappings do not overwrite one another, and runtime concurrency limit is represented safely.

No real phone call is required in CI.

### Acceptance testing

Before the milestone can be closed:

- perform one real inbound call using Yair’s phone/real number path if possible,
- verify call reaches LiveKit,
- verify LiveKit room is created,
- verify runtime session is created,
- verify room/session mapping,
- verify audio packet/frame count increases,
- verify call termination cleanup,
- verify metadata endpoints show the completed call,
- verify no orphan sessions remain.

## Design/mockup decision

Design/mockups required: No.

Reason: this is a backend/runtime/telephony milestone. No user-facing dashboard UI is included. API endpoints are functional validation surfaces only.

If dashboard UI is later added, that should be a separate PRD/design-gated task.

## Documentation requirements

PRD-002 should include documentation for required environment variables, self-hosted LiveKit setup assumptions, local/dev credential generation if implemented, SIP/phone-number configuration path, eSIM feasibility findings, provider adapter architecture, API endpoint usage, test strategy, real-call acceptance procedure, and deployment/smoke-test procedure.

The standard active worker set is `coder`, `reviewer`, `qa`, and `coordinator`. If a separate documentation agent profile is available, route documentation review there; otherwise documentation deliverables should be produced by `coder` and checked by `reviewer`/`qa`.

## Release / PR workflow

Every PRD milestone should follow this project convention:

```text
Feature Branch
  ↓
Pull Request
  ↓
Reviewer Agent
  ↓
QA Agent
  ↓
Documentation Agent / Documentation Review
  ↓
Manual Approval by Yair
  ↓
Merge
  ↓
Automatic Deployment
  ↓
Smoke Tests
  ↓
Hermes Verification
  ↓
Milestone Complete
```

For PRD-002 specifically:

- Branch: `feature/prd-002-livekit-telephony`
- PR title: `feat(prd-002): LiveKit telephony integration`
- Never deploy directly from feature branches.
- Deploy automatically only after merge to `main`.
- After merge, coordinator verifies local `main`, deployment, and smoke tests.

## Acceptance criteria

PRD-002 is complete when:

- Self-hosted LiveKit is operational for the project.
- Incoming call flow reaches LiveKit.
- LiveKit creates/manages a room for the call.
- Runtime creates a session for the call.
- Room and runtime session are linked.
- Voice Gateway receives raw audio packets/frames.
- Audio packets/frames are counted or otherwise observable.
- Audio is discarded after verification.
- Multiple call mappings are architecturally supported without global single-caller assumptions.
- Runtime concurrency limitation is explicit and safe.
- `GET /calls` works.
- `GET /calls/{id}` works.
- `GET /rooms` works.
- Call termination cleans runtime session, room/mapping state, and buffers.
- No orphan sessions remain after call end.
- CI integration tests pass using simulated events.
- One real call acceptance test is completed before closure.
- Documentation is updated.
- PR is reviewed by reviewer.
- QA validates behavior.
- Yair manually approves merge.
- Merge to `main` triggers/permits automatic deployment.
- Smoke tests pass after deployment.
- Hermes verification confirms the deployed milestone.

## First owner

First owner after PRD approval: `coder`.

Rationale: no design/mockups are needed. The next step is technical discovery and implementation: self-hosted LiveKit setup, eSIM/SIP feasibility, adapter design, runtime/session/audio integration, tests, and docs.
