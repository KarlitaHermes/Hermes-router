#!/usr/bin/env python3
"""
hermes-router — Free-tier AI load balancer with automatic key rotation.

A lightweight OpenAI-compatible proxy that:
  - Rotates across multiple API keys per provider automatically
  - Cascades to the next provider when one is exhausted or rate-limited
  - Strips thinking/reasoning fields that break non-Claude providers
  - Handles 413 (payload too large) by cascading instead of crashing
  - Caches identical responses to preserve free-tier quota
  - Routes short requests to low-latency providers first (optional)
  - Tracks per-provider latency and error rates

Supported providers (configure via .env):
  Gemini → OpenRouter → SambaNova → GitHub Models → Cerebras → Groq → Mistral → Cohere → Z.ai (GLM) → Naga → NVIDIA NIM

Quick start:
  pip install -r requirements.txt
  cp .env.example .env   # add your API keys
  python router.py
"""

import json, os, time, threading, logging, hashlib, hmac, itertools
from pathlib import Path
from collections import deque, OrderedDict
from flask import Flask, request, jsonify, Response, stream_with_context
import requests

# ── Config ─────────────────────────────────────────────────────────────────────

def _load_env(path: str = ".env"):
    """Load key=value pairs from a .env file into os.environ (no-op if missing)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_load_env()

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hermes-router")

# Shared HTTP session — reuses TCP/TLS connections to each provider host across
# requests (HTTP keep-alive), so we don't pay a fresh ~100–300ms handshake on
# every call. Thread-safe for sending; pool_maxsize covers our worker threads.
# max_retries=0 because the cascade handles retries, not urllib3.
_HTTP = requests.Session()
_http_adapter = requests.adapters.HTTPAdapter(
    pool_connections=20,
    pool_maxsize=max(32, int(os.environ.get("WORKER_THREADS", 16)) * 2),
    max_retries=0,
)
_HTTP.mount("https://", _http_adapter)
_HTTP.mount("http://", _http_adapter)

PORT              = int(os.environ.get("PORT", 8319))
PROXY_API_KEYS    = [k.strip() for k in os.environ.get("PROXY_API_KEYS", "sk-router-1").split(",") if k.strip()]
ROUTER_MODEL      = os.environ.get("ROUTER_MODEL_ID", "hermes-router")
CACHE_TTL         = int(os.environ.get("CACHE_TTL_SECONDS", 300))   # 0 = disabled
CACHE_MAX_SIZE    = int(os.environ.get("CACHE_MAX_SIZE", 100))
FAST_ROUTE_TOKENS = int(os.environ.get("FAST_ROUTE_THRESHOLD", 0))  # 0 = disabled
STATE_FILE        = Path(os.environ.get("ROUTER_STATE_FILE", "./router_state.json"))
STATE_TTL_HOURS   = int(os.environ.get("ROUTER_STATE_TTL_HOURS", 24))  # 0 = re-probe every start
AUTH_FILE         = Path(os.environ.get("ROUTER_AUTH_FILE", "./auth.json"))  # router's own key store


def _load_auth_json() -> dict[str, list[str]]:
    """Load provider API keys from auth.json — the router's own credential store,
    managed by `hr auth add`. This makes the router self-contained: keys live with
    the router, independent of any host application.

      Format: {"providers": {"openrouter": ["key1", "key2"], "gemini": ["key"]}}

    Returns {provider_name: [keys]}. A missing or invalid file is non-fatal —
    the router simply falls back to keys from .env (see _keys_for)."""
    if not AUTH_FILE.exists():
        return {}
    try:
        doc = json.loads(AUTH_FILE.read_text())
        out: dict[str, list[str]] = {}
        for name, keys in doc.get("providers", {}).items():
            if isinstance(keys, list):
                out[name] = [str(k).strip() for k in keys if str(k).strip()]
        return out
    except Exception as e:
        log.warning(f"Could not read {AUTH_FILE}: {e}")
        return {}

_AUTH_KEYS = _load_auth_json()

# Circuit-breaker knobs — a provider that fails health repeatedly is tripped out
# of rotation for a cooldown, then probed again (half-open). Overridable via env.
BREAKER_WINDOW      = int(os.environ.get("BREAKER_WINDOW", 8))          # recent outcomes to weigh
BREAKER_MIN_SAMPLES = int(os.environ.get("BREAKER_MIN_SAMPLES", 4))     # min samples before it can trip
BREAKER_ERROR_RATE  = float(os.environ.get("BREAKER_ERROR_RATE", 0.5))  # trip at >= this health-fail fraction
BREAKER_COOLDOWN    = int(os.environ.get("BREAKER_COOLDOWN", 60))       # seconds the breaker stays open

# Providers known for low-latency inference — promoted for short requests
_FAST_PROVIDERS = {"groq", "cerebras", "sambanova", "mistral"}

# Per-request counter for round-robin among equally-rated providers.
# itertools.count().__next__ is atomic in CPython, so it's thread-safe.
_rr_counter = itertools.count()

# ── Smart routing: capability ratings ─────────────────────────────────────────
# 1=outstanding  2=best  3=good  4=fair  5=basic  (lower = more capable)
# Recommended base model: set ROUTER_BASE_MODEL_PROVIDER + ROUTER_BASE_MODEL
# e.g. ROUTER_BASE_MODEL_PROVIDER=openai  ROUTER_BASE_MODEL=gpt-4o-mini
KNOWN_MODEL_RATINGS: dict = {
    # 1 — Outstanding
    "gpt-5.3-codex": 1, "gpt-5-codex": 1, "gpt-4o": 1, "o1": 1, "o3": 1,
    "claude-opus-4": 1, "claude-opus": 1, "gemini-2.5-pro": 1,
    "nemotron-3-ultra": 1,
    "gpt-4.5": 1, "claude-3-7": 1, "gemini-2.0-ultra": 1,
    "deepseek-r2": 1, "qwen3-235b": 1, "qwen3-72b": 1,
    # 2 — Best
    "gemini-2.5-flash": 2, "gemini-2.0-flash": 2,
    "llama-3.3-70b": 2, "llama-3.1-70b": 2,
    "mistral-large": 2, "mistral-medium": 2,
    "command-r-plus": 2, "command-a": 2, "nvidia/nemotron-3-super": 2, "nemotron": 2,
    "deepseek-v4-flash": 2, "deepseek-v4": 2,  # capable but slow cold-start → "best", not first-choice
    "deepseek-v3": 2, "deepseek-v2": 2,
    "claude-sonnet": 2, "claude-3-5": 2, "grok-2": 2,
    "qwen2.5-72b": 2, "qwen-72b": 2, "qwen3-32b": 2,
    "phi-4": 2, "phi-4-reasoning": 2,
    "mixtral-8x22b": 2, "wizardlm-2-8x22b": 2,
    "yi-large": 2, "moonshot-v1": 2,
    "llama-4-maverick": 2, "llama-4-scout": 2,
    # 3 — Good
    "gemini-2.5-flash-lite": 3, "gemini-1.5-flash": 3,
    "gpt-4o-mini": 3, "gpt-oss-120b": 3,
    "mistral-small": 3, "glm-4.5-flash": 3, "glm-4.7-flash": 3,
    "llama-3.1-8b-instant": 3,
    "qwen2.5-32b": 3, "qwen3-14b": 3, "qwen3-8b": 3,
    "phi-3.5": 3, "phi-3-medium": 3,
    "mixtral-8x7b": 3, "wizardlm-2-7b": 3,
    "yi-medium": 3, "yi-6b": 3,
    # 4 — Fair
    "command-r7b": 4, "command-r7b-12-2024": 4,
    "llama-3.2-3b": 4, "mistral-7b": 4,
    "qwen2.5-7b": 4, "qwen3-4b": 4, "phi-3-mini": 4,
    "phi-3.5-mini": 4, "yi-mini": 4,
}
_RATING_PATTERNS: list = [
    (1, ["pro-exp", "ultra", "opus", "o3", "o1-pro", "405b", "671b", "r1-zero"]),
    (2, ["70b", "large", "plus", "pro", "turbo", "super", "sonnet", "72b", "32b", "maverick", "scout", "phi-4", "wizardlm"]),
    (3, ["flash", "small", "mini", "medium", "120b", "8b-instant", "glm-4", "14b", "22b", "mixtral", "qwen", "yi-m", "phi-3"]),
    (4, ["7b", "8b", "lite", "fast", "r7b", "nano", "3b", "phi-3-mini", "phi-3.5-mini", "yi-mini", "4b"]),
    (5, ["micro", "tiny", "1b"]),
]
_COMPLEXITY_LABELS = {1: "critical", 2: "complex", 3: "standard", 4: "simple", 5: "trivial"}
_provider_state: dict = {}   # populated at startup by _initialize_ratings()


def _keys(env_var: str) -> list[str]:
    """Collect all keys for a provider from three naming conventions (combined + de-duped):
      1. Singular:  MISTRAL_API_KEY=k1
      2. Plural:    MISTRAL_API_KEYS=k1,k2,k3   (comma-separated)
      3. Numbered:  MISTRAL_API_KEY_2=k2, MISTRAL_API_KEY_3=k3, ...
    The plural form is the canonical multi-key env var; singular and numbered are
    convenience aliases that are merged in automatically.
    """
    collected = []
    # singular (drop the trailing S if the caller passed the plural form)
    singular = env_var[:-1] if env_var.endswith("S") else env_var
    if singular != env_var:
        single = os.environ.get(singular, "").strip()
        if single:
            collected.append(single)
    # plural / comma-separated
    for piece in os.environ.get(env_var, "").split(","):
        piece = piece.strip()
        if piece:
            collected.append(piece)
    # numbered suffixes on the singular name (_2, _3, ...)
    i = 2
    while True:
        nv = os.environ.get(f"{singular}_{i}", "").strip()
        if not nv:
            break
        collected.append(nv)
        i += 1
    seen, out = set(), []
    for k in collected:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _keys_for(provider_name: str, env_var: str) -> list[str]:
    """All keys for a provider: auth.json entries first (the primary store that
    `hr auth add` writes to), then any matching .env keys as a fallback. Deduped,
    order preserved. A provider with keys in EITHER source is enabled."""
    merged = list(_AUTH_KEYS.get(provider_name, []))
    merged += _keys(env_var)
    seen, out = set(), []
    for k in merged:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _int_env(env_var: str, default: int = 0) -> int:
    """Parse an integer env var, falling back to default on missing/invalid."""
    try:
        return int(os.environ.get(env_var, default))
    except (TypeError, ValueError):
        return default


def _parse_retry_after(value, default: int = 60) -> int:
    """Parse a Retry-After header value. RFC 9110 allows either delay-seconds
    or an HTTP date; some providers also send fractional seconds. Anything we
    can't read as a number falls back to the default cooldown."""
    try:
        return max(1, int(float(value)))
    except (TypeError, ValueError):
        return default


