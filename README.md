# hermes-router

![Hermes Router](hermes-router-banner.png)

**Keep your AI app online for free.** hermes-router sits between your app and a pool of
free AI providers (Gemini, OpenRouter, Groq, and more). When one provider hits its rate
limit, it automatically falls back to the next — so your app keeps working instead of
erroring out.

It speaks the **OpenAI API**, so any tool or library that already talks to OpenAI works
unchanged — just point it at hermes-router instead.

```
  Your app ──► hermes-router ──► Gemini → OpenRouter → Groq → … (tries each until one works)
 (OpenAI SDK)   localhost:8319
```

**Highlights:** automatic key rotation & failover · smart routing (sends each request to
the cheapest model that can handle it) · response caching · circuit breaker for unhealthy
providers · one structured `auth.json` for all your keys.

---

## Architecture

A single Python file (`router.py`) running a small Flask/Waitress server. One request
flows through it like this:

```
  ┌──────────┐   OpenAI-format request    ┌─────────────────────────────────────┐
  │ Your app │ ─────────────────────────► │            hermes-router            │
  └──────────┘   Bearer PROXY_API_KEYS    │                                     │
       ▲                                   │  1. Auth check (PROXY_API_KEYS)     │
       │                                   │  2. Cache lookup (exact match)      │
       │         OpenAI-format response    │  3. Rate the request (1–5)          │
       └────────────────────────────────► │  4. Order providers by fit + health │
                                           │  5. Try providers, rotate keys      │
                                           └───────────────┬─────────────────────┘
                                                           │ first one that succeeds
                                           ┌───────────────▼─────────────────────┐
                                           │ Gemini · OpenRouter · Groq · Mistral │
                                           │ Cohere · NVIDIA · … (11 providers)   │
                                           └──────────────────────────────────────┘
```

**The moving parts:**

- **Credential pool** — every provider can hold many keys (from `auth.json`, then `.env`).
  Keys are rotated round-robin; a key that gets rate-limited is put on a short cooldown and
  skipped until it recovers.
- **Smart routing** — each request is scored 1–5 for difficulty (by length and content, no
  extra API call), and each model is scored 1–5 for capability. The router picks the
  *cheapest* model that can still handle the request, and rotates among equally-good ones.
- **Failover** — if a provider errors or times out, the router cascades to the next one
  automatically, so a single failure never reaches your app.
- **Circuit breaker** — a provider that keeps failing is pulled out of rotation for a
  cooldown, then re-probed. Healthy providers are always preferred.
- **Response cache** — identical requests can be served from an in-memory cache (TTL-based),
  saving free-tier quota.

