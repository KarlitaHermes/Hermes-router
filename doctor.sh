#!/usr/bin/env bash
#
# hr doctor — diagnose your hermes-router installation
#
# Checks Python, venv, dependencies, API keys, PATH, and whether
# the router is currently running. Prints ✓/✗/! for each.
#
set -uo pipefail

cd "$(dirname "$0")" || { echo "cannot cd to script dir"; exit 1; }
REPO="$(pwd)"

pass() { printf '  \033[1;32m[✓]\033[0m %s\n' "$*"; }
fail() { printf '  \033[1;31m[✗]\033[0m %s\n' "$*"; ISSUES=$((ISSUES+1)); }
warn() { printf '  \033[1;33m[!]\033[0m %s\n' "$*"; }

PORT="${PORT:-8319}"
AUTH_FILE="${ROUTER_AUTH_FILE:-$REPO/auth.json}"
VENV_PYTHON="$REPO/venv/bin/python"
ISSUES=0

echo ""
echo "  hermes-router doctor"
echo "  ──────────────────────────────────────────"

# Python
if [ -f "$VENV_PYTHON" ]; then
  ver=$("$VENV_PYTHON" --version 2>&1 | awk '{print $2}')
  pass "Python $ver (venv)"
elif command -v python3 >/dev/null 2>&1; then
  ver=$(python3 --version 2>&1 | awk '{print $2}')
  warn "System python3 $ver found but no venv — run ./install.sh"
  ISSUES=$((ISSUES+1))
else
  fail "Python 3.10+ not found — install it first"
fi

# venv
if [ -f "$VENV_PYTHON" ]; then
  pass "venv at $REPO/venv"
else
  fail "venv missing — run ./install.sh"
fi

# Dependencies
if [ -f "$VENV_PYTHON" ] && "$VENV_PYTHON" -c "import flask, waitress, requests" 2>/dev/null; then
  pass "Dependencies installed (flask, waitress, requests)"
else
  fail "Dependencies missing — run ./install.sh"
fi

# auth.json + keys
PYTHON="${VENV_PYTHON:-python3}"
if command -v "$PYTHON" >/dev/null 2>&1 && [ -f "$AUTH_FILE" ]; then
  read -r total_keys provider_count <<< "$("$PYTHON" - "$AUTH_FILE" <<'PY'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
    providers = doc.get("providers", {})
    total = sum(len(v) for v in providers.values())
    active = len([p for p, keys in providers.items() if keys])
    print(total, active)
except Exception:
    print(0, 0)
PY
)"
  if [ "${total_keys:-0}" -gt 0 ]; then
    pass "auth.json: $total_keys key(s) across $provider_count provider(s)"
  else
    fail "auth.json exists but has no keys — run: hr auth add <provider>"
  fi
elif [ ! -f "$AUTH_FILE" ]; then
  fail "auth.json not found at $AUTH_FILE — run: hr auth add <provider>"
fi

# `hr` on PATH
if command -v hr >/dev/null 2>&1; then
  pass "hr on PATH ($(command -v hr))"
else
  warn "hr not on PATH — run ./install.sh (or open a new terminal)"
  ISSUES=$((ISSUES+1))
fi

# Router running
if curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; then
  pass "Router running on port $PORT"
else
  warn "Router not running on port $PORT — start with: hr start"
fi

echo "  ──────────────────────────────────────────"
if [ "$ISSUES" -eq 0 ]; then
  printf '  \033[1;32mAll checks passed.\033[0m\n'
else
  printf '  \033[1;33m%d issue(s) found — see above.\033[0m\n' "$ISSUES"
fi
echo ""
