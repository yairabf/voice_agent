#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8088}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local out="$4"
  if [[ -n "${body}" ]]; then
    curl -fsS -X "${method}" "${BASE_URL}${path}" \
      -H 'content-type: application/json' \
      -d "${body}" \
      -o "${out}"
  else
    curl -fsS -X "${method}" "${BASE_URL}${path}" -o "${out}"
  fi
}

request GET /health '' "${TMP_DIR}/health.json"
python -m json.tool "${TMP_DIR}/health.json" >/dev/null

grep -q '"status"' "${TMP_DIR}/health.json"

request GET /ready '' "${TMP_DIR}/ready.json"
grep -q '"ready"' "${TMP_DIR}/ready.json"

request GET /version '' "${TMP_DIR}/version.json"
grep -q '"service"' "${TMP_DIR}/version.json"

request POST /sessions '' "${TMP_DIR}/session.json"
SESSION_ID="$(python - <<'PY' "${TMP_DIR}/session.json"
import json, sys
print(json.load(open(sys.argv[1]))['sessionId'])
PY
)"

SECOND_STATUS="$(curl -sS -o "${TMP_DIR}/second.json" -w '%{http_code}' -X POST "${BASE_URL}/sessions")"
if [[ "${SECOND_STATUS}" != "409" ]]; then
  echo "Expected second session to return 409, got ${SECOND_STATUS}" >&2
  cat "${TMP_DIR}/second.json" >&2
  exit 1
fi

request POST "/sessions/${SESSION_ID}/messages" '{"message":"Hello from smoke test"}' "${TMP_DIR}/message.json"
grep -q '"accepted"' "${TMP_DIR}/message.json"

request GET "/sessions/${SESSION_ID}/stream" '' "${TMP_DIR}/stream.txt"
grep -q 'event: thinking' "${TMP_DIR}/stream.txt"
grep -q 'event: delta' "${TMP_DIR}/stream.txt"
grep -q 'event: completed' "${TMP_DIR}/stream.txt"

request DELETE "/sessions/${SESSION_ID}" '' "${TMP_DIR}/close.json"
grep -q '"closed"' "${TMP_DIR}/close.json"

request POST /telephony/livekit/events/incoming-call \
  '{"callId":"smoke-call-1","roomId":"smoke-room-1","callerId":"smoke"}' \
  "${TMP_DIR}/incoming-call.json"
grep -q '"callId":"smoke-call-1"' "${TMP_DIR}/incoming-call.json"
grep -q '"runtimeSessionId"' "${TMP_DIR}/incoming-call.json"

request POST /telephony/livekit/events/audio-frame \
  '{"callId":"smoke-call-1","payloadSize":320,"timestampMs":1}' \
  "${TMP_DIR}/audio-frame.json"
grep -q '"packetCount":1' "${TMP_DIR}/audio-frame.json"

request GET /calls '' "${TMP_DIR}/calls.json"
grep -q '"packetCount":1' "${TMP_DIR}/calls.json"
request GET /rooms '' "${TMP_DIR}/rooms.json"
grep -q '"livekitRoomId":"smoke-room-1"' "${TMP_DIR}/rooms.json"

request POST /telephony/livekit/events/call-ended \
  '{"callId":"smoke-call-1","disconnectReason":"smoke_complete"}' \
  "${TMP_DIR}/call-ended.json"
grep -q '"status":"ended"' "${TMP_DIR}/call-ended.json"

echo "Smoke test passed for ${BASE_URL}"
