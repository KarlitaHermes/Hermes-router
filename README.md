# hermes-router

![Hermes Router](hermes-router-banner.png)

**Keep your AI app online for free.** hermes-router sits between your app and a bunch of
free AI providers (Gemini, OpenRouter, Groq, and more). When one provider hits its rate
limit, it automatically tries the next one — so your app keeps working instead of erroring out.

It speaks the **OpenAI API**, so any tool or library that talks to OpenAI works with it
unchanged. You just point your app at hermes-router instead of at OpenAI.

---

## Who is this for?

- You're building something with AI and don't want to pay for an API yet.
- You keep hitting "rate limit exceeded" errors on free tiers.
- You have a few free API keys and want them used automatically, without writing
  switch-over logic yourself.

If that's you, this is a single Python file you run once and forget about.

---

## How it works (the 30-second version)

```
                    ┌─────────────────────────────────────────┐
   Your app  ─────► │             hermes-router               │
 (OpenAI SDK,       │                                         │
  curl, etc.)       │   Try Gemini      (key 1 → key 2 → …)  │
                    │   then OpenRouter (key 1 → key 2 → …)  │
                    │   then SambaNova                        │
                    │   then GitHub Models                    │
                    │   then Cerebras                         │
                    │   then Groq                             │
                    │   then Mistral                          │
                    │   then Cohere                           │
                    │   then Z.ai (GLM)                       │
                    │   then Naga (Nemotron Super)            │
                    │   then NVIDIA NIM (DeepSeek V4 Flash)  │
                    └─────────────────────────────────────────┘
```

When a provider is rate-limited or exhausted, hermes-router moves down the list
automatically. The first one that answers wins. Your app never sees the failures.