# ── Provider definitions ───────────────────────────────────────────────────────

def _build_providers() -> list[dict]:
    providers = []

    gemini_keys = _keys_for("gemini", "GEMINI_API_KEYS")
    if gemini_keys:
        providers.append({
            "name":     "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model":    os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            "keys":     gemini_keys,
        })

    openrouter_keys = _keys_for("openrouter", "OPENROUTER_API_KEYS")
    if openrouter_keys:
        providers.append({
            "name":     "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model":    os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"),
            "keys":     openrouter_keys,
            "headers":  {
                "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "https://github.com/Shaf2665/hermes-router"),
                "X-Title":      os.environ.get("OPENROUTER_APP_NAME", "hermes-router"),
            },
        })

    sambanova_keys = _keys_for("sambanova", "SAMBANOVA_API_KEYS")
    if sambanova_keys:
        providers.append({
            "name":     "sambanova",
            "base_url": "https://api.sambanova.ai/v1",
            "model":    os.environ.get("SAMBANOVA_MODEL", "DeepSeek-V3.2"),
            "keys":     sambanova_keys,
        })

    github_keys = _keys_for("github_models", "GITHUB_MODELS_TOKENS")
    if github_keys:
        providers.append({
            "name":     "github_models",
            "base_url": "https://models.inference.ai.azure.com",
            "model":    os.environ.get("GITHUB_MODELS_MODEL", "gpt-4o"),
            "keys":     github_keys,
        })

    cerebras_keys = _keys_for("cerebras", "CEREBRAS_API_KEYS")
    if cerebras_keys:
        providers.append({
            "name":     "cerebras",
            "base_url": "https://api.cerebras.ai/v1",
            "model":    os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b"),
            "keys":     cerebras_keys,
        })

    groq_keys = _keys_for("groq", "GROQ_API_KEYS")
    if groq_keys:
        providers.append({
            "name":     "groq",
            "base_url": "https://api.groq.com/openai/v1",
            "model":    os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "keys":     groq_keys,
        })

    mistral_keys = _keys_for("mistral", "MISTRAL_API_KEYS")
    if mistral_keys:
        providers.append({
            "name":     "mistral",
            "base_url": "https://api.mistral.ai/v1",
            "model":    os.environ.get("MISTRAL_MODEL", "mistral-medium-latest"),
            "keys":     mistral_keys,
        })

    cohere_keys = _keys_for("cohere", "COHERE_API_KEYS")
    if cohere_keys:
        providers.append({
            "name":     "cohere",
            "base_url": "https://api.cohere.ai/compatibility/v1",
            "model":    os.environ.get("COHERE_MODEL", "command-a-03-2025"),
            "keys":     cohere_keys,
        })

    zai_keys = _keys_for("zai", "GLM_API_KEYS")
    if zai_keys:
        providers.append({
            "name":     "zai",
            "base_url": "https://api.z.ai/api/paas/v4",
            "model":    os.environ.get("ZAI_MODEL", "glm-4.5-flash"),
            "keys":     zai_keys,
        })

    naga_keys = _keys_for("naga", "NAGA_API_KEYS")
    if naga_keys:
        providers.append({
            "name":     "naga",
            "base_url": "https://api.naga.ac/v1",
            "model":    os.environ.get("NAGA_MODEL", "nemotron-3-super-120b-a12b:free"),
            "keys":     naga_keys,
        })

    nvidia_keys = _keys_for("nvidia", "NVIDIA_API_KEYS")
    if nvidia_keys:
        providers.append({
            "name":     "nvidia",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "model":    os.environ.get("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-flash"),
            "keys":     nvidia_keys,
        })

    if not providers:
        log.warning("No providers configured — set GEMINI_API_KEYS, OPENROUTER_API_KEYS, etc. in .env")

    # Per-provider "skip when the request is too big" ceiling. Some free tiers
    # reject large payloads outright, so trying them with a big prompt just wastes
    # a round-trip before cascading. When the estimated request size exceeds a
    # provider's ceiling, that provider is skipped entirely.
    #   Configure via  {PROVIDER}_SKIP_TOKENS_OVER  (0 = never skip).
    # Defaults match each free tier's known limit:
    #   • groq          ~6000 TPM → 413
    #   • sambanova     DeepSeek-V3.2 here caps at 32K context → 400
    #   • github_models gpt-4o free tier ~8K input-token limit → 413
    _skip_defaults = {"groq": 5500, "sambanova": 30000, "github_models": 6000}
    for p in providers:
        env_var = f"{p['name'].upper()}_SKIP_TOKENS_OVER"
        p["skip_if_tokens_over"] = _int_env(env_var, _skip_defaults.get(p["name"], 0))

    # Per-provider output-token ceiling. Some providers 400 the whole request when
    # max_tokens exceeds their output cap, so we clamp it down in forward().
    #   Configure via  {PROVIDER}_MAX_OUTPUT_TOKENS  (0 = no clamp).
    #   • cohere        command-a caps output at 8192
    #   • github_models gpt-4o here rejects very large max_tokens (e.g. 65536)
    _max_out_defaults = {"cohere": 8192, "github_models": 16384}
    for p in providers:
        env_var = f"{p['name'].upper()}_MAX_OUTPUT_TOKENS"
        p["max_output_tokens"] = _int_env(env_var, _max_out_defaults.get(p["name"], 0))

    return providers


