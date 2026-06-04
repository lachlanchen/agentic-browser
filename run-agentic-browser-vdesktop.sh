#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SESSION="${AGENTIC_VDESKTOP_SESSION:-agentic-browser-vdesktop}"
MODE="${AGENTIC_VDESKTOP_MODE:-xephyr}"
DISPLAY_ID="${AGENTIC_VDESKTOP_DISPLAY:-:78}"
GEOMETRY="${AGENTIC_VDESKTOP_GEOMETRY:-1600x1000}"
XEPHYR_DEPTH="${AGENTIC_VDESKTOP_XEPHYR_DEPTH:-24}"
XEPHYR_FALLBACK_DEPTH="${AGENTIC_VDESKTOP_XEPHYR_FALLBACK_DEPTH:-16/16}"
XEPHYR_EXTRA_ARGS="${AGENTIC_VDESKTOP_XEPHYR_EXTRA_ARGS:--glamor}"
GUI_PORT="${AGENTIC_VDESKTOP_GUI_PORT:-8794}"
BROWSER_PORT="${AGENTIC_VDESKTOP_BROWSER_PORT:-9344}"
PROFILE_DIR="${AGENTIC_VDESKTOP_PROFILE:-$HOME/.cache/agentic-browser-vdesktop-chrome}"
MODEL="${AGENTIC_VDESKTOP_MODEL:-gpt-5.4-mini}"
REASONING="${AGENTIC_VDESKTOP_REASONING:-low}"
LOG_DIR="$ROOT/library/agentic-browser-vdesktop"
STATE_FILE="$LOG_DIR/${SESSION}.state"

usage() {
  cat <<EOF
Usage: $0 {start|stop|status|logs|daemon}

Starts the embedded agentic browser in an isolated virtual display/session.

Environment overrides:
  AGENTIC_VDESKTOP_MODE=auto|xvfb|xephyr|headless
  AGENTIC_VDESKTOP_SESSION=$SESSION
  AGENTIC_VDESKTOP_DISPLAY=$DISPLAY_ID
  AGENTIC_VDESKTOP_GEOMETRY=$GEOMETRY
  AGENTIC_VDESKTOP_XEPHYR_DEPTH=$XEPHYR_DEPTH
  AGENTIC_VDESKTOP_XEPHYR_FALLBACK_DEPTH=$XEPHYR_FALLBACK_DEPTH
  AGENTIC_VDESKTOP_XEPHYR_EXTRA_ARGS=$XEPHYR_EXTRA_ARGS
  AGENTIC_VDESKTOP_GUI_PORT=$GUI_PORT
  AGENTIC_VDESKTOP_BROWSER_PORT=$BROWSER_PORT
  AGENTIC_VDESKTOP_PROFILE=$PROFILE_DIR
  AGENTIC_VDESKTOP_MODEL=$MODEL
  AGENTIC_VDESKTOP_REASONING=$REASONING
EOF
}

have() {
  command -v "$1" >/dev/null 2>&1
}

write_state() {
  mkdir -p "$LOG_DIR"
  {
    printf 'SESSION=%q\n' "$SESSION"
    printf 'MODE=%q\n' "$MODE"
    printf 'DISPLAY_ID=%q\n' "$DISPLAY_ID"
    printf 'GEOMETRY=%q\n' "$GEOMETRY"
    printf 'XEPHYR_DEPTH=%q\n' "$XEPHYR_DEPTH"
    printf 'XEPHYR_FALLBACK_DEPTH=%q\n' "$XEPHYR_FALLBACK_DEPTH"
    printf 'XEPHYR_EXTRA_ARGS=%q\n' "$XEPHYR_EXTRA_ARGS"
    printf 'GUI_PORT=%q\n' "$GUI_PORT"
    printf 'BROWSER_PORT=%q\n' "$BROWSER_PORT"
    printf 'PROFILE_DIR=%q\n' "$PROFILE_DIR"
    printf 'MODEL=%q\n' "$MODEL"
    printf 'REASONING=%q\n' "$REASONING"
    printf 'LOG_DIR=%q\n' "$LOG_DIR"
  } > "$STATE_FILE"
}

