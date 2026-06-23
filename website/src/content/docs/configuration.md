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
| `CACHE_PERSIST` | `0` | If `1`, mirror the cache to a SQLite file so it survives restarts (opt-in). The DB mirrors the in-memory LRU, so it stays bounded by `CACHE_MAX_SIZE` — raise that to persist more |
| `CACHE_DB_PATH` | `./cache.db` | SQLite file for the persistent cache. On read-only hosts (e.g. HF Spaces) point it at `/tmp/cache.db` |
| `SEMANTIC_CACHE` | `0` | If `1`, also serve cached answers for *similar* prompts (needs an embedding provider; falls back to exact match otherwise) |
| `SEMANTIC_CACHE_THRESHOLD` | `0.95` | Cosine-similarity cutoff for a semantic hit (`1.0` = identical; lower = looser matching) |
| `FAST_ROUTE_THRESHOLD` | `0` | If >0, requests under this many tokens prefer low-latency providers first (`0` disables) |
| `ROUTER_MODEL_ID` | `hermes-router` | The model name clients send (the router maps it to each provider's real model) |
| `ROUTER_STATE_FILE` | `./router_state.json` | Where provider ratings/capabilities are cached between restarts (use `/tmp/...` on read-only hosts like HF Spaces) |
| `ROUTER_STATE_TTL_HOURS` | `24` | How long the cached probe state is trusted before re-probing (`0` = re-probe every start) |
| `BREAKER_WINDOW` | `8` | Recent outcomes the circuit breaker weighs per provider |
| `BREAKER_MIN_SAMPLES` | `4` | Minimum samples before the breaker can trip |
| `BREAKER_ERROR_RATE` | `0.5` | Health-failure fraction that trips the breaker |
| `BREAKER_COOLDOWN` | `60` | Seconds the breaker stays open before re-probing |

### Per-key budgets & rate limits

Give each `PROXY_API_KEYS` entry a ceiling so the router is safe to share with a team. These
env vars are **global defaults**; set per-key overrides in `auth.json` with `hr limit set`.
`0` = unlimited (the default — no enforcement). Live usage shows in `/v1/status` and `hr status`.

| Variable | Default | Purpose |
|---|---|---|
| `PROXY_LIMIT_RPM` | `0` | Requests/minute per key (rolling 60s window) |
| `PROXY_LIMIT_REQ_DAY` | `0` | Requests per UTC day, per key |
| `PROXY_LIMIT_TOKENS_DAY` | `0` | Tokens per UTC day, per key |

```bash
hr limit set sk-team-1 --rpm 60 --req-day 500 --tokens-day 100000   # per-key, written to auth.json
hr limit list                                                       # show all
hr restart                                                          # apply
```

Exceeding a limit returns `429` with a clear message and a `Retry-After` header. Per-key limits
in `auth.json` look like:

```json
{ "proxy_keys": { "sk-team-1": { "rpm": 60, "req_per_day": 500, "tokens_per_day": 100000 } } }
```

### Local model (Ollama / LM Studio / llama.cpp)

Set either of the first two to enable a `local` provider pointing at a model on your own
machine. It's keyless (cloud providers remain the fallback). See
[Providers → Local models](/providers/#local-models-ollama--lm-studio--llamacpp).

| Variable | Default | Purpose |
|---|---|---|
| `LOCAL_BASE_URL` | `http://localhost:11434/v1` | Your local server's OpenAI-compatible endpoint (LM Studio: `:1234/v1`) |
| `LOCAL_MODEL` | `llama3.1` | Local model id (comma-separate for multi-model failover) |
| `LOCAL_API_KEY` | `local` | Only if your local server actually requires a key |
| `LOCAL_EMBED_MODEL` | *(unset)* | Optional — also serve `/v1/embeddings` from the local server |

> Send model `hermes-router:fast` (or header `X-Hermes-Profile: fast`) to prefer the local model
> for short/casual turns, with cloud fallback for heavier requests.

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
new axis (keys × models × providers), with no extra signups. Each model is **also a first-class
routing candidate**, scored on its own rating and capability — so the router can pick the right
model in the list for each request (e.g. a stronger model for a hard or tool-using turn), not just
fall over to it. Within equal ratings, the **listed order** is preserved, so list them in
preference order (cheapest/fastest first).

> **Mixing model classes is fine.** Tool-calling and reasoning are detected **per model** at
> startup, so you can safely list models of different classes (e.g.
> `gemini-2.5-flash-lite,gemini-2.5-pro`) — each is routed and gated on its own capability. Force a
> result per model with `<PROVIDER>_<MODEL>_SUPPORTS_TOOLS` / `_REASONING` (model id upper-cased,
> non-alphanumerics → `_`, e.g. `GEMINI_GEMINI_2_5_PRO_SUPPORTS_TOOLS=1`); the provider-wide
> `<PROVIDER>_SUPPORTS_TOOLS` / `_REASONING` still applies as the default for all its models.

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
