---
title: "Usage"
description: "Call the router from the OpenAI SDK or Anthropic SDK, with tool use, embeddings and reasoning models."
---

hermes-router speaks **both the OpenAI API and the Anthropic API**. Point any client
that already talks to either at the router and it works unchanged.

`api_key` is any value from `PROXY_API_KEYS` (default `sk-router-1`; set your own in
`.env` — see [configuration.md](/configuration/)).

## OpenAI SDK

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

Streaming (`stream=True`) and function calling (`tools=[...]`) both work.

> **Tip — multiply your free quota:** give a provider several models with a comma-separated
> `<PROVIDER>_MODEL` (e.g. `GEMINI_MODEL=gemini-2.5-flash-lite,gemini-2.5-flash`). Since
> rate limits are per-model, the router fails over across a provider's models before moving
> on — capacity scales with keys × **models** × providers. See
> [Configuration](/configuration/#multiple-models-per-provider).

## Anthropic SDK

Already built on the Anthropic SDK? Point its `base_url` at hermes-router — no code
changes. The router accepts Anthropic's `/v1/messages` format (and the `x-api-key`
header), translates it, and routes across **all** your free providers:

```python
import anthropic

client = anthropic.Anthropic(api_key="sk-router-1", base_url="http://localhost:8319")
msg = client.messages.create(
    model="claude-3-5-sonnet-20241022",   # model name is ignored — the router picks
    max_tokens=100,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(msg.content[0].text)
```

Streaming (`client.messages.stream(...)`) works too.

> The `model` you pass is **ignored** — hermes-router routes to the cheapest capable free
> provider, so an Anthropic-SDK app transparently gets the same multi-provider failover.
> (Use the `openai`/`anthropic` paid providers if you specifically want those models.)

### Tool use

Anthropic `tools`, `tool_use`, and `tool_result` are translated to/from OpenAI function
calling in both streaming and non-streaming mode — full round-trips work:

```python
tools = [{
    "name": "get_weather",
    "description": "Get the current weather for a city",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}]
msg = client.messages.create(
    model="claude-3-5-sonnet-20241022", max_tokens=300, tools=tools,
    messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
)
# msg.stop_reason == "tool_use", with a tool_use block ready to run
```

When a request carries tools, the router **automatically routes only to providers whose
model supports function calling** (detected at startup), so a request never lands on a
model that would silently ignore the tools. Override detection per provider with
`<PROVIDER>_SUPPORTS_TOOLS=1` / `=0` (see [configuration.md](/configuration/)).

## Embeddings

The router also speaks the OpenAI **embeddings** API, backed by free providers (Gemini,
Mistral, Cohere):

```python
resp = client.embeddings.create(model="hermes-router", input="hello world")
print(len(resp.data[0].embedding))   # e.g. 3072 from Gemini
```

Unlike chat, embeddings use a **stable provider** (not round-robin): vectors from
different providers have different dimensions and can't be mixed in one store, so the
router keeps hitting the same provider and only fails over if it goes down. For a strict
single-dimension guarantee, disable the others' embed models (e.g. `MISTRAL_EMBED_MODEL=`
and `COHERE_EMBED_MODEL=` empty in `.env`).

## Reasoning models

Some models (e.g. gpt-oss, Nemotron, GLM-4.5) spend output tokens on hidden
chain-of-thought before answering. The router detects these at startup and reserves extra
output budget for them, so a small `max_tokens` never yields an empty reply. Tune with
`REASONING_TOKEN_RESERVE` (see [configuration.md](/configuration/)).

---

**Next:** [Build an Agent](/build-an-agent/) — go from a chatbot to a memory-backed, tool-using agent, copy-paste.