PROVIDERS = _build_providers()

# Providers whose /models endpoint mixes paid models in with the free ones.
# When auto-discovering a replacement model for these, restrict to :free ids so
# a probe can never silently promote the router onto a paid model.
_FREE_ONLY_DISCOVERY = {"openrouter", "naga"}

# ── Credential pool ────────────────────────────────────────────────────────────

# ── Smart routing helpers ─────────────────────────────────────────────────────

def _rate_model(model_name: str) -> int:
    mn = model_name.lower()
    for key in sorted(KNOWN_MODEL_RATINGS, key=len, reverse=True):
        if key in mn:
            return KNOWN_MODEL_RATINGS[key]
    for rating, patterns in _RATING_PATTERNS:
        if any(p in mn for p in patterns):
            return rating
    return 3


def _discover_best_model(base_url: str, key: str, extra_headers: dict = None,
                         free_only: bool = False) -> str | None:
    try:
        hdrs = {"Authorization": f"Bearer {key}", **(extra_headers or {})}
        r = _HTTP.get(f"{base_url.rstrip('/')}/models", headers=hdrs, timeout=10)
        if r.status_code != 200:
            return None
        models = [m["id"] for m in r.json().get("data", []) if isinstance(m.get("id"), str)]
        if free_only:
            models = [m for m in models if m.endswith(":free")]
        return min(models, key=_rate_model) if models else None
    except Exception:
        return None


