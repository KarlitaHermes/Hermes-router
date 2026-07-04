---
title: "Getting Started"
description: "What hermes-router is, the key terms, and your first message — written for total beginners."
---

New to AI and not sure what any of this means? Start here. This page explains what
hermes-router is, the handful of words you'll see everywhere, and how to send your very
first message — step by step.

## What is hermes-router, in one sentence?

It's a **free middleman** between your program and AI models. Your program asks it a
question; it quietly finds a free AI provider that's available and gets you an answer —
switching to another provider automatically if one is busy or rate-limited.

**An analogy:** imagine a phone operator with a stack of calling cards from different
networks. You ask to make a call; the operator tries one card, and if it's out of minutes,
instantly tries the next — you never get a busy signal. hermes-router is that operator, and
the "cards" are free API keys from providers like Google Gemini, Groq, and others.

## Why would I want it?

- **It's free.** It uses the free tiers of many AI providers.
- **It doesn't go down.** When one provider hits its limit, it falls back to another, so
  your app keeps working.
- **It's a drop-in.** If you already use code that talks to OpenAI or Anthropic, you change
  *one line* (the address) and it works.

## Words you'll keep seeing

You don't need to memorize these — skim them, and come back when one shows up. There's a
fuller list in **[concepts.md](/concepts/)**.

- **LLM** (Large Language Model) — the actual AI "brain" that reads text and writes a reply
  (e.g. GPT, Gemini, Claude, Llama).
- **API key** — a secret password that lets your program use a provider. You get these free
  from the providers (see **[providers.md](/providers/)**).
- **Provider** — a company that hosts LLMs you can call over the internet (Gemini, Groq…).
- **Token** — roughly ¾ of a word. AI usage and limits are measured in tokens.
- **Prompt** — the text you send to the AI.

## Step 1 — Install it

```bash
curl -fsSL https://raw.githubusercontent.com/Shaf2665/Hermes-router/main/get.sh | bash
```

This downloads hermes-router and adds an `hr` command to your terminal.

## Step 2 — Add your first free key

Run the friendly setup wizard:

```bash
hr setup
```

It will ask which provider you have a key for and walk you through it. Don't have one yet?
**Gemini** is the easiest and most generous — get a free key at
[aistudio.google.com](https://aistudio.google.com), then paste it when asked. (More options
in **[providers.md](/providers/)**.)

## Step 3 — Check it's running

```bash
curl http://localhost:8319/health
```

You should see `{"status":"ok",...}`. That means the router is up and listening.

> **Want it to stay up after a reboot?** On a server, run `hr service install` so the router
> starts on boot and restarts itself if it crashes (`hr setup` also offers this). See
> [Deployment → Keep it running](/deployment/#keep-it-running-survive-reboots).

## Step 4 — Send your first message

The router understands the same "language" as the popular OpenAI library, so any OpenAI
example works — you just point it at the router. Install the library and run this:

```bash
pip install openai
```

```python
from openai import OpenAI

# api_key here is the router's own password (default "sk-router-1"), NOT a provider key.
client = OpenAI(base_url="http://localhost:8319/v1", api_key="sk-router-1")

reply = client.chat.completions.create(
    model="hermes-router",
    messages=[{"role": "user", "content": "Explain what an AI agent is, simply."}],
)
print(reply.choices[0].message.content)
```

Run it — you just made your first AI call, for free, through hermes-router. 🎉

## Where to go next

**Next:** **[Core Concepts](/concepts/)** — a plain-language glossary of every term you'll meet.

Then keep following the guide in order (it's built to read top-to-bottom):
**[Routing Features](/routing/)** → how the router picks a provider for chat, tools, vision, and
embeddings, then **Set It Up** → [Deployment](/deployment/) · [Providers](/providers/) ·
[Configuration](/configuration/), then **Build With It** → [Usage](/usage/) · [Build an Agent](/build-an-agent/).
