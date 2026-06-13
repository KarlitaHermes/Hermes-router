#!/usr/bin/env bash
#
# Installs the `hermes-router` command (and the `hr` shorthand) so you can
# run `hr update`, `hr start`, etc. from anywhere — instead of ./update.sh.
#
# It just symlinks the launcher in this repo onto your PATH; nothing is copied
# or hidden, and `git pull` / `hr update` keep it current.
#
set -uo pipefail

cd "$(dirname "$0")" || { echo "cannot cd to script dir"; exit 1; }
REPO="$(pwd)"

log() { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; }
ok()  { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }

chmod +x "$REPO/hermes-router" "$REPO/update.sh" "$REPO/auth.sh" 2>/dev/null || true

# Prefer a user-local bin already on PATH; fall back to ~/.local/bin.
BINDIR=""
for d in "$HOME/.local/bin" "/usr/local/bin"; do
  case ":$PATH:" in *":$d:"*) BINDIR="$d"; break ;; esac
done
[ -n "$BINDIR" ] || BINDIR="$HOME/.local/bin"

mkdir -p "$BINDIR" 2>/dev/null || true

_symlink() {
  local name="$1"
  local link="$BINDIR/$name"
  if ln -sf "$REPO/hermes-router" "$link" 2>/dev/null; then
    ok "installed: $link -> $REPO/hermes-router"
  elif command -v sudo >/dev/null 2>&1; then
    log "need elevated permission to write to $BINDIR…"
    sudo ln -sf "$REPO/hermes-router" "$link" || { err "failed to create symlink $link"; exit 1; }
    ok "installed: $link -> $REPO/hermes-router"
  else
    err "couldn't write to $BINDIR (no sudo available). Pick a writable dir, e.g.:"
    err "  mkdir -p ~/.local/bin && ln -sf \"$REPO/hermes-router\" ~/.local/bin/$name"
    exit 1
  fi
}

_symlink hermes-router
_symlink hr

# Is the chosen dir actually on PATH right now?
case ":$PATH:" in
  *":$BINDIR:"*)
    ok "try it:  hr update --check"
    ;;
  *)
    err "$BINDIR is not on your PATH yet. Add this line to your shell config"
    err "(~/.bashrc or ~/.zshrc), then open a new terminal:"
    echo "      export PATH=\"$BINDIR:\$PATH\""
    ;;
esac