def _probe_provider(provider: dict, key: str) -> tuple:
    """Returns (success, latency_ms, model_used). Auto-discovers alt model on 400/404.

    A read-timeout means the provider accepted the request and is still
    generating — alive but slow. Large MoE models can cold-start for 30–60s,
    past the probe window, so a read-timeout counts as available rather than
    wrongly dropping a working provider to the back of its rating tier. Only a
    connection failure (host unreachable) counts as down."""
    url  = provider["base_url"].rstrip("/") + "/chat/completions"
    hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
            **provider.get("headers", {})}
    body = {"model": provider["model"],
            "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
    t0 = time.time()
    try:
        r = _HTTP.post(url, headers=hdrs, json=body, timeout=12)
        latency = (time.time() - t0) * 1000
        if r.status_code == 200:
            return True, latency, provider["model"]
        if r.status_code in (400, 404):
            # Providers that list paid models alongside free ones — never let
            # auto-discovery silently pick something that costs credits.
            alt = _discover_best_model(provider["base_url"], key, provider.get("headers", {}),
                                       free_only=provider["name"] in _FREE_ONLY_DISCOVERY)
            if alt:
                body["model"] = alt
                t0 = time.time()
                r2 = _HTTP.post(url, headers=hdrs, json=body, timeout=12)
                if r2.status_code == 200:
                    return True, (time.time() - t0) * 1000, alt
        return False, (time.time() - t0) * 1000, provider["model"]
    except requests.exceptions.ReadTimeout:
        # Connected, still generating — alive, just slow (cold MoE start).
        return True, (time.time() - t0) * 1000, provider["model"]
    except Exception:
        return False, (time.time() - t0) * 1000, provider["model"]


def classify_complexity(messages: list) -> int:
    """Heuristic: 1 (critical) → 5 (trivial). No LLM call."""
    content = " ".join(
        m["content"] if isinstance(m.get("content"), str)
        else " ".join(p.get("text", "") for p in m["content"] if isinstance(p, dict))
        for m in messages if m.get("content")
    )
    tokens = len(content) // 4
    cl = content.lower()
    has_code    = "```" in content or any(k in cl for k in ["def ", "function ", "class ", "import "])
    has_complex = any(k in cl for k in ["implement", "design", "architect", "debug", "refactor",
                                         "algorithm", "optimize", "analyze", "build", "develop",
                                         "summarize", "explain how", "compare", "research", "create a plan",
                                         "generate", "convert", "migrate", "write tests", "test cases",
                                         "step by step", "walk me through", "help me understand"])
    has_simple  = any(k in cl for k in ["what is", "who is", "define", "translate", "yes or no",
                                         "how many", "give me a number", "true or false", "in one word",
                                         "spell", "what does", "one sentence", "yes or no answer",
                                         "what year", "what time", "how old"])
    if tokens > 2000 or (has_code and has_complex): return 1
    if tokens > 800  or has_complex:                return 2
    if tokens > 300  or has_code:                   return 3
    if tokens > 100  or (not has_simple):           return 4
    return 5


def _get_smart_ordered(providers: list, complexity: int, est_tokens: int = 0) -> list:
    """
    Sort providers for this complexity: cheapest capable model first, then
    overkill models, then too-weak as last resort. Never blocks.

    When FAST_ROUTE_THRESHOLD is set and the request is shorter than it,
    low-latency providers win ties between otherwise equally-ranked options.

    Round-robin: providers that tie on every criterion (same rating, same
    availability) are rotated each request so load spreads across them instead
    of always hitting the same one first. We rotate the list by a per-request
    counter before sorting; the sort is stable, so equal-keyed providers keep
    their (rotated) relative order.
    """
    fast_first = FAST_ROUTE_TOKENS > 0 and 0 < est_tokens < FAST_ROUTE_TOKENS

    def _key(p):
        state  = _provider_state.get(p["name"], {})
        rating = state.get("rating", _rate_model(p["model"]))
        avail  = state.get("available", True)
        fast   = 0 if (fast_first and p["name"] in _FAST_PROVIDERS) else 1
        # Health-aware terms — tier/sort_within stay FIRST so capability matching
        # is never overridden by health (a healthy weak model must not outrank the
        # correct-capability one). When every candidate is healthy these two terms
        # are constant (0), leaving the existing round-robin/tie order untouched.
        breaker_open = 1 if stats.breaker_open(p["name"]) else 0  # open breakers sink within tier
        health       = stats.health_bucket(p["name"])            # 0 healthy / 1 degraded / 2 bad
        if rating <= complexity:
            tier        = 0
            sort_within = complexity - rating   # 0 = perfect match, larger = overkill
        else:
            tier        = 1
            sort_within = rating - complexity   # too weak — closest first
        return (tier, sort_within, breaker_open, health, 0 if avail else 1, fast)

    n = len(providers)
    offset = next(_rr_counter) % n if n else 0
    rotated = providers[offset:] + providers[:offset]
    return sorted(rotated, key=_key)


def _initialize_ratings(providers: list, pool_ref):
    """Background: probe all providers, fix bad models, assign ratings, persist state."""
    global _provider_state
    if STATE_FILE.exists():
        try:
            cached_doc = json.loads(STATE_FILE.read_text())
            _provider_state = cached_doc.get("providers", {})
            log.info(f"[ratings] Loaded cached state ({len(_provider_state)} providers)")
            # Probes cost a real completion per provider, so skip them while the
            # state is fresh and still covers every configured provider.
            age = time.time() - cached_doc.get("last_updated_ts", 0)
            if (STATE_TTL_HOURS > 0 and age < STATE_TTL_HOURS * 3600
                    and all(p["name"] in _provider_state for p in providers)):
                for p in providers:
                    cached_model = _provider_state[p["name"]].get("model")
                    if cached_model:
                        p["model"] = cached_model
                log.info(f"[ratings] State is {age/3600:.1f}h old (< {STATE_TTL_HOURS}h TTL) "
                         "— skipping startup probes")
                return
        except Exception:
            pass

    log.info("[ratings] Background provider validation starting…")
    new_state = {}
    for p in providers:
        name  = p["name"]
        probe = pool_ref.pools.get(name, [])
        if not probe:
            new_state[name] = {"rating": _rate_model(p["model"]), "model": p["model"],
                                "available": False, "latency_ms": 0, "overridden": False}
            continue
        key = probe[0]["key"]
        ok, latency, actual = _probe_provider(p, key)
        original   = p["model"]
        overridden = actual != original
        if overridden:
            log.info(f"[ratings]   {name}: model fixed {original} → {actual}")
            p["model"] = actual
        rating = _rate_model(actual)
        log.info(f"[ratings]   {name}: {'✓' if ok else '✗'} rating={rating} model={actual} {latency:.0f}ms")
        new_state[name] = {"rating": rating, "model": actual, "available": ok,
                            "latency_ms": round(latency, 1), "overridden": overridden,
                            "original_model": original}
    _provider_state = new_state
    try:
        STATE_FILE.write_text(json.dumps({"last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                           "last_updated_ts": time.time(),
                                           "providers": new_state}, indent=2))
        log.info("[ratings] State persisted to disk")
    except Exception as e:
        log.warning(f"[ratings] Could not persist state: {e}")


class CredentialPool:
    """Thread-safe round-robin key pool with per-key cooldown tracking."""

    def __init__(self, providers: list[dict]):
        self.lock  = threading.Lock()
        self.pools: dict[str, deque] = {}
        for p in providers:
            self.pools[p["name"]] = deque(
                {"key": k, "cool_until": 0.0} for k in p["keys"]
            )
            log.info(f"  {p['name']}: {len(p['keys'])} key(s) loaded")

    def get_key(self, provider_name: str) -> str | None:
        """Return the next ready key (round-robin), or None if all are cooling."""
        with self.lock:
            pool = self.pools.get(provider_name, deque())
            now  = time.time()
            for _ in range(len(pool)):
                entry = pool[0]
                pool.rotate(-1)
                if entry["cool_until"] <= now:
                    return entry["key"]
            return None

    def mark_rate_limited(self, provider_name: str, key: str, retry_after: int = 60):
        """Put a specific key into cooldown."""
        with self.lock:
            for entry in self.pools.get(provider_name, []):
                if entry["key"] == key:
                    entry["cool_until"] = time.time() + retry_after
                    log.warning(f"  {provider_name} key ...{key[-6:]} cooling for {retry_after}s")
                    return


pool = CredentialPool(PROVIDERS)

# Background: validate providers, fix models, assign ratings
threading.Thread(target=_initialize_ratings, args=(PROVIDERS, pool), daemon=True).start()

# ── Per-provider stats ─────────────────────────────────────────────────────────

class ProviderStats:
    """Tracks latency and error rates per provider for observability."""

    def __init__(self):
        self.lock   = threading.Lock()
        self._data: dict[str, dict] = {}

    def _ensure(self, name: str):
        if name not in self._data:
            self._data[name] = {"latency_sum": 0.0, "latency_count": 0,
                                "error_count": 0, "request_count": 0,
                                "health": deque(maxlen=BREAKER_WINDOW), "open_until": 0.0}

    def record_success(self, name: str, latency_s: float):
        with self.lock:
            self._ensure(name)
            s = self._data[name]
            s["latency_sum"]   += latency_s
            s["latency_count"] += 1
            s["request_count"] += 1

    def record_error(self, name: str):
        with self.lock:
            self._ensure(name)
            s = self._data[name]
            s["error_count"]   += 1
            s["request_count"] += 1

    # ── Circuit breaker ──────────────────────────────────────────────────────
    def record_health(self, name: str, ok: bool):
        """Record a HEALTH outcome (separate from request stats — breaker only).
        On failure: trip the breaker open once the window has enough samples and
        the health-fail fraction crosses the threshold. On success: half-open
        recovery — close the breaker and wipe the window for a clean slate."""
        with self.lock:
            self._ensure(name)
            s   = self._data[name]
            win = s["health"]
            win.append(ok)
            if ok:
                s["open_until"] = 0.0
                win.clear()
            elif len(win) >= BREAKER_MIN_SAMPLES:
                fails = sum(1 for x in win if not x)
                if fails / len(win) >= BREAKER_ERROR_RATE:
                    s["open_until"] = time.time() + BREAKER_COOLDOWN

    def breaker_open(self, name: str) -> bool:
        with self.lock:
            s = self._data.get(name)
            return bool(s) and time.time() < s.get("open_until", 0.0)

    def breaker_status(self, name: str) -> dict:
        with self.lock:
            s   = self._data.get(name, {})
            now = time.time()
            open_until = s.get("open_until", 0.0)
            win   = s.get("health", ())
            fails = sum(1 for x in win if not x)
            return {"open": now < open_until,
                    "opens_in_s": max(0, round(open_until - now)),
                    "recent_health_fails": fails}

    def health_bucket(self, name: str) -> int:
        """Recent error-rate bucket for routing: 0 healthy / 1 degraded / 2 bad.
        Too few samples → 0 (unknown = healthy; don't penalize new providers)."""
        with self.lock:
            s = self._data.get(name)
            if not s:
                return 0
            win = s.get("health", ())
            if len(win) < BREAKER_MIN_SAMPLES:
                return 0
            err_rate = sum(1 for x in win if not x) / len(win)
            return 0 if err_rate < 0.10 else (1 if err_rate < 0.50 else 2)

    def summary(self, name: str) -> dict:
        with self.lock:
            s  = self._data.get(name, {})
            lc = s.get("latency_count", 0)
            rc = s.get("request_count", 0)
            ec = s.get("error_count", 0)
            return {
                "avg_latency_ms": round(s.get("latency_sum", 0) / lc * 1000) if lc else None,
                "error_rate":     round(ec / rc, 3) if rc else 0.0,
                "total_requests": rc,
            }

    def all_summaries(self) -> dict:
        with self.lock:
            return {name: self.summary(name) for name in self._data}


stats = ProviderStats()

# ── Response cache ─────────────────────────────────────────────────────────────

class ResponseCache:
    """
    In-memory LRU cache for non-streaming responses.
    Identical requests (same model + messages) return a cached copy,
    saving free-tier quota for novel queries.
    Set CACHE_TTL_SECONDS=0 to disable.
    """

    def __init__(self, ttl: int = 300, max_size: int = 100):
        self.ttl      = ttl
        self.max_size = max_size
        self.lock     = threading.Lock()
        self._store: OrderedDict = OrderedDict()  # hash -> (data, timestamp)
        self.hits     = 0
        self.misses   = 0

    def _hash(self, payload: dict) -> str:
        # Hash the entire request (minus "stream", which doesn't change the
        # answer) so requests differing only in temperature, max_tokens,
        # tools, response_format, etc. never collide.
        relevant = {k: v for k, v in payload.items() if k != "stream"}
        content = json.dumps(relevant, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get(self, payload: dict) -> dict | None:
        if self.ttl <= 0:
            return None
        key = self._hash(payload)
        with self.lock:
            if key in self._store:
                data, ts = self._store[key]
                if time.time() - ts < self.ttl:
                    self._store.move_to_end(key)
                    self.hits += 1
                    return data
                del self._store[key]
            self.misses += 1
        return None

    def set(self, payload: dict, data: dict):
        if self.ttl <= 0:
            return
        key = self._hash(payload)
        with self.lock:
            if len(self._store) >= self.max_size:
                self._store.popitem(last=False)  # evict oldest
            self._store[key] = (data, time.time())

    @property
    def size(self) -> int:
        with self.lock:
            return len(self._store)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 3) if total else 0.0


cache = ResponseCache(ttl=CACHE_TTL, max_size=CACHE_MAX_SIZE)

# ── Thinking field stripping ───────────────────────────────────────────────────
# Some providers (e.g. Gemini 2.5) emit reasoning/thinking fields in responses.
# These fields cause 400 errors on other providers (Groq, Cerebras, OpenRouter).
# We strip them from both outgoing requests and incoming responses.

def _strip_message(msg: dict):
    """Remove thinking fields from a message dict in-place."""
    msg.pop("reasoning_content", None)
    msg.pop("think", None)
    if isinstance(msg.get("content"), list):
        msg["content"] = [
            b for b in msg["content"]
            if b.get("type") not in ("thinking", "think")
        ]


def _strip_response(data: dict):
    """Strip thinking fields from a non-streaming response before returning it."""
    for choice in data.get("choices", []):
        if "message" in choice:
            _strip_message(choice["message"])


def _streaming_generator(resp: requests.Response):
    """
    Yield SSE chunks with thinking fields stripped from delta objects.
    Buffers by newline to handle chunks that split across SSE boundaries.
    """
    buf = b""
    for raw_chunk in resp.iter_content(chunk_size=None):
        buf += raw_chunk
        while b"\n" in buf:
            line_bytes, buf = buf.split(b"\n", 1)
            line = line_bytes.decode("utf-8", errors="replace")
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    event = json.loads(line[6:])
                    for choice in event.get("choices", []):
                        delta = choice.get("delta", {})
                        delta.pop("reasoning_content", None)
                        delta.pop("think", None)
                    yield ("data: " + json.dumps(event) + "\n").encode("utf-8")
                    continue
                except (json.JSONDecodeError, Exception):
                    pass
            yield (line + "\n").encode("utf-8")
    if buf:
        yield buf

# ── Complexity-aware provider ordering ────────────────────────────────────────

def _estimated_tokens(messages: list) -> int:
    """Rough token estimate: total content characters / 4."""
    return sum(len(str(m.get("content", ""))) for m in messages) // 4


def _ordered_providers(payload: dict) -> list[dict]:
    """
    Smart complexity-aware ordering: use cheapest capable model for simple
    tasks, best model for complex ones. With FAST_ROUTE_THRESHOLD set,
    short requests break ties in favour of low-latency providers.
    """
    messages   = payload.get("messages", [])
    complexity = classify_complexity(messages)
    ordered    = _get_smart_ordered(PROVIDERS, complexity, _estimated_tokens(messages))
    log.info(f"→ complexity={complexity} ({_COMPLEXITY_LABELS[complexity]}) "
             f"order={[p['name'] for p in ordered]}")
    return ordered

# ── Request forwarding ─────────────────────────────────────────────────────────

def forward(provider: dict, key: str, payload: dict, streaming: bool) -> requests.Response | None:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        **provider.get("headers", {}),
    }

    body = dict(payload)

    # Remap any placeholder model name to the provider's real model
    if body.get("model", "") in ("", ROUTER_MODEL, "auto"):
        body["model"] = provider["model"]

    # Strip thinking fields from conversation history before forwarding
    if "messages" in body:
        cleaned = []
        for msg in body["messages"]:
            m = dict(msg)
            _strip_message(m)
            cleaned.append(m)
        body["messages"] = cleaned

    # Strip top-level thinking fields (Gemini sometimes adds these)
    body.pop("think", None)
    body.pop("thinking", None)

    # Clamp the requested output length to this provider's hard ceiling. Some
    # providers (e.g. Cohere caps output at 8192) reject the ENTIRE request with
    # a 400 when max_tokens exceeds their limit — so a client default like
    # max_tokens=65536 would fail every call. Capping it lets the request through;
    # the model still produces up to its real maximum.
    out_cap = provider.get("max_output_tokens", 0)
    if out_cap:
        for field in ("max_tokens", "max_completion_tokens"):
            if isinstance(body.get(field), int) and body[field] > out_cap:
                log.info(f"  clamping {field} {body[field]}→{out_cap} for {provider['name']}")
                body[field] = out_cap

    url = provider["base_url"].rstrip("/") + "/chat/completions"
    try:
        return _HTTP.post(url, headers=headers, json=body, stream=streaming, timeout=(10, 120))
    except requests.exceptions.RequestException as e:
        log.error(f"  Network error → {provider['name']}: {e}")
        return None

