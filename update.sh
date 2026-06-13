#!/usr/bin/env bash
#
# hermes-router self-updater
# ---------------------------
# Safely pulls the latest version from GitHub and restarts your router.
#
# Safety first — this script is built so an update can never leave you with a
# broken router:
#   1. It NEVER touches your .env or router_state.json (your keys + runtime
#      state are untracked, so a pull leaves them alone).
#   2. It validates the new code BEFORE restarting anything.
#   3. If validation, install, or the post-restart health check fails, it
#      automatically rolls back to the exact version you were on and restarts
#      that — so you're never left worse off than before you ran it.
#
# Usage:
#   ./update.sh            # check, then update + restart if there's a new version
#   ./update.sh --check    # only tell me if an update is available (no changes)
#
# Optional environment overrides:
#   PYTHON=python3.12              # which interpreter to validate/install with
#   PORT=8319                      # port to health-check after restart
#   HERMES_ROUTER_SERVICE=my-svc   # systemd unit name (default: hermes-router)
#
set -uo pipefail

cd "$(dirname "$0")" || { echo "cannot cd to script dir"; exit 1; }

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8319}"
SERVICE="${HERMES_ROUTER_SERVICE:-hermes-router}"
CHECK_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --check)   CHECK_ONLY=1 ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^#[[:space:]]?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

# How this updater was invoked, for use in messages. Set by the `hermes-router`
# wrapper to "hermes-router update"; otherwise we're being run directly.
SELF="${HR_INVOKE:-./update.sh}"

log()  { printf '\033[1;36m[update]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[update]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[update]\033[0m %s\n' "$*"; }

# ── Preconditions ─────────────────────────────────────────────────────────────
command -v git >/dev/null 2>&1 || { err "git is not installed."; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  err "this folder isn't a git clone — the updater only works on a 'git clone' of"
  err "the repo. (If you downloaded a zip, re-clone with: git clone <repo-url>)"
  exit 1
}

BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# rollback() restores the exact commit we started on and restarts it.
# Relies on $START_COMMIT, set before any call below.
rollback() {
  err "rolling back to ${START_COMMIT:0:9}…"
  git reset --hard "$START_COMMIT" >/dev/null 2>&1
  restart_service >/dev/null 2>&1 || true
  err "rolled back. Your previous working version is restored."
  exit 1
}

# restart_service() returns 0 if it restarted a systemd unit, 2 if none exists.
restart_service() {
  if command -v systemctl >/dev/null 2>&1 \
     && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}\.service"; then
    log "restarting systemd service '${SERVICE}'…"
    if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
      sudo systemctl restart "$SERVICE"
    else
      systemctl restart "$SERVICE"
    fi
    return $?
  fi
  return 2
}

# health_ok() polls /health for up to ~15s. Returns 0 if healthy, 1 if not,
# 2 if we can't check (no curl).
health_ok() {
  command -v curl >/dev/null 2>&1 || return 2
  for _ in $(seq 1 15); do
    curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

# ── Check for updates ──────────────────────────────────────────────────────────
log "checking for updates on branch '${BRANCH}'…"
if ! git fetch --quiet origin "$BRANCH"; then
  err "couldn't reach GitHub (are you online?)."
  exit 1
fi

START_COMMIT="$(git rev-parse HEAD)"
REMOTE_COMMIT="$(git rev-parse "origin/${BRANCH}")"

if [ "$START_COMMIT" = "$REMOTE_COMMIT" ]; then
  ok "already up to date (${START_COMMIT:0:9}). Nothing to do."
  exit 0
fi

log "update available:  ${START_COMMIT:0:9} → ${REMOTE_COMMIT:0:9}"
echo "        ── what's new ──"
git --no-pager log --oneline "HEAD..origin/${BRANCH}" | sed 's/^/        /'

if [ "$CHECK_ONLY" = "1" ]; then
  log "run ${SELF} (without --check) to apply it."
  exit 0
fi

# ── Guard against losing local edits ────────────────────────────────────────────
# .env and router_state.json are gitignored, so they're never at risk. This only
# catches edits to TRACKED files (e.g. you hand-tweaked router.py).
if ! git diff --quiet || ! git diff --cached --quiet; then
  err "you have local changes to tracked files (e.g. router.py)."
  err "stash them first, then re-run:   git stash && ${SELF} && git stash pop"
  exit 1
fi

# ── Apply ────────────────────────────────────────────────────────────────────
# Nothing below modifies the working tree until this fast-forward succeeds, so a
# failure here leaves you exactly where you started — no rollback needed.
log "pulling latest…"
merge_out="$(git merge --ff-only "origin/${BRANCH}" 2>&1)"; merge_rc=$?
if [ "$merge_rc" -ne 0 ]; then
  if printf '%s' "$merge_out" | grep -q "untracked working tree files"; then
    err "the update adds files that you already have locally (untracked), so it"
    err "won't overwrite them. Move or delete these, then re-run ${SELF}:"
    printf '%s\n' "$merge_out" | grep -E '^[[:space:]]+[^[:space:]]' | sed 's/^[[:space:]]*/        /'
  else
    err "can't fast-forward (your history has diverged from origin)."
    err "resolve manually, e.g.:   git pull --rebase origin ${BRANCH}"
  fi
  exit 1
fi

# Reinstall deps only if requirements actually changed.
if git diff --name-only "$START_COMMIT" HEAD | grep -q '^requirements\.txt$'; then
  log "requirements.txt changed — updating dependencies…"
  if ! $PYTHON -m pip install -q -r requirements.txt; then
    err "dependency install failed."
    rollback
  fi
fi

# ── Validate the new code BEFORE we touch the running service ───────────────────
log "validating new code…"
if ! $PYTHON -c "import ast,sys; ast.parse(open('router.py').read())" 2>/dev/null; then
  err "new router.py has a syntax error."
  rollback
fi
if ! $PYTHON -m py_compile router.py 2>/dev/null; then
  err "new router.py failed to compile."
  rollback
fi
ok "new code looks good (${REMOTE_COMMIT:0:9})."

# ── Restart + health-check (with auto-rollback) ─────────────────────────────────
restart_service
rc=$?
if [ "$rc" -eq 0 ]; then
  log "health-checking on :${PORT}…"
  health_ok
  hc=$?
  if [ "$hc" -eq 0 ]; then
    ok "✅ updated to ${REMOTE_COMMIT:0:9} and the router is healthy."
  elif [ "$hc" -eq 2 ]; then
    ok "✅ updated to ${REMOTE_COMMIT:0:9} and restarted (install 'curl' to enable health checks)."
  else
    err "the router didn't come back healthy after restart."
    rollback
  fi
else
  ok "✅ code updated to ${REMOTE_COMMIT:0:9}."
  log "no '${SERVICE}' systemd service found — restart your router however you run it"
  log "(e.g. stop the old process and run:  ${PYTHON} router.py)."
fi
