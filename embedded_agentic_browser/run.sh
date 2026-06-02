#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m embedded_agentic_browser.server \
  --host "${EMBEDDED_AGENTIC_HOST:-127.0.0.1}" \
  --port "${EMBEDDED_AGENTIC_PORT:-8791}" \
  --browser-port "${EMBEDDED_AGENTIC_BROWSER_PORT:-9333}" \
  --profile-dir "${EMBEDDED_AGENTIC_PROFILE:-$HOME/.cache/embedded-agentic-browser-chrome}" \
  --model "${EMBEDDED_AGENTIC_MODEL:-gpt-5.4-mini}" \
  --reasoning-effort "${EMBEDDED_AGENTIC_REASONING:-low}"