# ── Flask app ──────────────────────────────────────────────────────────────────

app = Flask(__name__)
# Cap request bodies so a buggy client can't exhaust memory (Flask returns 413)
app.config["MAX_CONTENT_LENGTH"] = _int_env("MAX_REQUEST_BYTES", 10 * 1024 * 1024)


def _auth_check():
    header = request.headers.get("Authorization", "").strip()
    token  = header[7:].strip() if header[:7].lower() == "bearer " else header
    # compare_digest keeps the comparison constant-time per key
    if not any(hmac.compare_digest(token, k) for k in PROXY_API_KEYS):
        return jsonify({"error": "unauthorized"}), 401


@app.route("/health")
def health():
    """Unauthenticated health check for uptime monitoring."""
    return jsonify({"status": "ok", "providers": [p["name"] for p in PROVIDERS]})


@app.route("/v1/models")
def models():
    err = _auth_check()
    if err:
        return err
    return jsonify({"object": "list", "data": [
        {"id": ROUTER_MODEL, "object": "model", "owned_by": "hermes-router"}
    ]})


@app.route("/v1/chat/completions", methods=["POST"])
def chat():
    err = _auth_check()
    if err:
        return err

    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": {"message": "request body must be a JSON object",
                                  "type": "invalid_request_error"}}), 400
    streaming = payload.get("stream", False)
    messages  = payload.get("messages", [])

    # Cache check (non-streaming only)
    if not streaming:
        cached = cache.get(payload)
        if cached is not None:
            log.info("↩ cache hit")
            return jsonify(cached)

    est_tokens = _estimated_tokens(messages)
    ordered    = _ordered_providers(payload)

    # Circuit breaker: skip providers whose breaker is open. SAFETY — if EVERY
    # candidate is open, treat them all as half-open probes (skip none) so we
    # always make forward progress instead of hard-failing while options remain.
    any_closed = any(not stats.breaker_open(p["name"]) for p in ordered)

    for provider in ordered:
        name     = provider["name"]

        # Breaker open → skip (unless all are open, then probe everything).
        if any_closed and stats.breaker_open(name):
            log.info(f"⨂ skipping {name} (circuit open)")
            continue

        # Skip providers whose payload ceiling this request would exceed
        # (e.g. Groq's free TPM) — avoids a guaranteed 413 round-trip.
        cap = provider.get("skip_if_tokens_over", 0)
        if cap and est_tokens > cap:
            log.info(f"⤳ skipping {name} (~{est_tokens} tok > {cap} cap)")
            continue

        attempts = len(pool.pools.get(name, [])) or 1

        for _ in range(attempts):
            key = pool.get_key(name)
            if not key:
                log.warning(f"All {name} keys cooling — skipping provider")
                break

            log.info(f"→ Trying {name} ...{key[-6:]}")
            t0   = time.time()
            resp = forward(provider, key, payload, streaming)
            elapsed = time.time() - t0

            if resp is None:
                stats.record_error(name)
                stats.record_health(name, False)   # network/timeout = provider health failure
                pool.mark_rate_limited(name, key, retry_after=30)
                continue

            if resp.status_code == 429:
                stats.record_error(name)
                # 429 is NOT a health failure — key cooldown already handles it.
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                pool.mark_rate_limited(name, key, retry_after=retry_after)
                log.warning(f"  {name} 429 — cooldown {retry_after}s, trying next key")
                continue

            if resp.status_code in (400, 401, 403):
                stats.record_error(name)
                # request/auth-specific — NOT a provider health failure.
                log.error(f"  {name} {resp.status_code} — skipping provider: {resp.text[:200]}")
                break

            if resp.status_code == 413:
                stats.record_error(name)
                # payload-specific — NOT a provider health failure.
                log.warning(f"  {name} 413 — payload too large, cascading")
                break

            if resp.status_code >= 500:
                stats.record_error(name)
                stats.record_health(name, False)   # 5xx = provider health failure
                pool.mark_rate_limited(name, key, retry_after=15)
                continue

            if not (200 <= resp.status_code < 300):
                stats.record_error(name)
                stats.record_health(name, False)   # unexpected non-2xx = health failure
                log.warning(f"  {name} unexpected {resp.status_code} — skipping provider")
                break

            # Success
            stats.record_success(name, elapsed)
            stats.record_health(name, True)        # 2xx = healthy (half-open recovery)
            log.info(f"  ✓ {name} {resp.status_code} ({elapsed*1000:.0f}ms)")
            if streaming:
                return Response(
                    stream_with_context(_streaming_generator(resp)),
                    content_type=resp.headers.get("Content-Type", "text/event-stream"),
                    headers={"X-Provider": name},
                )
            else:
                data = resp.json()
                _strip_response(data)
                cache.set(payload, data)
                return jsonify(data), resp.status_code

        log.warning(f"✗ {name} exhausted — cascading")

    return jsonify({"error": {"message": "All providers exhausted", "type": "router_error"}}), 503


