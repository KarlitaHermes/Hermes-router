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
  Gemini → OpenRouter → SambaNova → GitHub Models → Cerebras → Groq → Mistral → Cohere → Z.ai (GLM)

Quick start:
  pip install -r requirements.txt
  cp .env.example .env   # add your API keys
  python router.py
"""

import json, os, time, threading, logging, hashlib, hmac
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

PORT              = int(os.environ.get("PORT", 8319))
PROXY_API_KEYS    = [k.strip() for k in os.environ.get("PROXY_API_KEYS", "sk-router-1").split(",") if k.strip()]
ROUTER_MODEL      = os.environ.get("ROUTER_MODEL_ID", "hermes-router")
CACHE_TTL         = int(os.environ.get("CACHE_TTL_SECONDS", 300))   # 0 = disabled
CACHE_MAX_SIZE    = int(os.environ.get("CACHE_MAX_SIZE", 100))
FAST_ROUTE_TOKENS = int(os.environ.get("FAST_ROUTE_THRESHOLD", 0))  # 0 = disabled
STATE_FILE        = Path(os.environ.get("ROUTER_STATE_FILE", "./router_state.json"))

# Providers known for low-latency inference — promoted for short requests
_FAST_PROVIDERS = {"groq", "cerebras", "sambanova"}

# ── Smart routing: capability ratings ─────────────────────────────────────────
# 1=outstanding  2=best  3=good  4=fair  5=basic  (lower = more capable)
# Recommended base model: set ROUTER_BASE_MODEL_PROVIDER + ROUTER_BASE_MODEL
# e.g. ROUTER_BASE_MODEL_PROVIDER=openai  ROUTER_BASE_MODEL=gpt-4o-mini
KNOWN_MODEL_RATINGS: dict = {
    # 1 — Outstanding
    "gpt-5.3-codex": 1, "gpt-5-codex": 1, "gpt-4o": 1, "o1": 1, "o3": 1,
    "claude-opus-4": 1, "claude-opus": 1, "gemini-2.5-pro": 1,
    # 2 — Best
    "gemini-2.5-flash": 2, "gemini-2.0-flash": 2,
    "llama-3.3-70b": 2, "llama-3.1-70b": 2,
    "mistral-large": 2, "mistral-medium": 2,
    "command-r-plus": 2, "nvidia/nemotron-3-super": 2, "nemotron": 2,
    "claude-sonnet": 2, "claude-3-5": 2, "grok-2": 2,
    # 3 — Good
    "gemini-2.5-flash-lite": 3, "gemini-1.5-flash": 3,
    "gpt-4o-mini": 3, "gpt-oss-120b": 3,
    "mistral-small": 3, "glm-4.5-flash": 3, "glm-4.7-flash": 3,
    "llama-3.1-8b-instant": 3,
    # 4 — Fair
    "command-r7b": 4, "command-r7b-12-2024": 4,
    "llama-3.2-3b": 4, "mistral-7b": 4,
}
_RATING_PATTERNS: list = [
    (1, ["pro-exp", "ultra", "opus", "o3", "o1-pro"]),
    (2, ["70b", "large", "plus", "pro", "turbo", "super", "sonnet"]),
    (3, ["flash", "small", "mini", "medium", "120b", "8b-instant", "glm-4"]),
    (4, ["7b", "8b", "lite", "fast", "r7b", "nano", "3b"]),
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

    gemini_keys = _keys("GEMINI_API_KEYS")
    if gemini_keys:
        providers.append({
            "name":     "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model":    os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            "keys":     gemini_keys,
        })

    openrouter_keys = _keys("OPENROUTER_API_KEYS")
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

    sambanova_keys = _keys("SAMBANOVA_API_KEYS") or _keys("SAMBANOVA_API_KEY")
    if sambanova_keys:
        providers.append({
            "name":     "sambanova",
            "base_url": "https://api.sambanova.ai/v1",
            "model":    os.environ.get("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct"),
            "keys":     sambanova_keys,
        })

    github_keys = _keys("GITHUB_MODELS_TOKENS") or _keys("GITHUB_MODELS_TOKEN")
    if github_keys:
        providers.append({
            "name":     "github_models",
            "base_url": "https://models.inference.ai.azure.com",
            "model":    os.environ.get("GITHUB_MODELS_MODEL", "gpt-4o-mini"),
            "keys":     github_keys,
        })

    cerebras_keys = _keys("CEREBRAS_API_KEYS") or _keys("CEREBRAS_API_KEY")
    if cerebras_keys:
        providers.append({
            "name":     "cerebras",
            "base_url": "https://api.cerebras.ai/v1",
            "model":    os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b"),
            "keys":     cerebras_keys,
        })

    groq_keys = _keys("GROQ_API_KEYS") or _keys("GROQ_API_KEY")
    if groq_keys:
        providers.append({
            "name":     "groq",
            "base_url": "https://api.groq.com/openai/v1",
            "model":    os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant"),
            "keys":     groq_keys,
        })

    mistral_keys = _keys("MISTRAL_API_KEYS") or _keys("MISTRAL_API_KEY")
    if mistral_keys:
        providers.append({
            "name":     "mistral",
            "base_url": "https://api.mistral.ai/v1",
            "model":    os.environ.get("MISTRAL_MODEL", "mistral-small-latest"),
            "keys":     mistral_keys,
        })

    cohere_keys = _keys("COHERE_API_KEYS") or _keys("COHERE_API_KEY")
    if cohere_keys:
        providers.append({
            "name":     "cohere",
            "base_url": "https://api.cohere.ai/compatibility/v1",
            "model":    os.environ.get("COHERE_MODEL", "command-r7b-12-2024"),
            "keys":     cohere_keys,
        })

    zai_keys = _keys("GLM_API_KEYS") or _keys("GLM_API_KEY")
    if zai_keys:
        providers.append({
            "name":     "zai",
            "base_url": "https://api.z.ai/api/paas/v4",
            "model":    os.environ.get("ZAI_MODEL", "glm-4.5-flash"),
            "keys":     zai_keys,
        })

    if not providers:
        log.warning("No providers configured — set GEMINI_API_KEYS, OPENROUTER_API_KEYS, etc. in .env")

    # Per-provider "skip when the request is too big" ceiling. Some free tiers
    # reject large payloads outright (e.g. Groq's free tier caps tokens-per-minute
    # at ~6000 and returns 413), so trying them with a big prompt just wastes a
    # round-trip before cascading. When the estimated request size exceeds a
    # provider's ceiling, that provider is skipped entirely.
    #   Configure via  {PROVIDER}_SKIP_TOKENS_OVER  (0 = never skip).
    # Groq defaults to 5500 to match its free TPM; override if you're on a paid tier.
    _skip_defaults = {"groq": 5500}
    for p in providers:
        env_var = f"{p['name'].upper()}_SKIP_TOKENS_OVER"
        p["skip_if_tokens_over"] = _int_env(env_var, _skip_defaults.get(p["name"], 0))

    return providers


PROVIDERS = _build_providers()

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


def _discover_best_model(base_url: str, key: str, extra_headers: dict = None) -> str | None:
    try:
        hdrs = {"Authorization": f"Bearer {key}", **(extra_headers or {})}
        r = requests.get(f"{base_url.rstrip('/')}/models", headers=hdrs, timeout=10)
        if r.status_code != 200:
            return None
        models = [m["id"] for m in r.json().get("data", []) if isinstance(m.get("id"), str)]
        return min(models, key=_rate_model) if models else None
    except Exception:
        return None


def _probe_provider(provider: dict, key: str) -> tuple:
    """Returns (success, latency_ms, model_used). Auto-discovers alt model on 400/404."""
    url  = provider["base_url"].rstrip("/") + "/chat/completions"
    hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
            **provider.get("headers", {})}
    body = {"model": provider["model"],
            "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
    t0 = time.time()
    try:
        r = requests.post(url, headers=hdrs, json=body, timeout=12)
        latency = (time.time() - t0) * 1000
        if r.status_code == 200:
            return True, latency, provider["model"]
        if r.status_code in (400, 404):
            alt = _discover_best_model(provider["base_url"], key, provider.get("headers", {}))
            if alt:
                body["model"] = alt
                t0 = time.time()
                r2 = requests.post(url, headers=hdrs, json=body, timeout=12)
                if r2.status_code == 200:
                    return True, (time.time() - t0) * 1000, alt
        return False, (time.time() - t0) * 1000, provider["model"]
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
                                         "algorithm", "optimize", "analyze", "build", "develop"])
    has_simple  = any(k in cl for k in ["what is", "who is", "define", "translate", "yes or no"])
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
    """
    fast_first = FAST_ROUTE_TOKENS > 0 and 0 < est_tokens < FAST_ROUTE_TOKENS

    def _key(p):
        state  = _provider_state.get(p["name"], {})
        rating = state.get("rating", _rate_model(p["model"]))
        avail  = state.get("available", True)
        fast   = 0 if (fast_first and p["name"] in _FAST_PROVIDERS) else 1
        if rating <= complexity:
            return (0, complexity - rating, 0 if avail else 1, fast)   # perfect match = 0 delta
        return (1, rating - complexity, 0 if avail else 1, fast)        # too weak — closest first
    return sorted(providers, key=_key)


