# Configuration

All configuration is via environment variables (in `.env`) and the `auth.json` credential
store. Everything is optional with sensible defaults — the router runs out of the box once
it has at least one key.

## Where your keys live

`hr auth add` writes to **`auth.json`** — the router's own credential store, kept next to
the router. It's git-ignored, so real keys are never committed.

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
| `PROXY_API_KEYS` | `sk-router-1` | Comma-separated keys your app uses to authenticate |
| `ROUTER_AUTH_FILE` | `./auth.json` | Where keys are stored |
| `CACHE_TTL_SECONDS` | `300` | Response cache lifetime (`0` disables) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `METRICS_REQUIRE_AUTH` | `0` | Require the proxy key on `/metrics` (`1` to enable) |
| `REASONING_TOKEN_RESERVE` | `4096` | Extra output budget added for reasoning models so hidden chain-of-thought doesn't eat the answer (`0` disables) |

### Per-provider model

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Model override (set via `hr model set`) |
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