@app.route("/v1/status")
def status():
    """Show key cooldown state, latency/error stats, and cache metrics."""
    err = _auth_check()
    if err:
        return err

    now  = time.time()
    keys = {}
    with pool.lock:
        for name, entries in pool.pools.items():
            keys[name] = [
                {
                    "key_tail": e["key"][-6:],
                    "status":   "cooling" if e["cool_until"] > now else "ready",
                    "ready_in": max(0, round(e["cool_until"] - now)),
                }
                for e in entries
            ]

    provider_stats = {}
    for p in PROVIDERS:
        entry = {
            "keys":  keys.get(p["name"], []),
            "stats": stats.summary(p["name"]),
            "breaker": stats.breaker_status(p["name"]),
        }
        if p.get("skip_if_tokens_over"):
            entry["skip_if_tokens_over"] = p["skip_if_tokens_over"]
        if p.get("max_output_tokens"):
            entry["max_output_tokens"] = p["max_output_tokens"]
        provider_stats[p["name"]] = entry

    return jsonify({
        "providers": provider_stats,
        "cache": {
            "enabled":  CACHE_TTL > 0,
            "ttl_s":    CACHE_TTL,
            "size":     cache.size,
            "max_size": CACHE_MAX_SIZE,
            "hits":     cache.hits,
            "misses":   cache.misses,
            "hit_rate": cache.hit_rate,
        },
        "fast_routing": {
            "enabled":         FAST_ROUTE_TOKENS > 0,
            "threshold_tokens": FAST_ROUTE_TOKENS,
            "fast_providers":  sorted(_FAST_PROVIDERS),
        },
        "circuit_breaker": {
            "window":      BREAKER_WINDOW,
            "min_samples": BREAKER_MIN_SAMPLES,
            "error_rate":  BREAKER_ERROR_RATE,
            "cooldown_s":  BREAKER_COOLDOWN,
        },
    })


if __name__ == "__main__":
    log.info(f"hermes-router starting on :{PORT}")
    log.info(f"Providers: {[p['name'] for p in PROVIDERS]}")
    log.info(f"Cache: {'enabled' if CACHE_TTL > 0 else 'disabled'} (TTL={CACHE_TTL}s, max={CACHE_MAX_SIZE})")
    log.info(f"Fast routing: {'enabled' if FAST_ROUTE_TOKENS > 0 else 'disabled'} (threshold={FAST_ROUTE_TOKENS} tokens)")
    _skips = {p["name"]: p["skip_if_tokens_over"] for p in PROVIDERS if p.get("skip_if_tokens_over")}
    if _skips:
        log.info(f"Large-payload skip ceilings: {_skips}")
    try:
        from waitress import serve
        log.info("Serving with waitress (production WSGI)")
        serve(app, host="0.0.0.0", port=PORT, threads=int(os.environ.get("WORKER_THREADS", 16)))
    except ImportError:
        log.warning("waitress not installed — falling back to Flask dev server")
        app.run(host="0.0.0.0", port=PORT, threaded=True)