load_state() {
  if [[ -f "$STATE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE"
  fi
}

choose_mode() {
  if [[ "$MODE" != "auto" ]]; then
    printf '%s\n' "$MODE"
    return
  fi
  if have Xephyr; then
    printf 'xephyr\n'
  elif have Xvfb; then
    printf 'xvfb\n'
  else
    printf 'headless\n'
  fi
}

start_window_manager() {
  if have openbox; then
    openbox >>"$LOG_DIR/window-manager.log" 2>&1 &
  elif have fluxbox; then
    fluxbox >>"$LOG_DIR/window-manager.log" 2>&1 &
  elif have xfwm4; then
    xfwm4 >>"$LOG_DIR/window-manager.log" 2>&1 &
  elif have matchbox-window-manager; then
    matchbox-window-manager >>"$LOG_DIR/window-manager.log" 2>&1 &
  fi
}

kill_profile_processes() {
  local pids
  pids="$(pgrep -af "$PROFILE_DIR" | awk -v self="$$" '$1 != self {print $1}' || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill $pids >/dev/null 2>&1 || true
    sleep 1
    # shellcheck disable=SC2086
    kill -9 $pids >/dev/null 2>&1 || true
  fi
}

kill_display_processes() {
  local display="$1"
  local display_num="${display#:}"
  local pids
  pids="$(pgrep -af "(Xephyr|Xvfb) ${display}( |$)" | awk -v self="$$" '$1 != self {print $1}' || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill $pids >/dev/null 2>&1 || true
    sleep 1
    # shellcheck disable=SC2086
    kill -9 $pids >/dev/null 2>&1 || true
  fi
  if [[ -n "$display_num" ]]; then
    rm -f "/tmp/.X${display_num}-lock" "/tmp/.X11-unix/X${display_num}" >/dev/null 2>&1 || true
  fi
}

wait_for_service() {
  local url="http://127.0.0.1:$GUI_PORT/api/status"
  if ! have curl; then
    sleep 2
    return 0
  fi
  for _ in $(seq 1 40); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "Service did not become ready: $url" >&2
  "$0" logs >&2 || true
  return 1
}

start_xephyr() {
  local depth="$1"
  shift
  local -a extra_args=("$@")
  Xephyr "$DISPLAY_ID" \
    -screen "${GEOMETRY}x${depth}" \
    "${extra_args[@]}" \
    -resizeable \
    -title "Agentic Browser Virtual Desktop" \
    -nolisten tcp \
    >>"$LOG_DIR/xserver.log" 2>&1 &
  x_pid="$!"
  sleep 1
  if ps -p "$x_pid" >/dev/null 2>&1; then
    return 0
  fi
  wait "$x_pid" >/dev/null 2>&1 || true
  x_pid=""
  return 1
}

daemon() {
  mkdir -p "$LOG_DIR"
  local selected_mode
  selected_mode="$(choose_mode)"
  MODE="$selected_mode"
  write_state
  local x_pid=""
  local server_pid=""

  echo "Agentic browser virtual desktop"
  echo "Mode: $selected_mode"
  echo "GUI: http://127.0.0.1:$GUI_PORT"
  echo "CDP: http://127.0.0.1:$BROWSER_PORT"
  echo "Profile: $PROFILE_DIR"
  echo "Logs: $LOG_DIR"

  case "$selected_mode" in
    xvfb)
      if ! have Xvfb; then
        echo "Xvfb is not installed. Install it or use AGENTIC_VDESKTOP_MODE=xephyr/headless." >&2
        exit 1
      fi
      kill_display_processes "$DISPLAY_ID"
      Xvfb "$DISPLAY_ID" -screen 0 "${GEOMETRY}x24" -nolisten tcp >>"$LOG_DIR/xserver.log" 2>&1 &
      x_pid="$!"
      export DISPLAY="$DISPLAY_ID"
      sleep 1
      start_window_manager
      ;;
    xephyr)
      if ! have Xephyr; then
        echo "Xephyr is not installed. Install it or use AGENTIC_VDESKTOP_MODE=headless." >&2
        exit 1
      fi
      kill_display_processes "$DISPLAY_ID"
      # 24-bit Xephyr needs glamor in some XRDP/Xvnc sessions. Fall back to the
      # older 16-bit mode only if the high-color launch fails.
      # shellcheck disable=SC2206
      local xephyr_extra_args=( $XEPHYR_EXTRA_ARGS )
      if ! start_xephyr "$XEPHYR_DEPTH" "${xephyr_extra_args[@]}"; then
        echo "Xephyr ${GEOMETRY}x${XEPHYR_DEPTH} failed; retrying ${GEOMETRY}x${XEPHYR_FALLBACK_DEPTH}" >>"$LOG_DIR/xserver.log"
        kill_display_processes "$DISPLAY_ID"
        start_xephyr "$XEPHYR_FALLBACK_DEPTH" || {
          echo "Xephyr failed to start. See $LOG_DIR/xserver.log" >&2
          exit 1
        }
      fi
      export DISPLAY="$DISPLAY_ID"
      start_window_manager
      ;;
    headless)
      unset DISPLAY
      local width="${GEOMETRY%x*}"
      local height="${GEOMETRY#*x}"
      export EMBEDDED_AGENTIC_CHROME_ARGS="${EMBEDDED_AGENTIC_CHROME_ARGS:-} --headless=new --window-size=${width},${height}"
      ;;
    *)
      echo "Unknown AGENTIC_VDESKTOP_MODE: $selected_mode" >&2
      exit 1
      ;;
  esac

  cleanup() {
    if [[ -n "$server_pid" ]]; then
      kill "$server_pid" >/dev/null 2>&1 || true
    fi
    kill_profile_processes
    if [[ -n "$x_pid" ]]; then
      kill "$x_pid" >/dev/null 2>&1 || true
    fi
  }
  trap cleanup EXIT INT TERM

  export EMBEDDED_AGENTIC_HOST=127.0.0.1
  export EMBEDDED_AGENTIC_PORT="$GUI_PORT"
  export EMBEDDED_AGENTIC_BROWSER_PORT="$BROWSER_PORT"
  export EMBEDDED_AGENTIC_PROFILE="$PROFILE_DIR"
  export EMBEDDED_AGENTIC_MODEL="$MODEL"
  export EMBEDDED_AGENTIC_REASONING="$REASONING"

  ./embedded_agentic_browser/run.sh &
  server_pid="$!"
  wait "$server_pid"
}

