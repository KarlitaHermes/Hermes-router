#!/usr/bin/env python3
"""
hermes-router — Free-tier AI load balancer with automatic key rotation.

A lightweight OpenAI-compatible proxy that:
  - Rotates across multiple API keys per provider automatically
  - Cascades to the next provider when one is exhausted or rate-limited
  - Strips thinking/reasoning fields that break non-Claude providers
  - Handles 413 (payload too large) by cascading instead of crashing

Supported providers (configure via .env):
  Gemini → OpenRouter → Cerebras → Groq

Quick start:
  pip install -r requirements.txt
  cp .env.example .env   # add your API keys
  python router.py
"""

import json, os, time, threading, logging
from pathlib import Path
from collections import deque
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

PORT           = int(os.environ.get("PORT", 8319))
PROXY_API_KEYS = [k.strip() for k in os.environ.get("PROXY_API_KEYS", "sk-router-1").split(",") if k.strip()]
ROUTER_MODEL   = os.environ.get("ROUTER_MODEL_ID", "hermes-router")


def _keys(env_var: str) -> list[str]:
    """Parse comma-separated API keys from an environment variable."""
    return [k.strip() for k in os.environ.get(env_var, "").split(",") if k.strip()]


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

    if not providers:
        log.warning("No providers configured — set GEMINI_API_KEYS, OPENROUTER_API_KEYS, etc. in .env")
    return providers


PROVIDERS = _build_providers()

# ── Credential pool ────────────────────────────────────────────────────────────

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
        """Return the next ready key for a provider, or None if all are cooling."""
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


def _auth_check():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if token not in PROXY_API_KEYS:
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

    payload   = request.get_json(force=True)
    streaming = payload.get("stream", False)

    for provider in PROVIDERS:
        name     = provider["name"]
        attempts = len(pool.pools.get(name, [])) or 1

        for _ in range(attempts):
            key = pool.get_key(name)
            if not key:
                log.warning(f"All {name} keys cooling — skipping provider")
                break

            log.info(f"→ Trying {name} ...{key[-6:]}")
            resp = forward(provider, key, payload, streaming)

            if resp is None:
                pool.mark_rate_limited(name, key, retry_after=30)
                continue

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                pool.mark_rate_limited(name, key, retry_after=retry_after)
                log.warning(f"  {name} 429 — cooldown {retry_after}s, trying next key")
                continue

            if resp.status_code in (400, 401, 403):
                log.error(f"  {name} {resp.status_code} — skipping provider: {resp.text[:200]}")
                break

            if resp.status_code == 413:
                log.warning(f"  {name} 413 — payload too large, cascading")
                break

            if resp.status_code >= 500:
                pool.mark_rate_limited(name, key, retry_after=15)
                continue

            if not (200 <= resp.status_code < 300):
                log.warning(f"  {name} unexpected {resp.status_code} — skipping provider")
                break

            # Success
            log.info(f"  ✓ {name} {resp.status_code}")
            if streaming:
                return Response(
                    stream_with_context(_streaming_generator(resp)),
                    content_type=resp.headers.get("Content-Type", "text/event-stream"),
                    headers={"X-Provider": name},
                )
            else:
                data = resp.json()
                _strip_response(data)
                return jsonify(data), resp.status_code

        log.warning(f"✗ {name} exhausted — cascading")

    return jsonify({"error": {"message": "All providers exhausted", "type": "router_error"}}), 503


@app.route("/v1/status")
def status():
    """Show key cooldown state for all providers."""
    err = _auth_check()
    if err:
        return err
    now = time.time()
    out = {}
    with pool.lock:
        for name, entries in pool.pools.items():
            out[name] = [
                {
                    "key_tail":  e["key"][-6:],
                    "status":    "cooling" if e["cool_until"] > now else "ready",
                    "ready_in":  max(0, round(e["cool_until"] - now)),
                }
                for e in entries
            ]
    return jsonify(out)


if __name__ == "__main__":
    log.info(f"hermes-router starting on :{PORT}")
    log.info(f"Providers: {[p['name'] for p in PROVIDERS]}")
    log.info(f"Proxy auth keys: {len(PROXY_API_KEYS)} configured")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
