---
title: "Configuration"
description: "auth.json, every .env setting, model overrides, key rotation and advanced knobs."
---

All configuration is via environment variables (in `.env`) and the `auth.json` credential
store. Everything is optional with sensible defaults — the router runs out of the box once
it has at least one key.

## Where your keys live

`hr auth add` writes to **`auth.json`** — the router's own credential store, kept next to
the router. It's git-ignored, so real keys are never committed. Codex (ChatGPT
subscription) logins are stored separately under `codex_accounts` (via
`hr auth import-codex`); the router refreshes their OAuth access tokens automatically.

```json
{
  "providers": {
    "openrouter": ["sk-or-key1", "sk-or-key2"],
    "gemini": ["AIzaSy-key"]
  }
}
```

> Keys in `.env` (e.g. `OPENROUTER_API_KEYS=k1,k2`) still work too — the router reads
> `auth.json` first, then falls back to `.env`. Point at a different file with
> `ROUTER_AUTH_FILE=/path/to/auth.json`.

## Settings (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8319` | Port to listen on |
| `HOST` | `0.0.0.0` | Bind address. Set `127.0.0.1` to listen on localhost only (recommended on a shared/VPS host — reach it via localhost or an SSH tunnel). Keep `0.0.0.0` for Docker. |
| `PROXY_API_KEYS` | `sk-router-1` | Comma-separated keys your app uses to authenticate |
| `ROUTER_AUTH_FILE` | `./auth.json` | Where keys are stored |
| `CACHE_TTL_SECONDS` | `300` | Response cache lifetime (`0` disables). Entries are namespaced per API key, so different `PROXY_API_KEYS` never share a cached answer — safe for multi-tenant use |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `METRICS_REQUIRE_AUTH` | `0` | Require the proxy key on `/metrics` (`1` to enable) |
| `REASONING_TOKEN_RESERVE` | `4096` | Extra output budget added for reasoning models so hidden chain-of-thought doesn't eat the answer (`0` disables) |
| `ROTATION_MODE` | `round-robin` | How keys are picked within a provider (set via `hr mode`) — `round-robin` or `sequential` |

### Advanced settings

Sensible defaults — most users never touch these.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_REQUEST_BYTES` | `10485760` (10 MB) | Max request body size; larger requests get `413` (guards against memory exhaustion) |
| `WORKER_THREADS` | `16` | Waitress worker threads (concurrency). The HTTP connection pool scales with this |
| `CACHE_MAX_SIZE` | `100` | Max entries in the response cache (LRU eviction) |
| `FAST_ROUTE_THRESHOLD` | `0` | If >0, requests under this many tokens prefer low-latency providers first (`0` disables) |
| `ROUTER_MODEL_ID` | `hermes-router` | The model name clients send (the router maps it to each provider's real model) |
| `ROUTER_STATE_FILE` | `./router_state.json` | Where provider ratings/capabilities are cached between restarts (use `/tmp/...` on read-only hosts like HF Spaces) |
| `ROUTER_STATE_TTL_HOURS` | `24` | How long the cached probe state is trusted before re-probing (`0` = re-probe every start) |
| `BREAKER_WINDOW` | `8` | Recent outcomes the circuit breaker weighs per provider |
| `BREAKER_MIN_SAMPLES` | `4` | Minimum samples before the breaker can trip |
| `BREAKER_ERROR_RATE` | `0.5` | Health-failure fraction that trips the breaker |
| `BREAKER_COOLDOWN` | `60` | Seconds the breaker stays open before re-probing |

### Per-provider model

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Model override (set via `hr model set`) |
| `CODEX_MODEL` | `gpt-5.5` | Codex (ChatGPT subscription) model — see [providers.md](/providers/) |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model override (set via `hr model set`) |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Model override (set via `hr model set`) |
| `<PROVIDER>_MODEL` | *(varies)* | Same pattern applies to all providers |

### Per-provider embeddings

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | Embedding model (empty disables this provider for `/v1/embeddings`) |
| `<PROVIDER>_EMBED_MODEL` | *(gemini/mistral/cohere set)* | Same pattern for embeddings; set empty to disable |

### Per-provider capability overrides

The router auto-probes each provider at startup, but you can force the result:

| Variable | Default | Purpose |
|---|---|---|
| `<PROVIDER>_SUPPORTS_TOOLS` | *(auto-probed)* | Force tool-capability on/off (`1`/`0`) |
| `<PROVIDER>_REASONING` | *(auto-probed)* | Force reasoning-model on/off (`1`/`0`) |
| `<PROVIDER>_SKIP_TOKENS_OVER` | *(per provider)* | Skip this provider when an estimated request exceeds this many tokens (`0` = never) |
| `<PROVIDER>_MAX_OUTPUT_TOKENS` | *(per provider)* | Clamp `max_tokens` down to this provider's output ceiling (`0` = no clamp) |

## Model overrides

Each provider has a default model that works out of the box. Switch models without editing
files:

```bash
hr model list                              # see all providers and their active model
hr model set anthropic claude-sonnet-4-6   # upgrade Anthropic to Sonnet
hr model set openai gpt-4o                 # use full GPT-4o instead of mini
hr model set gemini gemini-2.5-pro         # switch Gemini to Pro
hr model reset anthropic                   # revert back to the default
hr restart                                 # apply changes
```

Overrides are stored as plain variables in `.env` (e.g. `ANTHROPIC_MODEL=claude-sonnet-4-6`)
and active overrides are highlighted in `hr model list`.

### Multiple models per provider

A provider can use **several models** — just give `<PROVIDER>_MODEL` a comma-separated list:

```bash
hr model set gemini gemini-2.5-flash-lite,gemini-2.5-flash,gemini-2.0-flash
hr restart
```

Free-tier rate limits are almost always **per-model**, so each model is its own quota
bucket. When the first model hits its limit (429), the router **fails over to the next model
on the same key** before cascading to the next provider — multiplying free throughput along a
new axis (keys × models × providers), with no extra signups. The first model in the list is
the **primary** (used for routing, rating, and status); list them in preference order
(cheapest/fastest first).

> **Keep a provider's models the same class.** Tool-calling and reasoning are detected on the
> primary model and applied to the whole provider, so list models that behave alike (e.g. the
> Gemini `flash` family). Don't mix a tool-capable chat model with one that can't.

## Key rotation mode

When a provider holds several keys (or several accounts), `ROTATION_MODE` decides how the
router picks among them:

```bash
hr mode                # show the current mode
hr mode round-robin    # default — spread requests evenly across all keys
hr mode sequential     # drain one key fully before moving to the next
hr restart             # apply the change
```

- **`round-robin`** (default) — every request goes to the next key in turn, so all keys
  share the load and deplete together. Best for spreading latency and load.
- **`sequential`** — one key is used until it hits its rate limit, then the router moves to
  the next, and so on. Later keys stay **untouched in reserve** — useful when you want to
  ration accounts after a quota reset instead of burning them all at once. Keys are drained
  in the order they appear in `auth.json`.

Either way, failover, per-key cooldowns, and the circuit breaker keep working — the mode
only changes *which ready key is preferred* next. The active mode shows in `hr status` and
at `/v1/status`.
