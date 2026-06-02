#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
exec python3 -m embedded_agentic_browser.standalone "$@"
