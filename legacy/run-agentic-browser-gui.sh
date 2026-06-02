#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

HOST="${AGENTIC_BROWSER_HOST:-127.0.0.1}"
PORT="${AGENTIC_BROWSER_PORT:-8789}"
BROWSER_PORT="${AGENTIC_BROWSER_CHROME_PORT:-9223}"
MODEL="${AGENTIC_BROWSER_MODEL:-gpt-5.4-mini}"
REASONING="${AGENTIC_BROWSER_REASONING:-low}"

if [[ "$#" -gt 0 ]]; then
  exec python3 agentic_browser.py "$@"
fi

exec python3 agentic_browser.py \
  --host "$HOST" \
  --port "$PORT" \
  --browser-port "$BROWSER_PORT" \
  --model "$MODEL" \
  --reasoning-effort "$REASONING"
