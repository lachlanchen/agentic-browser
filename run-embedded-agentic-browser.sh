#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
exec ./embedded_agentic_browser/run.sh
