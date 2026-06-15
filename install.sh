#!/usr/bin/env bash
#
# hermes-router installer — one command sets everything up:
#   creates a venv, installs dependencies, and puts `hr` on your PATH.
#
# Usage:
#   ./install.sh
#
# One-liner (from scratch):
#   git clone https://github.com/Shaf2665/Hermes-router.git && cd Hermes-router && ./install.sh
#
set -uo pipefail

cd "$(dirname "$0")" || { echo "cannot cd to script dir"; exit 1; }
REPO="$(pwd)"

log() { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; }
ok()  { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }

echo ""
echo "  ┌──────────────────────────────────┐"
echo "  │   hermes-router  ·  installer    │"
echo "  └──────────────────────────────────┘"
echo ""

# ── 1. Python 3.10+ ──────────────────────────────────────────────────────────
PYTHON=""
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    _ver=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
    _maj="${_ver%%.*}"
    _min="${_ver#*.}"
    if [ "$_maj" -ge 3 ] && [ "$_min" -ge 10 ]; then
      PYTHON="$py"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  err "Python 3.10+ is required but not found on PATH."
  err "  Ubuntu/Debian:  sudo apt install python3"
  err "  macOS:          brew install python"
  exit 1
fi

ok "Python $("$PYTHON" --version 2>&1 | awk '{print $2}') found"

# ── 2. Create virtual environment ─────────────────────────────────────────────
if [ -f "$REPO/venv/bin/python" ]; then
  ok "venv already exists — skipping creation"
else
  log "Creating virtual environment..."
  if command -v uv >/dev/null 2>&1; then
    uv venv "$REPO/venv" --python "$PYTHON" --quiet
    ok "venv created (via uv)"
  else
    "$PYTHON" -m venv "$REPO/venv"
    ok "venv created"
  fi
fi

VENV_PYTHON="$REPO/venv/bin/python"

# ── 3. Install dependencies ───────────────────────────────────────────────────
if "$VENV_PYTHON" -c "import flask, waitress, requests" 2>/dev/null; then
  ok "Dependencies already installed"
else
  log "Installing dependencies..."
  # Look for uv in PATH and common install locations
  UV="$(command -v uv 2>/dev/null || true)"
  for _p in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "/usr/local/bin/uv"; do
    [ -z "$UV" ] && [ -x "$_p" ] && UV="$_p"
  done

  if [ -n "$UV" ]; then
    "$UV" pip install --python "$VENV_PYTHON" -r "$REPO/requirements.txt" --quiet
  elif [ -f "$REPO/venv/bin/pip" ]; then
    "$REPO/venv/bin/pip" install -q -r "$REPO/requirements.txt"
  else
    "$VENV_PYTHON" -m pip install -q -r "$REPO/requirements.txt" 2>/dev/null || {
      err "Cannot install dependencies: no uv or pip found in the venv."
      err "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
      exit 1
    }
  fi

  if ! "$VENV_PYTHON" -c "import flask, waitress, requests" 2>/dev/null; then
    err "Dependency installation failed."
    err "Try manually: uv pip install -r requirements.txt"
    exit 1
  fi
  ok "Dependencies installed (flask, waitress, requests)"
fi

# ── 4. Make scripts executable ────────────────────────────────────────────────
chmod +x "$REPO/hermes-router" "$REPO/install.sh" "$REPO/update.sh" \
         "$REPO/auth.sh" "$REPO/status.sh" "$REPO/restart.sh" \
         "$REPO/setup.sh" "$REPO/doctor.sh" 2>/dev/null || true

# ── 5. Symlink `hr` and `hermes-router` on PATH ───────────────────────────────
BINDIR=""
for d in "$HOME/.local/bin" "/usr/local/bin"; do
  case ":$PATH:" in *":$d:"*) BINDIR="$d"; break ;; esac
done
[ -n "$BINDIR" ] || BINDIR="$HOME/.local/bin"
mkdir -p "$BINDIR"

_symlink() {
  local name="$1"
  local link="$BINDIR/$name"
  if ln -sf "$REPO/hermes-router" "$link" 2>/dev/null; then
    ok "symlinked: $link"
  elif command -v sudo >/dev/null 2>&1; then
    log "need elevated permission for $BINDIR..."
    sudo ln -sf "$REPO/hermes-router" "$link" && ok "symlinked: $link" || { err "failed to symlink $name"; exit 1; }
  else
    err "can't write to $BINDIR — run manually:"
    err "  ln -sf \"$REPO/hermes-router\" ~/.local/bin/$name"
    exit 1
  fi
}

_symlink hermes-router
_symlink hr

# ── 6. PATH auto-fix ─────────────────────────────────────────────────────────
case ":$PATH:" in
  *":$BINDIR:"*)
    ;;
  *)
    SHELL_RC=""
    case "${SHELL:-}" in
      */zsh)  SHELL_RC="$HOME/.zshrc" ;;
      */bash) SHELL_RC="$HOME/.bashrc" ;;
    esac

    EXPORT_LINE="export PATH=\"$BINDIR:\$PATH\""

    if [ -n "$SHELL_RC" ] && ! grep -qF "$BINDIR" "$SHELL_RC" 2>/dev/null; then
      printf '\n# hermes-router\n%s\n' "$EXPORT_LINE" >> "$SHELL_RC"
      log "Added $BINDIR to PATH in $SHELL_RC"
      log "Run: source $SHELL_RC  (or open a new terminal)"
    elif [ -z "$SHELL_RC" ]; then
      log "Add this to your shell config (~/.bashrc or ~/.zshrc):"
      echo "    $EXPORT_LINE"
    fi
    ;;
esac

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
ok "Installation complete!"
echo ""
echo "  Next steps:"
echo "    hr setup                 ← interactive setup wizard (recommended)"
echo "    hr auth add openrouter   ← or add a key directly"
echo ""