start() {
  if tmux has-session -t "$SESSION" >/dev/null 2>&1; then
    echo "Session already running: $SESSION"
    "$0" status
    exit 0
  fi
  write_state
  local command
  printf -v command \
    'AGENTIC_VDESKTOP_SESSION=%q AGENTIC_VDESKTOP_MODE=%q AGENTIC_VDESKTOP_DISPLAY=%q AGENTIC_VDESKTOP_GEOMETRY=%q AGENTIC_VDESKTOP_XEPHYR_DEPTH=%q AGENTIC_VDESKTOP_XEPHYR_FALLBACK_DEPTH=%q AGENTIC_VDESKTOP_XEPHYR_EXTRA_ARGS=%q AGENTIC_VDESKTOP_GUI_PORT=%q AGENTIC_VDESKTOP_BROWSER_PORT=%q AGENTIC_VDESKTOP_PROFILE=%q AGENTIC_VDESKTOP_MODEL=%q AGENTIC_VDESKTOP_REASONING=%q %q daemon' \
    "$SESSION" "$MODE" "$DISPLAY_ID" "$GEOMETRY" "$XEPHYR_DEPTH" "$XEPHYR_FALLBACK_DEPTH" "$XEPHYR_EXTRA_ARGS" "$GUI_PORT" "$BROWSER_PORT" "$PROFILE_DIR" "$MODEL" "$REASONING" "$0"
  tmux new-session -d -s "$SESSION" "$command"
  wait_for_service
  "$0" status
}

stop() {
  load_state
  tmux kill-session -t "$SESSION" >/dev/null 2>&1 || true
  kill_profile_processes
  kill_display_processes "$DISPLAY_ID"
  rm -f "$STATE_FILE"
  echo "Stopped session: $SESSION"
}

status() {
  load_state
  if tmux has-session -t "$SESSION" >/dev/null 2>&1; then
    echo "Session: $SESSION running"
    echo "GUI: http://127.0.0.1:$GUI_PORT"
    echo "CDP: http://127.0.0.1:$BROWSER_PORT"
    echo "Mode: $MODE"
    echo "Display: $DISPLAY_ID"
    echo "Logs: $LOG_DIR"
  else
    echo "Session: $SESSION not running"
    exit 1
  fi
}

logs() {
  tmux capture-pane -p -t "$SESSION" -S -120
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  logs) logs ;;
  daemon) daemon ;;
  -h|--help|help) usage ;;
  *) usage; exit 1 ;;
esac
