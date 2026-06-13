#!/usr/bin/env bash
#
# Installs the `hermes-router` command so you can run `hermes-router update`
# (and `hermes-router start`) from anywhere — instead of ./update.sh.
#
# It just symlinks the launcher in this repo onto your PATH; nothing is copied
# or hidden, and `git pull` / `hermes-router update` keep it current.
#
set -uo pipefail

cd "$(dirname "$0")" || { echo "cannot cd to script dir"; exit 1; }
REPO="$(pwd)"

log() { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; }
ok()  { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }

chmod +x "$REPO/hermes-router" "$REPO/update.sh" 2>/dev/null || true

# Prefer a user-local bin already on PATH; fall back to ~/.local/bin.
BINDIR=""
for d in "$HOME/.local/bin" "/usr/local/bin"; do
  case ":$PATH:" in *":$d:"*) BINDIR="$d"; break ;; esac
done
[ -n "$BINDIR" ] || BINDIR="$HOME/.local/bin"

mkdir -p "$BINDIR" 2>/dev/null || true
LINK="$BINDIR/hermes-router"

if ln -sf "$REPO/hermes-router" "$LINK" 2>/dev/null; then
  :
elif command -v sudo >/dev/null 2>&1; then
  log "need elevated permission to write to $BINDIR…"
  sudo ln -sf "$REPO/hermes-router" "$LINK" || { err "failed to create symlink in $BINDIR"; exit 1; }
else
  err "couldn't write to $BINDIR (no sudo available). Pick a writable dir, e.g.:"
  err "  mkdir -p ~/.local/bin && ln -sf \"$REPO/hermes-router\" ~/.local/bin/hermes-router"
  exit 1
fi

ok "installed: $LINK -> $REPO/hermes-router"

# Is the chosen dir actually on PATH right now?
case ":$PATH:" in
  *":$BINDIR:"*)
    ok "try it:  hermes-router update --check"
    ;;
  *)
    err "$BINDIR is not on your PATH yet. Add this line to your shell config"
    err "(~/.bashrc or ~/.zshrc), then open a new terminal:"
    echo "      export PATH=\"$BINDIR:\$PATH\""
    ;;
esac
