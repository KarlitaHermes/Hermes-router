#!/usr/bin/env bash
#
# hr auth — manage API keys for hermes-router providers
#
# Usage:
#   hr auth add <provider>   Add one or more API keys for a provider
#   hr auth list             Show all providers and how many keys are configured
#   hr auth help             Show this help
#
# Supported providers:
#   gemini  openrouter  cerebras  sambanova  github_models
#   mistral  groq  cohere  naga  nvidia
#
# Keys are stored in .env next to this script (or override with HR_ENV_FILE).
# The router loads them as a credential pool — multiple keys per provider
# are round-robined and individually cooled down on rate-limits.
#
# Key numbering matches the router's loader:
#   GROQ_API_KEY      ← first key
#   GROQ_API_KEY_2    ← second
#   GROQ_API_KEY_3    ← third   ... and so on
#
set -uo pipefail

cd "$(dirname "$0")" || { echo "cannot cd to script dir"; exit 1; }
REPO="$(pwd)"
ENV_FILE="${HR_ENV_FILE:-$REPO/.env}"

log()  { printf '\033[1;36m[auth]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[auth]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[auth]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[auth]\033[0m %s\n' "$*"; }

PROVIDERS_LIST="gemini openrouter cerebras sambanova github_models mistral groq cohere naga nvidia"

# Map provider name → env var base (matches the live router's env_var field)
env_var_for() {
  case "${1,,}" in
    gemini)                echo "GOOGLE_API_KEY" ;;
    openrouter)            echo "OPENROUTER_API_KEY" ;;
    cerebras)              echo "CEREBRAS_API_KEY" ;;
    sambanova)             echo "SAMBANOVA_API_KEY" ;;
    github_models|github)  echo "GITHUB_MODELS_TOKEN" ;;
    mistral)               echo "MISTRAL_API_KEY" ;;
    groq)                  echo "GROQ_API_KEY" ;;
    cohere)                echo "COHERE_API_KEY" ;;
    naga)                  echo "NAGA_API_KEY" ;;
    nvidia)                echo "NVIDIA_API_KEY" ;;
    *)                     echo "" ;;
  esac
}

# Count how many keys are already stored for a given env var base.
# Counts: BASE=, BASE_2=, BASE_3=, ... (stops at first gap, same as router loader).
count_keys() {
  local base="$1"
  local count=0
  [ -f "$ENV_FILE" ] || { echo 0; return; }
  grep -qE "^${base}=" "$ENV_FILE" 2>/dev/null && count=$((count + 1))
  local i=2
  while grep -qE "^${base}_${i}=" "$ENV_FILE" 2>/dev/null; do
    count=$((count + 1))
    i=$((i + 1))
  done
  echo "$count"
}

# Append one key to .env and echo back the variable name used.
append_key() {
  local base="$1"
  local key="$2"
  local existing
  existing=$(count_keys "$base")
  touch "$ENV_FILE"
  if [ "$existing" -eq 0 ]; then
    # Add a blank line before the first key for readability if .env is non-empty
    [ -s "$ENV_FILE" ] && echo "" >> "$ENV_FILE"
    printf '%s=%s\n' "$base" "$key" >> "$ENV_FILE"
    echo "$base"
  else
    local slot=$((existing + 1))
    printf '%s_%d=%s\n' "$base" "$slot" "$key" >> "$ENV_FILE"
    echo "${base}_${slot}"
  fi
}

# ── hr auth add <provider> ────────────────────────────────────────────────────

cmd_add() {
  local provider="${1:-}"
  if [ -z "$provider" ]; then
    err "Usage: hr auth add <provider>"
    err "Providers: $PROVIDERS_LIST"
    exit 1
  fi

  local base
  base=$(env_var_for "$provider")
  if [ -z "$base" ]; then
    err "Unknown provider: '$provider'"
    err "Supported: $PROVIDERS_LIST"
    exit 1
  fi

  local existing
  existing=$(count_keys "$base")
  if [ "$existing" -gt 0 ]; then
    log "$provider already has $existing key(s). New keys will be added to the pool."
  else
    log "No keys found for $provider yet. Adding the first one."
  fi
  log "Keys will be saved to: $ENV_FILE"
  echo ""

  while true; do
    local key=""
    printf '\033[1;36m[auth]\033[0m Enter API key (input hidden): '
    read -rs key
    echo ""

    if [ -z "$key" ]; then
      warn "Empty key — skipped."
    else
      local var_name
      var_name=$(append_key "$base" "$key")
      ok "Saved as ${var_name}  (ends in: ...${key: -8})"
    fi

    echo ""
    printf '\033[1;36m[auth]\033[0m Add another key for $provider? [y/N]: '
    read -r again
    echo ""
    case "$again" in
      [yY]|[yY][eE][sS]) continue ;;
      *) break ;;
    esac
  done

  local total
  total=$(count_keys "$base")
  ok "$provider now has $total key(s) in the credential pool."
  log "Apply the change with:  hr restart"
}

# ── hr auth list ─────────────────────────────────────────────────────────────

cmd_list() {
  if [ ! -f "$ENV_FILE" ]; then
    warn "No .env file found at: $ENV_FILE"
    warn "Run 'hr auth add <provider>' to create one."
    exit 0
  fi

  echo ""
  printf '  %-16s  %-6s  %s\n' "Provider" "Keys" "Env var"
  printf '  %-16s  %-6s  %s\n' "────────────────" "──────" "───────────────────────"

  local total_keys=0
  for provider in $PROVIDERS_LIST; do
    local base
    base=$(env_var_for "$provider")
    local count
    count=$(count_keys "$base")
    total_keys=$((total_keys + count))
    if [ "$count" -eq 0 ]; then
      printf '  %-16s  \033[1;31m%-6s\033[0m  %s\n' "$provider" "none" "$base"
    else
      printf '  %-16s  \033[1;32m%-6s\033[0m  %s\n' "$provider" "$count key(s)" "$base"
    fi
  done

  echo ""
  log "$total_keys total key(s) across all providers — stored in: $ENV_FILE"
}

# ── Dispatch ─────────────────────────────────────────────────────────────────

subcmd="${1:-help}"
shift 2>/dev/null || true

case "$subcmd" in
  add)             cmd_add "$@" ;;
  list)            cmd_list ;;
  help|-h|--help)  awk 'NR>1 && /^#/ {sub(/^#[[:space:]]?/,""); print; next} NR>1 {exit}' "$0" ;;
  *)
    err "unknown auth subcommand: '$subcmd'"
    err "Usage: hr auth add <provider>  |  hr auth list"
    exit 1
    ;;
esac
