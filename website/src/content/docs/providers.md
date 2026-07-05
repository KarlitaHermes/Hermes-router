---
title: "Providers"
description: "Every free & paid provider, sign-up links, capabilities, plus Codex (ChatGPT subscription)."
---

hermes-router routes across a pool of providers. You only need **one** key to start —
add more (and more providers) to stay online longer. You can stack quota by creating
multiple keys per provider, and by signing up with multiple Google/GitHub accounts.

Add keys with `hr auth add <provider>` (see [configuration.md](/configuration/) for where
they're stored).

## Free providers

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
| Hugging Face | ~$0.10/mo credit (PRO: $2/mo) — 45k+ models | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

> **Hugging Face note:** one token reaches 45,000+ models across many inference partners
> via an OpenAI-compatible endpoint. The free credit is small, so it's best as an *extra* in
> the pool (the router fails over to other providers when it runs out). The default model
> uses the `:cheapest` suffix to stretch the credit; change it with `HUGGINGFACE_MODEL`.

## Paid providers

Add your existing API key; the router handles everything else.

| Provider | Default model | API keys |
|---|---|---|
| OpenAI | `gpt-4o-mini` | [platform.openai.com](https://platform.openai.com/api-keys) |
| Anthropic | `claude-haiku-4-5` | [console.anthropic.com](https://console.anthropic.com) |

> Anthropic's API uses a different wire format from OpenAI. hermes-router translates
> automatically — your app sends the same OpenAI-format request regardless of which
> provider handles it.

## Codex (ChatGPT subscription)

Codex lets you use your **ChatGPT subscription** (Plus/Pro/Go) for completions instead of a
pay-per-token API key. It doesn't use an API key — it authenticates with OAuth tokens, so
setup is different:

```bash
codex login            # one-time, with the official Codex CLI (opens browser / device flow)
hr auth import-codex    # copy the login into the router (reads ~/.codex/auth.json)
hr restart
```

The router stores the account under `codex_accounts` in `auth.json`, **refreshes the access
token automatically** before it expires, and translates your OpenAI-format requests to the
Codex **Responses API** transparently. Add several accounts (run `hr auth import-codex` after
logging into each) and pair with `hr mode sequential` to drain one account's quota before the
next. Override the model with `CODEX_MODEL` (default `gpt-5.5`).

> ⚠️ **Terms of service:** routing ChatGPT *subscription* quota through a proxy is a gray
> area in OpenAI's terms and could risk your account. Use your own accounts, at your own
> discretion.

## Kimi (Moonshot coding plan)

The **Kimi coding plan** (Moonshot) is a subscription, but — unlike Codex — it authenticates
with a normal **API key** (`sk-...`), not OAuth. Its endpoint is OpenAI-compatible, so it adds
like any other provider:

```bash
hr auth add kimi        # paste your Kimi/Moonshot key
hr restart
```

Defaults to `https://api.kimi.com/coding/v1` with model `kimi-for-coding`. Using the standard
Moonshot API instead of the coding plan? Point it elsewhere with `KIMI_BASE_URL`
(e.g. `https://api.moonshot.ai/v1`) and set `KIMI_MODEL` to a model like `kimi-k2-0905-preview`.
Get a key at [platform.kimi.ai](https://platform.kimi.ai) / [platform.moonshot.ai](https://platform.moonshot.ai).

## OpenCode (Zen + Go)

[OpenCode](https://opencode.ai) Zen is an OpenAI-compatible gateway of coding-tuned models —
including a rotating pool of **genuinely free** ones. It's a normal API-key provider (no OAuth):
sign in at [opencode.ai](https://opencode.ai), copy your key from **API Keys**, then:

```bash
hr auth add opencode
hr restart
```

The default routes to free models (`deepseek-v4-flash-free`, `minimax-m3-free`,
`qwen3.6-plus-free`). Free promotions rotate — when one ends OpenCode returns a model error and
the router automatically **skips it and fails over** to the next, so you stay online. Reach the
premium models (Claude, GPT, Gemini, GLM, Kimi, Qwen…) by setting `OPENCODE_MODEL`.

**OpenCode Go** is OpenCode's low-cost subscription tier (**$5 first month, then $10/mo**) —
the *same* API key against a different endpoint, no separate auth. Enable Go billing on
opencode.ai, then add it as its own provider so it's only used once you've subscribed:

```bash
hr auth add opencode_go      # paste the same OpenCode key
hr restart
```

> **Only do this after you've actually enabled Go billing.** Adding an `opencode_go` key is the
> router's *only* signal that you've subscribed — it doesn't verify it. A key added without Go
> billing enabled will fail on every request with an auth error (the router backs off after
> repeated failures instead of retrying forever, but it will never succeed). If you haven't
> subscribed, skip this section — OpenCode Zen above already covers the free tier.

Defaults to `https://opencode.ai/zen/go/v1` with `deepseek-v4-flash,minimax-m3`; override with
`OPENCODE_GO_MODEL`. (Go models: Kimi K2.7/K2.6, GLM-5.2/5.1, MiniMax M3/M2.7, Qwen3.7, DeepSeek
V4 Pro/Flash, MiMo…)

## Local models (Ollama / LM Studio / llama.cpp)

Run a model on your **own machine** and route to it — free, private, and fast, with the cloud
providers as automatic fallback. Any OpenAI-compatible local server works (Ollama, LM Studio,
llama.cpp's server, vLLM…). It's **keyless**, so there's nothing to add with `hr auth add` —
just point the router at it:

```bash
# e.g. with Ollama:  ollama serve  &&  ollama pull llama3.1
hr model set local llama3.1     # writes LOCAL_MODEL; enables the local provider
hr restart
```

Or set it directly in `.env`:

```
LOCAL_BASE_URL=http://localhost:11434/v1     # Ollama default (LM Studio: http://localhost:1234/v1)
LOCAL_MODEL=llama3.1                          # comma-separate for multi-model failover
# LOCAL_EMBED_MODEL=nomic-embed-text          # optional: also serve /v1/embeddings locally
```

The provider turns on as soon as `LOCAL_BASE_URL` or `LOCAL_MODEL` is set.

**Conversation mode** — send the model id **`hermes-router:fast`** (or the header
`X-Hermes-Profile: fast`) and the router prefers your local model for short/casual turns,
falling back to the cloud pool for heavier requests. Plain `hermes-router` keeps the normal
smart routing across every provider.

## Valid provider names

Use these names with `hr auth add`, `hr model set`, and the `<PROVIDER>_*` environment
variables:

`gemini`, `openrouter`, `sambanova`, `github_models`, `cerebras`, `groq`, `mistral`,
`cohere`, `zai`, `naga`, `nvidia`, `huggingface`, `kimi`, `opencode`, `opencode_go`, `openai`,
`anthropic`, `codex`, `local`.

## Per-provider capabilities

Each provider's model is probed at startup for **function-calling** and **reasoning**
support; results show up in `hr status` and `/v1/status`. See
[usage.md](/usage/) for how those affect tool routing, and
[configuration.md](/configuration/) for the override variables.

---

**Next:** [Configuration](/configuration/) — tune models, per-key budgets, caching, and every other setting.
