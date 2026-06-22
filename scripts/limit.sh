#!/usr/bin/env bash
#
# hr limit — per-proxy-key rate limits & daily budgets ("virtual keys" lite)
#
# Each value in PROXY_API_KEYS can carry:
#   rpm             requests per minute (rolling 60s window)
#   req_per_day     requests per UTC day
#   tokens_per_day  tokens per UTC day
# 0 / unset = unlimited. Limits are stored in auth.json under "proxy_keys" and
# read by the router on start — run `hr restart` after changing them.
#
# Usage:
#   hr limit list
#   hr limit set <key> [--rpm N] [--req-day N] [--tokens-day N]
#   hr limit clear <key>
#
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo dir"; exit 1; }
AUTH_FILE="${ROUTER_AUTH_FILE:-$REPO/auth.json}"
PYTHON="${PYTHON:-python3}"

log()  { printf '\033[1;36m[limit]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[limit]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[limit]\033[0m %s\n' "$*"; }

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
}

cmd="${1:-list}"
shift 2>/dev/null || true

case "$cmd" in
  list)
    AUTH_FILE="$AUTH_FILE" "$PYTHON" - <<'PY'
import json, os
f = os.environ["AUTH_FILE"]
try:
    doc = json.load(open(f))
except Exception:
    doc = {}
pk = doc.get("proxy_keys", {})
if not pk:
    print("No per-key limits set. Add one with:  hr limit set <key> --rpm 60")
else:
    for k, v in pk.items():
        tail = k[-6:] if len(k) > 6 else k
        rpm = v.get("rpm", 0) or "∞"
        rq  = v.get("req_per_day", 0) or "∞"
        tk  = v.get("tokens_per_day", 0) or "∞"
        print(f"  …{tail}:  rpm={rpm}  req/day={rq}  tokens/day={tk}")
print("\nGlobal env defaults (apply when a key has no explicit value):")
print(f"  PROXY_LIMIT_RPM={os.environ.get('PROXY_LIMIT_RPM','0')}  "
      f"PROXY_LIMIT_REQ_DAY={os.environ.get('PROXY_LIMIT_REQ_DAY','0')}  "
      f"PROXY_LIMIT_TOKENS_DAY={os.environ.get('PROXY_LIMIT_TOKENS_DAY','0')}")
PY
    ;;

  set)
    key="${1:-}"; shift 2>/dev/null || true
    [ -n "$key" ] || { err "usage: hr limit set <key> [--rpm N] [--req-day N] [--tokens-day N]"; exit 1; }
    rpm=""; reqday=""; tokday=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --rpm)        rpm="${2:-}"; shift 2 ;;
        --req-day)    reqday="${2:-}"; shift 2 ;;
        --tokens-day) tokday="${2:-}"; shift 2 ;;
        *) err "unknown option: $1"; exit 1 ;;
      esac
    done
    AUTH_FILE="$AUTH_FILE" KEY="$key" RPM="$rpm" REQDAY="$reqday" TOKDAY="$tokday" "$PYTHON" - <<'PY'
import json, os
f = os.environ["AUTH_FILE"]
try:
    doc = json.load(open(f))
except Exception:
    doc = {}
pk = doc.setdefault("proxy_keys", {})
spec = pk.get(os.environ["KEY"], {})
for env, field in (("RPM", "rpm"), ("REQDAY", "req_per_day"), ("TOKDAY", "tokens_per_day")):
    val = os.environ.get(env, "")
    if val != "":
        spec[field] = int(val)
pk[os.environ["KEY"]] = spec
json.dump(doc, open(f, "w"), indent=2)
print("stored:", spec)
PY
    ok "Saved. Run 'hr restart' to apply."
    ;;

  clear)
    key="${1:-}"
    [ -n "$key" ] || { err "usage: hr limit clear <key>"; exit 1; }
    AUTH_FILE="$AUTH_FILE" KEY="$key" "$PYTHON" - <<'PY'
import json, os
f = os.environ["AUTH_FILE"]
try:
    doc = json.load(open(f))
except Exception:
    doc = {}
pk = doc.get("proxy_keys", {})
if pk.pop(os.environ["KEY"], None) is not None:
    json.dump(doc, open(f, "w"), indent=2)
    print("cleared")
else:
    print("no limits were set for that key")
PY
    ok "Run 'hr restart' to apply."
    ;;

  help|--help|-h) usage ;;
  *) err "unknown subcommand: ${cmd}"; usage >&2; exit 1 ;;
esac