Everything is configured by environment variables (see [Commands](#commands)); keys live in
`auth.json`. Nothing is hidden or installed system-wide — `install.sh` only symlinks the
`hr` command onto your PATH.

---

## Setup

**Requirements:** Python 3.10+ and at least one free API key (see the table below).

### One-liner install

```bash
curl -fsSL https://raw.githubusercontent.com/Shaf2665/Hermes-router/main/get.sh | bash
```

This clones the repo to `~/.local/share/hermes-router`, creates a venv, installs
dependencies, and puts `hr` on your PATH — all in one step.

Then run the interactive setup wizard:

```bash
hr setup
```

It walks you through adding your first API key and starting the router.

### Manual install (if you already cloned)

```bash
git clone https://github.com/Shaf2665/Hermes-router.git
cd Hermes-router
./install.sh     # creates venv, installs deps, symlinks hr
hr setup         # interactive wizard: add a key + start the router
```

Check it's running:

```bash
curl http://localhost:8319/health
```

### Use it from your app

Point any OpenAI client at `http://localhost:8319/v1`, model `hermes-router`:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8319/v1", api_key="sk-router-1")
resp = client.chat.completions.create(
    model="hermes-router",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)
```

`api_key` is any value from `PROXY_API_KEYS` (default `sk-router-1`; set your own in `.env`).

### Where your keys live

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

### Free API keys

You only need one to start — add more to stay online longer. You can stack quota by
creating multiple keys per provider (and signing up with multiple Google/GitHub accounts).

**Free providers** — you only need one to start. Stack quota by adding multiple keys per provider.

| Provider | Free tier | Sign up |
|---|---|---|
| Gemini | Generous per-minute limits | [aistudio.google.com](https://aistudio.google.com) |
| OpenRouter | 50 requests/day per key | [openrouter.ai](https://openrouter.ai) |
| SambaNova | Free, fast Llama models | [cloud.sambanova.ai](https://cloud.sambanova.ai) |
| GitHub Models | Free with any GitHub account | [github.com/settings/tokens](https://github.com/settings/tokens) |
| Cerebras | Fast inference, free tier | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| Groq | Fast inference, free tier | [console.groq.com](https://console.groq.com) |
| Mistral | Free tier | [console.mistral.ai](https://console.mistral.ai) |
| Cohere | 1,000 calls/mo per key | [dashboard.cohere.com](https://dashboard.cohere.com) |
| Z.ai (GLM) | ~1k requests/day | [z.ai](https://z.ai) |
| Naga AI | 100 requests/day per key | [naga.ac](https://naga.ac) |
| NVIDIA NIM | 40 requests/min per key | [build.nvidia.com](https://build.nvidia.com) |

**Paid providers** — add your existing API key; the router handles everything else.

| Provider | Default model | API keys |
|---|---|---|
| OpenAI | `gpt-4o-mini` | [platform.openai.com](https://platform.openai.com/api-keys) |
| Anthropic | `claude-haiku-4-5` | [console.anthropic.com](https://console.anthropic.com) |

> Anthropic's API uses a different wire format from OpenAI. hermes-router translates
> automatically — your app sends the same OpenAI-format request regardless of which
> provider handles it.

---

## Commands

The `./install.sh` step puts `hr` (and the full name `hermes-router`) on your PATH.

| Command | What it does |
|---|---|
| `hr setup` | Interactive first-run wizard — add a key, start the router, verify it works |
| `hr auth add <provider>` | Add one or more API keys for a provider (prompts you, input hidden) |
| `hr auth list` | Show every provider and how many keys it has |
| `hr start` | Run the router (same as `python router.py`) |
| `hr status` | Live dashboard — per-provider health, latency, cache stats |
| `hr restart` | Restart the router so key/config changes take effect |
| `hr doctor` | Diagnose installation issues (Python, venv, keys, PATH, router health) |
| `hr update` | Update to the latest version (safe; auto-rolls-back on failure) |
| `hr version` | Show the installed version |
| `hr help` | Show all commands |

Valid provider names: `gemini`, `openrouter`, `sambanova`, `github_models`, `cerebras`,
`groq`, `mistral`, `cohere`, `zai`, `naga`, `nvidia`.

**Settings** live in `.env` (all optional — sensible defaults):

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8319` | Port to listen on |
| `PROXY_API_KEYS` | `sk-router-1` | Comma-separated keys your app uses to authenticate |
| `ROUTER_AUTH_FILE` | `./auth.json` | Where keys are stored |
| `CACHE_TTL_SECONDS` | `300` | Response cache lifetime (`0` disables) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Troubleshooting

**`All providers exhausted` / requests fail** — every provider is rate-limited or has no
keys. Run `hr auth list` to confirm keys are loaded, and `hr status` to see which are
cooling down. Add more keys: `hr auth add <provider>`.

**`401 Unauthorized`** — your app's API key isn't in `PROXY_API_KEYS`. Use a value that
matches (default `sk-router-1`), or set your own in `.env` and `hr restart`.

**A provider never gets used** — check `hr status`. If its circuit breaker is open it was
unhealthy and is cooling off; it'll be re-probed automatically. If it shows `no keys`, add
some with `hr auth add`.

**Keys not picked up after adding** — you must `hr restart` for new keys to load.

**Port already in use** — something else is on `8319`. Set `PORT=8320` in `.env` (and point
your app at the new port), then `hr restart`.

**Check it's alive** — `curl http://localhost:8319/health` should return `{"status":"ok",...}`.
For detail, `hr status` or watch the logs (`router.log`, or `journalctl -u hermes-router` if
you run it as a systemd service).

---

## License

MIT — see [LICENSE](LICENSE).
