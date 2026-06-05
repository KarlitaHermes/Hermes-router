# hermes-router

A lightweight OpenAI-compatible proxy that load-balances across multiple free AI providers and API keys — so your app stays online even when one provider hits a rate limit.

## The problem

Free AI tiers are great, but they rate-limit aggressively:
- Gemini: per-minute token limits
- OpenRouter: 50 requests/day per key
- Groq / Cerebras: requests-per-minute caps

When you hit a limit, your app returns errors. If you have multiple keys or providers, switching between them manually is painful.

## What hermes-router does

- **Key rotation** — cycle through all your keys for each provider before giving up
- **Provider cascade** — if one provider is fully exhausted, automatically fall through to the next
- **Thinking field stripping** — removes `reasoning_content` / `think` fields that Gemini adds but other providers reject, preventing 400 errors during fallback
- **Smart cooldowns** — rate-limited keys sit out temporarily instead of hammering the API
- **Drop-in compatible** — any OpenAI SDK client works with zero code changes

```
Your app  →  hermes-router  →  Gemini (key 1, 2, 3 ...)
                            →  OpenRouter (key 1, 2 ...)
                            →  Cerebras
                            →  Groq
```

## Quick start

```bash
git clone https://github.com/Shaf2665/hermes-router
cd hermes-router

pip install -r requirements.txt

cp .env.example .env
# edit .env and add your API keys

python router.py
```

The server starts on port `8319` by default.

## Configuration

All configuration is via `.env` (or real environment variables):

| Variable | Description | Default |
|---|---|---|
| `PROXY_API_KEYS` | Comma-separated keys clients use to authenticate with the router | `sk-router-1` |
| `PORT` | Port to listen on | `8319` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` | `INFO` |
| `GEMINI_API_KEYS` | Comma-separated Gemini API keys | — |
| `OPENROUTER_API_KEYS` | Comma-separated OpenRouter API keys | — |
| `CEREBRAS_API_KEY` | Cerebras API key | — |
| `GROQ_API_KEY` | Groq API key | — |
| `GEMINI_MODEL` | Gemini model to use | `gemini-2.5-flash-lite` |
| `OPENROUTER_MODEL` | OpenRouter model to use | `nvidia/nemotron-3-super-120b-a12b:free` |
| `CEREBRAS_MODEL` | Cerebras model to use | `gpt-oss-120b` |
| `GROQ_MODEL` | Groq model to use | `llama-3.1-8b-instant` |
| `ROUTER_MODEL_ID` | Model name advertised at `/v1/models` | `hermes-router` |

Any provider with no keys set is automatically skipped.

### Getting free API keys

| Provider | Free tier | Sign up |
|---|---|---|
| Gemini | Generous per-minute limits | [aistudio.google.com](https://aistudio.google.com) |
| OpenRouter | 50 req/day per key | [openrouter.ai](https://openrouter.ai) |
| Cerebras | Fast inference, free tier | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| Groq | Fast inference, free tier | [console.groq.com](https://console.groq.com) |

**Tip:** Create multiple Google / OpenRouter accounts to stack more free keys.

## Usage with any OpenAI SDK

Point your client at `http://localhost:8319/v1` with your `PROXY_API_KEYS` value:

**Python:**
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8319/v1",
    api_key="sk-my-router-key-1",
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
  -H "Authorization: Bearer sk-my-router-key-1" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-router",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Docker

```bash
cp .env.example .env
# fill in your keys

docker compose up -d
```

## API endpoints

| Endpoint | Auth | Description |
|---|---|---|
| `GET /health` | No | Health check — returns provider list |
| `GET /v1/models` | Yes | Lists available models |
| `POST /v1/chat/completions` | Yes | Main chat endpoint (streaming supported) |
| `GET /v1/status` | Yes | Shows key cooldown state per provider |

### Check provider status

```bash
curl http://localhost:8319/v1/status \
  -H "Authorization: Bearer sk-my-router-key-1"
```

Example response:
```json
{
  "gemini": [
    {"key_tail": "abc123", "status": "ready", "ready_in": 0},
    {"key_tail": "xyz789", "status": "cooling", "ready_in": 42}
  ],
  "groq": [
    {"key_tail": "def456", "status": "ready", "ready_in": 0}
  ]
}
```

## Run as a systemd service (Linux)

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

## How cascading works

```
Request received
  │
  ▼
Try Gemini key 1 ──429──► Try Gemini key 2 ──429──► All Gemini keys cooling
                                                              │
                                                              ▼
                                                    Try OpenRouter key 1 ──429──► ...
                                                              │ (all exhausted)
                                                              ▼
                                                         Try Cerebras
                                                              │ (400/exhausted)
                                                              ▼
                                                           Try Groq
                                                              │ (exhausted)
                                                              ▼
                                                         503 — all providers exhausted
```

- **429** → key goes into cooldown, try next key for same provider
- **400/401/403** → skip entire provider (bad credentials or unsupported payload)
- **413** → payload too large for this provider, cascade to next
- **5xx** → provider error, short cooldown then retry

## License

MIT
