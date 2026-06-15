#!/usr/bin/env bash
#
# hr restart — restart the router so config/key changes take effect
#
# Use this after `hr auth add` (or any .env change). It restarts cleanly:
#   • If a systemd service exists, it restarts that.
#   • Otherwise it finds the running router.py process, stops it, and relaunches
#     it in the background (logging to ./router.log).
# Either way it then health-checks the router and tells you the result.
#
# Usage:
#   hr restart
#
# Optional env overrides:
#   PORT=8319                      # port to health-check
#   PYTHON=python3                 # interpreter for the background fallback
#   HERMES_ROUTER_SERVICE=my-svc   # systemd unit name (default: hermes-router)
#
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo dir"; exit 1; }
PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8319}"
SERVICE="${HERMES_ROUTER_SERVICE:-hermes-router}"

log() { printf '\033[1;36m[restart]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[restart]\033[0m %s\n' "$*" >&2; }
ok()  { printf '\033[1;32m[restart]\033[0m %s\n' "$*"; }

# Wait up to ~15s for /health to come back. 0=healthy, 1=not, 2=can't check.
health_ok() {
  command -v curl >/dev/null 2>&1 || return 2
  for _ in $(seq 1 15); do
    curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

report_health() {
  health_ok
  case $? in
    0) ok "router is healthy on :${PORT}.  (see:  hr status)" ;;
    2) ok "restarted (install 'curl' to enable health checks)." ;;
    *) err "router did not come back healthy on :${PORT} — check the logs."; exit 1 ;;
  esac
}

# 1) systemd path -----------------------------------------------------------------
if command -v systemctl >/dev/null 2>&1 \
   && systemctl cat "${SERVICE}.service" >/dev/null 2>&1; then
  log "restarting systemd service '${SERVICE}'…"
  if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    sudo systemctl restart "$SERVICE" || { err "systemctl restart failed."; exit 1; }
  else
    systemctl restart "$SERVICE" || { err "systemctl restart failed."; exit 1; }
  fi
  report_health
  exit 0
fi

# 2) standalone process path ------------------------------------------------------
# Find a running router.py belonging to this repo (best-effort).
pids="$(pgrep -f "${REPO}/router.py" 2>/dev/null || pgrep -f "router.py" 2>/dev/null || true)"
if [ -n "$pids" ]; then
  log "stopping running router (pid: $(echo "$pids" | tr '\n' ' '))…"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 10); do
    pgrep -f "${REPO}/router.py" >/dev/null 2>&1 || break
    sleep 1
  done
  # force-kill anything still alive
  pids="$(pgrep -f "${REPO}/router.py" 2>/dev/null || true)"
  # shellcheck disable=SC2086
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
else
  log "no running router found — starting a fresh one."
fi

log "launching router in the background (logging to ${REPO}/router.log)…"
nohup "$PYTHON" "$REPO/router.py" >> "$REPO/router.log" 2>&1 &
disown 2>/dev/null || true

report_health