def _initialize_ratings(providers: list, pool_ref):
    """Background: probe all providers, fix bad models, assign ratings, persist state."""
    global _provider_state
    if STATE_FILE.exists():
        try:
            _provider_state = json.loads(STATE_FILE.read_text()).get("providers", {})
            log.info(f"[ratings] Loaded cached state ({len(_provider_state)} providers)")
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
                                "error_count": 0, "request_count": 0}

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

    url = provider["base_url"].rstrip("/") + "/chat/completions"
    try:
        return requests.post(url, headers=headers, json=body, stream=streaming, timeout=(10, 120))
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

    for provider in _ordered_providers(payload):
        name     = provider["name"]

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
                pool.mark_rate_limited(name, key, retry_after=30)
                continue

            if resp.status_code == 429:
                stats.record_error(name)
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                pool.mark_rate_limited(name, key, retry_after=retry_after)
                log.warning(f"  {name} 429 — cooldown {retry_after}s, trying next key")
                continue

            if resp.status_code in (400, 401, 403):
                stats.record_error(name)
                log.error(f"  {name} {resp.status_code} — skipping provider: {resp.text[:200]}")
                break

            if resp.status_code == 413:
                stats.record_error(name)
                log.warning(f"  {name} 413 — payload too large, cascading")
                break

            if resp.status_code >= 500:
                stats.record_error(name)
                pool.mark_rate_limited(name, key, retry_after=15)
                continue

            if not (200 <= resp.status_code < 300):
                stats.record_error(name)
                log.warning(f"  {name} unexpected {resp.status_code} — skipping provider")
                break

            # Success
            stats.record_success(name, elapsed)
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
        }
        if p.get("skip_if_tokens_over"):
            entry["skip_if_tokens_over"] = p["skip_if_tokens_over"]
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
    })


if __name__ == "__main__":
    log.info(f"hermes-router starting on :{PORT}")
    log.info(f"Providers: {[p['name'] for p in PROVIDERS]}")
    log.info(f"Cache: {'enabled' if CACHE_TTL > 0 else 'disabled'} (TTL={CACHE_TTL}s, max={CACHE_MAX_SIZE})")
    log.info(f"Fast routing: {'enabled' if FAST_ROUTE_TOKENS > 0 else 'disabled'} (threshold={FAST_ROUTE_TOKENS} tokens)")
    _skips = {p["name"]: p["skip_if_tokens_over"] for p in PROVIDERS if p.get("skip_if_tokens_over")}
    if _skips:
        log.info(f"Large-payload skip ceilings: {_skips}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
