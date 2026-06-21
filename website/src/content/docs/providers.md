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

## Valid provider names

Use these names with `hr auth add`, `hr model set`, and the `<PROVIDER>_*` environment
variables:

`gemini`, `openrouter`, `sambanova`, `github_models`, `cerebras`, `groq`, `mistral`,
`cohere`, `zai`, `naga`, `nvidia`, `huggingface`, `kimi`, `openai`, `anthropic`, `codex`.

## Per-provider capabilities

Each provider's model is probed at startup for **function-calling** and **reasoning**
support; results show up in `hr status` and `/v1/status`. See
[usage.md](/usage/) for how those affect tool routing, and
[configuration.md](/configuration/) for the override variables.