> The order above is the *fallback* order — but hermes-router doesn't blindly start
> at the top every time. It first sizes up your request and picks the best-fit
> provider for it (a cheap model for an easy question, a powerful one for a hard
> task). See **[How it picks a provider](#how-it-picks-a-provider-smart-routing)** below.

**Extra niceties:**

- **Smart routing** — sizes up each request and matches it to the right model: cheap
  models for simple questions, powerful ones for hard tasks. No overkill, no under-power.
- **Round-robin load spreading** — when several providers are equally good for a request,
  it rotates between them instead of always hitting the same one, so no single free tier
  burns out first.
- **Key rotation** — uses every key you give it for a provider before moving on.
- **Smart cooldowns** — a rate-limited key sits out for a while instead of being hammered.
- **Connection reuse** — keeps connections to providers open (HTTP keep-alive), so it
  doesn't pay a fresh ~100–300 ms handshake on every single request.
- **Response cache** — repeated identical questions return instantly without spending quota.
- **Large-payload skip** — providers that reject big requests (like Groq's free tier) are
  skipped automatically when your prompt is too long, instead of wasting a failed attempt.
- **Thinking-field cleanup** — strips `reasoning_content` / `think` fields that some models
  add but others reject, which would otherwise cause errors when falling back.
- **Built-in monitoring** — see latency, error rates, and cache hits at `/v1/status`.

---

## How it picks a provider (smart routing)

This is the part that makes hermes-router more than a dumb fallback list. You don't
have to understand it to use the router — but here's what's happening under the hood.

### Step 1: every model gets a capability score (1–5)

Lower number = more capable model.

| Score | Meaning | Example models |
|:---:|---|---|
| **1** | Outstanding | GPT-4o, Claude Opus, Gemini Pro |
| **2** | Best | Llama-70B, Mistral Large, Nemotron Super, DeepSeek V4 |
| **3** | Good | Gemini Flash, GPT-4o-mini, Mistral Small |
| **4** | Fair | Cohere R7B, Llama-8B |
| **5** | Basic | tiny <1B models |

You don't set these by hand — the router knows ratings for common models and guesses
sensibly for the rest (e.g. anything with `70b` in the name → score 2).

### Step 2: every request gets a difficulty score (1–5)

No AI call is used for this — it's a fast keyword + length check.

| Difficulty | What triggers it |
|:---:|---|
| **1** (critical) | very long prompt, or code + words like "implement / debug / refactor" |
| **2** (complex) | long prompt, or "design / architect / optimize" |
| **3** (standard) | medium prompt, or contains a code block |
| **4** (simple) | short prompt |
| **5** (trivial) | tiny factual question — "what is X", "translate Y" |

### Step 3: match the request to the cheapest model that can handle it

The rule is simple: **use the weakest model that's still good enough.** A capable model
is wasted (and slower) on "what's 2+2", and a weak model fails a hard coding task.

```
Easy question  ("what is Python?")   →  a score-4 model answers it   (fast, cheap)
Standard task                        →  a score-3 model              (Gemini Flash, Mistral)
Hard coding / long context           →  a score-2 model              (Llama-70B, DeepSeek V4)
```

Providers that *can* handle the request are tried first (weakest-capable first); more
powerful providers sit behind them as backup; models too weak for the task are the very
last resort. If the chosen provider is rate-limited, the cascade takes over from there.

When several providers are an equally good fit (same capability score), the router
**rotates between them request by request** — so if you have, say, four free providers all
good enough for a task, the load spreads evenly instead of draining one provider's quota
first. The moment one is rate-limited, it's skipped and the next equal one steps in.

### Bonus: fast routing for snappy chats

For very short requests (set `FAST_ROUTE_THRESHOLD`, e.g. `200` tokens), low-latency
providers (Groq, Cerebras, SambaNova, Mistral) jump the queue when two providers are
otherwise equally good — shaving a few hundred milliseconds off quick back-and-forth turns.

### Bonus: health-aware routing & the circuit breaker

The router also watches how each provider has been *behaving lately* and reacts so a
flaky provider doesn't slow you down:

- **Health-aware routing** — every provider keeps a short rolling record of its recent
  outcomes (network errors and `5xx` server errors count against it; rate-limits and
  bad-request errors don't, since those aren't the provider's fault). A provider that's
  been failing a lot quietly **sinks** within its group, so healthy providers get tried
  first. This only kicks in once there's enough evidence — a brand-new or quiet provider
  is treated as healthy, and when *everyone* is healthy the ordering (including the
  round-robin above) is exactly as it was. Capability matching always wins: a healthy but
  weaker model never jumps ahead of the right model for the job.

- **Circuit breaker** — if a provider crosses the failure threshold (by default, at least
  4 recent outcomes with ≥ 50% of them failing), its "circuit" **opens**: the router skips
  it entirely for a cooldown (~60s) instead of wasting round-trips on it. After the
  cooldown it's *probed* again (half-open) — one success closes the circuit and gives it a
  clean slate. Safety net: if *every* provider's circuit is open at once, the router probes
  them all rather than hard-failing, so you always get an answer while options remain.

Both features reuse the existing per-provider tracking — no new dependencies — and are
tunable via the `BREAKER_*` env knobs (see [Optional settings](#optional-settings-sensible-defaults--change-only-if-you-want-to)).
Current breaker state per provider shows up at `/v1/status` under each provider's
`breaker` field.

---

## What you'll need

1. **Python 3.10 or newer** — check with `python3 --version`.
2. **At least one free API key** from any provider in the table below. More is better —
   the whole point is to spread load across them.

---

## Quick start

```bash
# 1. Get the code
git clone https://github.com/Shaf2665/hermes-router
cd hermes-router

# 2. Install the two dependencies (Flask + requests)
pip install -r requirements.txt

# 3. Create your config file and add your API keys
cp .env.example .env
nano .env          # paste in at least one provider's key

# 4. Start it
python router.py
```

You'll see something like:

```
hermes-router starting on :8319
Providers: ['gemini', 'groq']
Cache: enabled (TTL=300s, max=100)
```

That's it — hermes-router is now listening on **http://localhost:8319**.

### Check that it's working

In another terminal:

```bash
curl http://localhost:8319/health
```

You should get back `{"status": "ok", "providers": [...]}`. If you see your providers
listed, you're ready to go.

---

## The `hr` command

hermes-router ships with a small command-line tool for managing your router — adding
keys, checking health, restarting, and updating — without editing files or memorising
`curl` incantations. Install it once:

```bash
./install.sh
```

This adds two commands to your PATH that point at the same tool: **`hermes-router`** and
the shorthand **`hr`**. Use whichever you like — every example below works with both.

> Don't want to install anything? Each command also runs straight from the clone as a
> script — e.g. `./auth.sh list`, `./status.sh`, `./restart.sh`, `./update.sh`.

### All commands at a glance

| Command | What it does |
|---|---|
| `hr auth add <provider>` | Add one or more API keys for a provider (prompts you, input hidden) |
| `hr auth list` | Show every provider and how many keys it has configured |
| `hr status` | Live health dashboard — rating, health, keys, and latency per provider |
| `hr start` | Run the router (same as `python router.py`) |
| `hr restart` | Restart the router so `.env`/key changes take effect |
| `hr update` | Pull the latest version and restart safely (auto-rollback on failure) |
| `hr update --check` | Tell you if an update is available — changes nothing |
| `hr version` | Show the installed version |
| `hr help` | Show the command list |

The natural lifecycle: **configure** (`auth`) → **run** (`start` / `restart`) →
**watch** (`status`) → **maintain** (`update`).

### Managing API keys — `hr auth`

Add keys interactively instead of hand-editing `.env`. Your input is hidden as you type,
and keys are appended with the exact numbering the router expects (`GROQ_API_KEY`,
`GROQ_API_KEY_2`, `GROQ_API_KEY_3`, …) so they all join the credential pool automatically.

```bash
hr auth add groq          # prompts for a key, then offers to add more
hr auth list              # see what's configured
hr restart                # apply the new keys
```

Valid provider names are the ones the router ships with:
`gemini`, `openrouter`, `cerebras`, `sambanova`, `github_models`, `mistral`, `groq`,
`cohere`, `naga`, `nvidia`.

### Watching health — `hr status`

A glanceable dashboard of the running router. Providers are sorted best-rated first;
unhealthy ones and any tripped circuit breakers are highlighted.

```bash
hr status                 # the dashboard
hr status --json          # raw JSON (handy for scripts)
```

```
  hermes-router — localhost:8319

  Provider        Rating  Health                 Keys             Latency
  ─────────────── ─────── ────────────────────── ──────────────── ─────────
  github_models   1       ✅ ok                   1 ready          1820ms
  groq            2       ✅ ok                   2 ready          126ms
  nvidia          2       ⨂ open (probes in 38s)  4 (1 cooling)    —
  gemini          3       ✅ ok                   6 ready          834ms

  cache: on · hit-rate 0.0 · 0/200 entries
  breaker: trips at 50% fails over last 8 · opens 60s
```

- **Health** — `✅ ok`, `⚠ degraded` (erroring lately), `⚠ unavailable`, or
  `⨂ open` (circuit breaker tripped — the provider is being skipped and will be
  re-probed when the countdown hits zero).
- **Keys** — how many are in the pool, and how many are temporarily cooling after a
  rate-limit.

### Restarting — `hr restart`

Restarts the router so changes to `.env` (e.g. after `hr auth add`) take effect. It
restarts your systemd service if you have one, otherwise it stops the running process
and relaunches it in the background (logging to `router.log`), then health-checks it.

```bash
hr restart
```

---

## Getting free API keys

You only need one to start, but add as many as you can — that's what keeps you online.

| Provider | Free tier | Sign up |
|---|---|---|
| Gemini | Generous per-minute limits | [aistudio.google.com](https://aistudio.google.com) |
| OpenRouter | 50 requests/day per key | [openrouter.ai](https://openrouter.ai) |
| SambaNova | Free, fast Llama models | [cloud.sambanova.ai](https://cloud.sambanova.ai) |
| GitHub Models | Free with any GitHub account | [github.com/settings/tokens](https://github.com/settings/tokens) |
| Cerebras | Fast inference, free tier | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| Groq | Fast inference, free tier | [console.groq.com](https://console.groq.com) |
| Mistral | Free tier (mistral-small-latest) | [console.mistral.ai](https://console.mistral.ai) |
| Cohere | Free trial (1,000 calls/mo per key) | [dashboard.cohere.com](https://dashboard.cohere.com) |
| Z.ai (GLM) | Free (glm-4.5-flash, ~1k req/day) | [z.ai](https://z.ai) |
| Naga AI | Free (Nemotron-3-Super-120B, 100 req/day) | [naga.ac](https://naga.ac) |
| NVIDIA NIM | Free (77+ models, 40 req/min per key) | [build.nvidia.com](https://build.nvidia.com) |

**Tip:** Most providers let you create more than one key, and you can sign up with
multiple Google / GitHub accounts to stack even more free quota. Add them all as
comma-separated values (see below).

---

## Using it from your app

Point any OpenAI client at `http://localhost:8319/v1` and use the model name
`hermes-router`. Use one of your `PROXY_API_KEYS` values as the API key.

**Python:**
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8319/v1",
    api_key="sk-router-1",          # one of your PROXY_API_KEYS
)

response = client.chat.completions.create(
    model="hermes-router",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

**curl:**
```bash
curl http://localhost:8319/v1/chat/completions \
  -H "Authorization: Bearer sk-router-1" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-router",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

Streaming (`"stream": true`) works too.

---

## Works with any agent framework

hermes-router speaks the OpenAI API, so it drops into any framework that supports a custom
`base_url` — no code changes beyond the two lines below.

**LangChain**
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8319/v1",
    api_key="sk-router-1",
    model="hermes-router",
)
```

**LlamaIndex**
```python
from llama_index.llms.openai import OpenAI

llm = OpenAI(
    api_base="http://localhost:8319/v1",
    api_key="sk-router-1",
    model="hermes-router",
)
```

**CrewAI**
```python
from crewai import LLM

llm = LLM(
    model="openai/hermes-router",
    base_url="http://localhost:8319/v1",
    api_key="sk-router-1",
)
```

**AutoGen**
```python
config_list = [{
    "model": "hermes-router",
    "api_key": "sk-router-1",
    "base_url": "http://localhost:8319/v1",
}]
```

**Hermes Agent** (native)
```yaml
# config.yaml
custom_providers:
  - name: my-router
    base_url: http://localhost:8319/v1
    api_key_env: PROXY_API_KEY
model:
  default: custom:my-router
```

Any other framework with an `openai_api_base` / `base_url` setting works the same way.

---

## Configuration

Everything is set in the `.env` file (or as real environment variables). You only need
the keys for the providers you actually use — anything left blank is skipped automatically.

### API keys (add the ones you have)

| Variable | Description |
|---|---|
| `GEMINI_API_KEYS` | Gemini keys (see multi-key formats below) |
| `OPENROUTER_API_KEYS` | OpenRouter keys |
| `SAMBANOVA_API_KEY` | SambaNova key |
| `GITHUB_MODELS_TOKEN` | GitHub Models token |
| `CEREBRAS_API_KEY` | Cerebras key |
| `GROQ_API_KEY` | Groq key |
| `MISTRAL_API_KEY` | Mistral key |
| `COHERE_API_KEY` | Cohere key |
| `GLM_API_KEY` | Z.ai / GLM key |
| `NAGA_API_KEY` | Naga AI key |
| `NVIDIA_API_KEY` | NVIDIA NIM key |

**Three ways to give a provider multiple keys (all work, all combine automatically):**

```bash
# 1. Comma-separated (canonical)
GEMINI_API_KEYS=key1,key2,key3

# 2. Numbered suffixes
GROQ_API_KEY=key1
GROQ_API_KEY_2=key2
GROQ_API_KEY_3=key3

# 3. Mix both — they merge and de-duplicate
MISTRAL_API_KEY=key1
MISTRAL_API_KEY_2=key2
MISTRAL_API_KEYS=key3,key4
```

The router round-robins through all keys for a provider before cascading to the next one.

### Optional settings (sensible defaults — change only if you want to)

| Variable | What it does | Default |
|---|---|---|
| `PROXY_API_KEYS` | The key(s) your app uses to talk to hermes-router | `sk-router-1` |
| `PORT` | Port to listen on | `8319` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, or `WARNING` | `INFO` |
| `GEMINI_MODEL` | Which Gemini model to use | `gemini-2.5-flash-lite` |
| `OPENROUTER_MODEL` | Which OpenRouter model to use | `nvidia/nemotron-3-super-120b-a12b:free` |
| `SAMBANOVA_MODEL` | Which SambaNova model to use | `Meta-Llama-3.3-70B-Instruct` |
| `GITHUB_MODELS_MODEL` | Which GitHub model to use | `gpt-4o-mini` |
| `CEREBRAS_MODEL` | Which Cerebras model to use | `gpt-oss-120b` |
| `GROQ_MODEL` | Which Groq model to use | `llama-3.1-8b-instant` |
| `MISTRAL_MODEL` | Which Mistral model to use | `mistral-small-latest` |
| `COHERE_MODEL` | Which Cohere model to use | `command-r7b-12-2024` |
| `ZAI_MODEL` | Which Z.ai (GLM) model to use | `glm-4.5-flash` |
| `NAGA_MODEL` | Which Naga model to use | `nemotron-3-super-120b-a12b:free` |
| `NVIDIA_MODEL` | Which NVIDIA NIM model to use | `deepseek-ai/deepseek-v4-flash` |
| `ROUTER_MODEL_ID` | The model name your app sends | `hermes-router` |
| `CACHE_TTL_SECONDS` | Cache identical answers for N seconds (`0` = off) | `300` |
| `CACHE_MAX_SIZE` | How many answers to keep cached | `100` |
| `FAST_ROUTE_THRESHOLD` | Requests shorter than this (estimated tokens) prefer low-latency providers (Groq, Cerebras, SambaNova, Mistral) when ratings tie (`0` = off). Try `200` for snappier chat. | `0` |
| `ROUTER_STATE_TTL_HOURS` | Reuse saved provider ratings for N hours instead of re-probing (and spending quota) on every restart (`0` = always re-probe) | `24` |
| `BREAKER_WINDOW` | How many recent outcomes the circuit breaker weighs per provider | `8` |
| `BREAKER_MIN_SAMPLES` | Minimum recent outcomes before a breaker can trip | `4` |
| `BREAKER_ERROR_RATE` | Trip the breaker when this fraction of the window are health failures | `0.5` |
| `BREAKER_COOLDOWN` | Seconds a tripped breaker stays open before the provider is probed again | `60` |
| `MAX_REQUEST_BYTES` | Largest request body accepted | `10485760` (10 MB) |
| `WORKER_THREADS` | Server worker threads | `16` |
| `GROQ_SKIP_TOKENS_OVER` | Skip Groq when a request is bigger than this (it would be rejected anyway). Set `0` to disable, or raise it if you're on a paid Groq tier. | `5500` |

> Any provider can have its own skip ceiling with `{PROVIDER}_SKIP_TOKENS_OVER`,
> e.g. `CEREBRAS_SKIP_TOKENS_OVER=30000`.

> **Note on the cache:** cached answers are shared across *all* clients of your
> router (every `PROXY_API_KEYS` holder). That's perfect for personal use, but if
> you expose one router to multiple untrusted users, set `CACHE_TTL_SECONDS=0` so
> one user can never receive a response cached from another.

---

## Running it 24/7 (Linux systemd service)

So it starts on boot and restarts if it ever crashes:

```bash
sudo nano /etc/systemd/system/hermes-router.service
```

```ini
[Unit]
Description=hermes-router AI load balancer
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/hermes-router/router.py
WorkingDirectory=/path/to/hermes-router
EnvironmentFile=/path/to/hermes-router/.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-router
```

(Replace `/path/to/hermes-router` with the real folder path.)

---

## Running with Docker

```bash
cp .env.example .env
# fill in your keys
docker compose up -d
```

---

## Keeping it up to date

This project gets frequent improvements (new providers, better default models,
performance fixes). Once you've installed [the `hr` command](#the-hr-command), updating
is a single familiar command from anywhere:

```bash
hr update            # check + update + restart if there's a new version
hr update --check    # just tell me if an update is available (changes nothing)
```

No install? The same updater runs straight from your clone:

```bash
./update.sh
./update.sh --check
```

**Either way, it's built so an update can't break your setup:**

- It **never touches your `.env` or `router_state.json`** — your keys and runtime
  state are left exactly as they are.
- It **validates the new code before restarting anything.**
- If the download, dependency install, or the post-restart health check fails, it
  **automatically rolls back** to the exact version you were on and restarts that —
  so you're never left worse off than before you ran it.

If you run hermes-router as a systemd service named something other than
`hermes-router`, tell the updater (and `hr restart`):

```bash
HERMES_ROUTER_SERVICE=my-router hr update
```

> Prefer to do it by hand? `git pull` then restart your router — your `.env` is
> gitignored, so a pull never overwrites your keys. The command just adds the
> validate-and-rollback safety net on top.

---

## API endpoints

| Endpoint | Needs auth? | What it's for |
|---|---|---|
| `GET /health` | No | Quick "is it up?" check — returns the provider list |
| `GET /v1/models` | Yes | Lists the model name your app should use |
| `POST /v1/chat/completions` | Yes | The main chat endpoint (streaming supported) |
| `GET /v1/status` | Yes | Live view of every key, provider stats, and cache metrics |

### Checking status

The friendly way is [`hr status`](#watching-health--hr-status) (a formatted dashboard).
To get the raw JSON — for monitoring or scripts — hit the endpoint directly:

```bash
curl http://localhost:8319/v1/status \
  -H "Authorization: Bearer sk-router-1"
```

Example response:

```json
{
  "providers": {
    "gemini": {
      "keys": [
        {"key_tail": "abc123", "status": "ready",   "ready_in": 0},
        {"key_tail": "xyz789", "status": "cooling", "ready_in": 42}
      ],
      "stats": {"avg_latency_ms": 850, "error_rate": 0.0, "total_requests": 42}
    },
    "groq": {
      "keys": [{"key_tail": "def456", "status": "ready", "ready_in": 0}],
      "stats": {"avg_latency_ms": 210, "error_rate": 0.05, "total_requests": 18},
      "skip_if_tokens_over": 5500
    }
  },
  "cache": {"enabled": true, "ttl_s": 300, "size": 12, "max_size": 100,
            "hits": 8, "misses": 30, "hit_rate": 0.211},
  "fast_routing": {"enabled": false, "threshold_tokens": 0,
                   "fast_providers": ["cerebras", "groq", "sambanova"]}
}
```

- `status: ready` — key is good to use right now.
- `status: cooling` — key was rate-limited; `ready_in` is seconds until it's usable again.

---

## What happens on each request (the cascade)

```
Request received
  │
  ▼
Try Gemini key 1 ──429──► Try Gemini key 2 ──429──► All Gemini keys cooling
                                                              │
                                                              ▼
                                                    Try OpenRouter key 1 ──429──► …
                                                              │ (all exhausted)
                                                              ▼
                                                         Try Cerebras
                                                              │ (exhausted)
                                                              ▼
                                                           Try Groq
                                                              │ (exhausted)
                                                              ▼
                                                         Try Mistral
                                                              │ (exhausted)
                                                              ▼
                                                         Try Cohere
                                                              │ (exhausted)
                                                              ▼
                                                       Try Z.ai (GLM)
                                                              │ (exhausted)
                                                              ▼
                                                          Try Naga
                                                              │ (exhausted)
                                                              ▼
                                                       Try NVIDIA NIM
                                                              │ (exhausted)
                                                              ▼
                                                 503 — all providers exhausted
```

How different errors are handled:

- **429 (rate limited)** → that key cools down, try the next key for the same provider.
- **400 / 401 / 403** → skip the whole provider (bad key or unsupported request).
- **413 (too big)** → request too large for this provider, move to the next one.
- **5xx (provider error)** → brief cooldown, then retry.

---

## Troubleshooting

**`503 — all providers exhausted`**
All your keys are rate-limited or invalid. Check `/v1/status` — if everything shows
`cooling`, just wait, or add more keys. If a provider shows repeated errors, double-check
that key is valid.

**`401 unauthorized` from hermes-router itself**
The `Authorization` header your app sends must match one of your `PROXY_API_KEYS`. They're
two different things: provider keys go in `.env`; the key your *app* uses is `PROXY_API_KEYS`.

**A provider is always being skipped**
Check `/v1/status` for a `skip_if_tokens_over` value — your prompts may be larger than that
provider's limit. Raise the limit (e.g. `GROQ_SKIP_TOKENS_OVER=0` to disable) if you're on
a paid tier.

**Nothing happens / connection refused**
Make sure `python router.py` is still running and you're using the right port (default 8319).

---

## Words you might not know

New to this? Here's the jargon, in plain English:

- **API key** — a password that lets your app use a provider's AI. Free providers give
  you one when you sign up.
- **Rate limit** — a cap on how many requests you can make in a window (e.g. "30 per
  minute"). Hit it and the provider replies with an error (`429`) instead of an answer.
- **Cascade / fallback** — when one provider says no, automatically trying the next one.
- **Cooldown** — after a key gets rate-limited, the router rests it for a bit before
  reusing it, so it isn't hammered while it's blocked.
- **Token** — roughly ¾ of a word. Both your prompt and the reply are measured in tokens;
  limits and prompt sizes are usually counted this way.
- **Proxy** — a middleman. Your app talks to hermes-router, and hermes-router talks to the
  real providers on your behalf.
- **OpenAI-compatible** — speaks the same request/response format as OpenAI's API, so
  existing tools work by only changing the URL.

---

## License

[MIT](LICENSE) — free to use, modify, and distribute.
