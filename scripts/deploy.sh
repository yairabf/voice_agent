#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-/opt/hermes-voice-runtime}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${TARGET_DIR}" != /* ]]; then
  echo "Target directory must be absolute: ${TARGET_DIR}" >&2
  exit 2
fi

if [[ "${HERMES_INTEGRATION_MODE:-fake}" == "api" ]]; then
  echo "Refusing api mode: dedicated Hermes API/profile is not wired in PRD-001." >&2
  exit 3
fi

mkdir -p "${TARGET_DIR}"
rsync -a --delete \
  --exclude .git \
  --exclude .venv \
  --exclude .env \
  --exclude __pycache__ \
  "${SOURCE_DIR}/" "${TARGET_DIR}/"

cd "${TARGET_DIR}"
docker build -t voice-agent:latest .

echo "Deployment files copied to ${TARGET_DIR}"
echo "Next: cd ${TARGET_DIR} && docker compose up -d --build"
echo "Then: ${TARGET_DIR}/scripts/smoke_test.sh http://127.0.0.1:8088"
