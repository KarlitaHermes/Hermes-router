---
title: "Architecture — How it works"
description: "The full picture: the request pipeline, credential pool, smart routing, failover, protocol translation (OpenAI/Anthropic/Codex), caching, and observability."
---

hermes-router is a single Python file (`router.py`) running a small Flask/Waitress server. It
accepts OpenAI- or Anthropic-format requests and forwards each one to the best available
provider in a pool, handling key rotation, failover, and format translation transparently.

## The request pipeline

Every request flows through the same pipeline:

```
  ┌──────────┐   OpenAI- or Anthropic-format    ┌─────────────────────────────────────┐
  │ Your app │ ───────────────────────────────► │            hermes-router            │
  └──────────┘   Bearer / x-api-key (PROXY key)  │                                     │
       ▲                                          │  1. Auth check (constant-time)      │
       │                                          │  2. Cache lookup (per-caller)       │
       │            OpenAI/Anthropic response     │  3. Rate the request 1–5            │
       └────────────────────────────────────────►│  4. Order providers by fit + health │
                                                  │  5. Try providers, rotate keys      │
                                                  └───────────────┬─────────────────────┘
                                                                  │ first one that succeeds
                                                  ┌───────────────▼─────────────────────┐
                                                  │ Gemini · OpenRouter · Groq · Mistral │
                                                  │ Cohere · NVIDIA · Codex · … (15)     │
                                                  └──────────────────────────────────────┘
```

1. **Authenticate** — the caller's key is compared against `PROXY_API_KEYS` in constant time
   (`hmac.compare_digest`). Both `Authorization: Bearer` and Anthropic's `x-api-key` are accepted.
2. **Cache lookup** — identical requests can be served from an in-memory cache, namespaced by
   the calling key (see [Response cache](#response-cache)).
3. **Rate the request** — a 1–5 difficulty score is computed from length and content, with no
   extra API call.
4. **Order providers** — each model is scored 1–5 for capability; the router prefers the
   *cheapest* model that can still handle the request, skips unhealthy ones, and rotates among
   equally-good ties.
5. **Try and fail over** — it sends to the first provider, rotating keys; on a rate-limit or
   error it cascades to the next, so a single failure never reaches your app.

## The moving parts

### Credential pool

Every provider can hold many keys (from `auth.json` first, then `.env`). Keys are tracked in a
thread-safe pool with per-key cooldowns. A key that gets rate-limited (HTTP 429) is put on a
short cooldown and skipped until it recovers.

**Rotation modes** (set with `hr mode`, see [Configuration](/configuration/#key-rotation-mode)):

- `round-robin` *(default)* — spread requests evenly across all keys; they deplete together.
- `sequential` — drain one key fully until it rate-limits, then move to the next, keeping later
  keys/accounts fresh in reserve. Ideal for rationing many accounts.

### Smart routing

Requests are scored for difficulty and models for capability (both 1–5, lower = more capable).
The router picks the cheapest model that can handle the request. Tool requests are only sent to
providers whose model supports function calling (detected at startup). Optional **fast routing**
(`FAST_ROUTE_THRESHOLD`) sends short requests to low-latency providers first.

### Failover & circuit breaker

If a provider errors or times out, the router cascades to the next automatically. A provider
that keeps failing health checks (network errors or 5xx — not rate-limits or bad requests) has
its **circuit breaker** tripped: it's pulled out of rotation for a cooldown, then re-probed
(half-open). Healthy providers are always preferred. Tunable via the `BREAKER_*` settings.

### Response cache

Identical requests can be served from an in-memory TTL+LRU cache, saving free-tier quota. Cache
entries are **namespaced by the caller's API key**, so two different `PROXY_API_KEYS` never share
a cached answer for the same prompt — safe to expose to multiple users. Disable with
`CACHE_TTL_SECONDS=0`.

### Accurate token counting

Request size is measured with `tiktoken` (the `o200k_base` encoder, loaded lazily) for accurate
routing and large-payload skipping, with a `characters ÷ 4` fallback when tiktoken is unavailable.

### Capability probing

At startup the router probes each provider once to learn its real model, whether it supports
**function calling**, and whether it's a **reasoning model**. Results are cached to
`router_state.json` for `ROUTER_STATE_TTL_HOURS` (default 24h) so restarts don't re-probe. You
can override any result with `<PROVIDER>_SUPPORTS_TOOLS` / `<PROVIDER>_REASONING`.

Reasoning models spend output tokens on hidden chain-of-thought, so the router reserves extra
output budget (`REASONING_TOKEN_RESERVE`) to stop a small `max_tokens` from yielding an empty reply.

## Protocol translation

Your app always speaks one format; the router adapts to whatever the chosen provider needs.

| Provider type | Wire format | How the router handles it |
|---|---|---|
| Most providers | OpenAI Chat Completions | Pass-through (the router's native format) |
| Anthropic | Messages API (`/v1/messages`) | Two-way translation incl. tools & streaming |
| Codex (ChatGPT) | **Responses API** over OAuth | Two-way translation + OAuth token lifecycle |

- **OpenAI ⇄ Anthropic** — `/v1/messages` is accepted for Anthropic-SDK apps, translated to
  OpenAI format, routed through the same pipeline, and translated back (including `tool_use` /
  `tool_result` blocks and streaming).
- **Codex (ChatGPT subscription)** — authenticates with OAuth, not an API key. Accounts are
  imported with `hr auth import-codex`; the router mints fresh access tokens from the refresh
  token, sends requests to the ChatGPT backend in Responses-API format, and translates the SSE
  stream back to OpenAI chunks. Multiple accounts pool naturally and pair with `sequential`
  rotation to ration them. See [Providers](/providers/#codex-chatgpt-subscription).

## Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /v1/chat/completions` | proxy key | OpenAI chat completions (streaming + tools) |
| `POST /v1/messages` | proxy key | Anthropic Messages API (translated) |
| `POST /v1/embeddings` | proxy key | OpenAI embeddings (stable provider order) |
| `GET /v1/models` | proxy key | Advertises the `hermes-router` model id |
| `GET /v1/status` | proxy key | Per-provider health, latency, keys, rotation, cache |
| `GET /health` | none | Liveness check for uptime monitors |
| `GET /metrics` | optional | Prometheus metrics (set `METRICS_REQUIRE_AUTH=1` to lock) |

## Observability

`hr status` renders a live dashboard (provider health, latency, key cooldowns, cache, rotation
mode) from `/v1/status`. `/metrics` exposes Prometheus counters and gauges for Grafana — counts
and timings only, never request content. See [Monitoring](/monitoring/).

## Design principles

- **Self-contained** — one Python file; keys live in your own `auth.json` (git-ignored, `0600`).
  Nothing is installed system-wide beyond the `hr` symlink.
- **Configured by environment** — every behavior is an env var with a sensible default; see
  [Configuration](/configuration/).
- **Fail soft** — when in doubt the router makes forward progress (e.g. if every provider's
  breaker is open it probes them all) rather than hard-failing while options remain.
