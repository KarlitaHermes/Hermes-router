#!/usr/bin/env bash
#
# hr mode — choose how keys are picked within each provider
#
# Usage:
#   hr mode                 Show the current rotation mode
#   hr mode round-robin     Spread requests evenly across all keys (default)
#   hr mode sequential      Drain one key fully before moving to the next
#   hr mode help            Show this help
#
# Modes:
#   round-robin  All keys share the load, so they deplete together. Best for
#                spreading latency and load across many keys.
#   sequential   One key is used until it rate-limits, then the next, and so on.
#                Keeps later keys/accounts untouched in reserve — useful when you
#                want to ration accounts after a quota reset instead of burning
#                them all at once.
#
# The mode is written to .env (ROTATION_MODE) and takes effect after: hr restart
#
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo dir"; exit 1; }
ENV_FILE="$REPO/.env"
PYTHON="${REPO}/venv/bin/python"
[ -f "$PYTHON" ] || PYTHON=python3

log()  { printf '\033[1;36m[mode]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[mode]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[mode]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[mode]\033[0m %s\n' "$*"; }

DEFAULT_MODE="round-robin"
ENV_KEY="ROTATION_MODE"

# Normalize a mode name (accepts a couple of friendly aliases).
canonical_mode() {
  case "${1,,}" in
    round-robin|roundrobin|round_robin|rr) echo "round-robin" ;;
    sequential|seq|drain)                  echo "sequential" ;;
    *)                                     echo "" ;;
  esac
}

# Read a single key from .env (last occurrence wins).
read_env() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return
  grep "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2-
}

# Write or delete a key in .env. Pass empty value to delete.
write_env() {
  local key="$1"
  local val="$2"
  "$PYTHON" - "$ENV_FILE" "$key" "$val" <<'PY'
import os, sys
path, key, val = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(path).readlines() if os.path.exists(path) else []
found, out = False, []
for line in lines:
    if line.strip().startswith(f"{key}="):
        if val:                          # set: replace line
            out.append(f"{key}={val}\n")
        found = True                     # reset: skip line (delete)
    else:
        out.append(line)
if not found and val:                    # new key
    out.append(f"{key}={val}\n")
with open(path, "w") as f:
    f.writelines(out)
PY
}

# ── hr mode  (no args) — show current mode ────────────────────────────────────

cmd_show() {
  local current
  current=$(read_env "$ENV_KEY")
  current=$(canonical_mode "${current:-$DEFAULT_MODE}")
  [ -n "$current" ] || current="$DEFAULT_MODE"

  echo ""
  if [ "$current" = "$DEFAULT_MODE" ] && [ -z "$(read_env "$ENV_KEY")" ]; then
    printf '  Rotation mode: \033[1;32m%s\033[0m  (default)\n' "$current"
  else
    printf '  Rotation mode: \033[1;33m%s\033[0m\n' "$current"
  fi
  echo ""
  log "Change it with:  hr mode round-robin | sequential"
  log "Stored in: $ENV_FILE  ·  run 'hr restart' to apply."
}

# ── hr mode <name> — set mode ─────────────────────────────────────────────────

cmd_set() {
  local raw="$1"
  local mode
  mode=$(canonical_mode "$raw")
  if [ -z "$mode" ]; then
    err "Unknown mode: '$raw'"
    err "Valid modes: round-robin (or rr), sequential (or seq)"
    exit 1
  fi

  local current
  current=$(read_env "$ENV_KEY")
  current=$(canonical_mode "${current:-$DEFAULT_MODE}")
  [ -n "$current" ] || current="$DEFAULT_MODE"

  if [ "$current" = "$mode" ]; then
    warn "Rotation mode is already: $mode"
    exit 0
  fi

  if [ "$mode" = "$DEFAULT_MODE" ]; then
    write_env "$ENV_KEY" ""              # back to default → drop the override
  else
    write_env "$ENV_KEY" "$mode"
  fi
  ok "Rotation mode: $current  →  $mode"
  log "Run 'hr restart' to apply."
}

# ── Dispatch ─────────────────────────────────────────────────────────────────

subcmd="${1:-show}"

case "$subcmd" in
  ""|show|list|status)  cmd_show ;;
  help|-h|--help)       awk 'NR>1 && /^#/ {sub(/^#[[:space:]]?/,""); print; next} NR>1 {exit}' "$0" ;;
  *)                    cmd_set "$subcmd" ;;
esac
