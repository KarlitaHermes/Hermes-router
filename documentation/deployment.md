# Deployment & Platform Support

Where can you run hermes-router, and how? Short answer: **anywhere Python runs** — Linux,
macOS, Windows, Docker, or a cloud box like a Hugging Face Space.

## Platform support at a glance

hermes-router has two parts:

- **The router itself (`router.py`)** — a plain Python web server (Flask + waitress). It is
  **fully cross-platform**: Linux, macOS, and **Windows** all work natively. Every
  dependency (`flask`, `requests`, `waitress`, `tiktoken`) ships prebuilt Windows wheels,
  and waitress is a production WSGI server that runs great on Windows.
- **The `hr` command-line tool** — a set of **bash** scripts that use Unix tools
  (`systemctl`, `nohup`, …). These run on Linux and macOS, but **not** in native Windows
  `cmd`/PowerShell.

So the engine runs everywhere; only the convenience CLI is Unix-shell-based.

## Windows

Pick whichever fits you:

| Option | `hr` CLI? | Notes |
|---|---|---|
| **Docker Desktop** *(recommended)* | n/a | Turnkey, identical to every other platform. See [Docker](#docker) below. |
| **WSL2** (Ubuntu) | ✅ full | Install the Linux way inside WSL; behaves exactly like Linux. |
| **Git Bash** | ⚠️ mostly | The bash scripts run; `hr restart` uses its `nohup` fallback (no systemd). |
| **Native Python** | ❌ | Run the server directly (below); manage config by hand. |

### Native Python on Windows (no `hr`)

```powershell
git clone https://github.com/Shaf2665/Hermes-router.git
cd Hermes-router
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# set at least one provider key + your proxy key (PowerShell):
$env:GEMINI_API_KEYS = "your-key"
$env:PROXY_API_KEYS  = "sk-router-1"
python router.py
```

The router comes up on `http://localhost:8319`. Everything `hr auth`/`hr model` would do is
just environment variables (see [configuration.md](configuration.md)) — set them in your
shell, a `.env` file, or System Environment Variables. To manage keys without the CLI, edit
`auth.json` directly:

```json
{ "providers": { "gemini": ["key1"], "openrouter": ["key2"] } }
```

## Docker

The repo ships a `Dockerfile` and `docker-compose.yml`. This is the simplest way to run on
**any** OS (including Windows/macOS via Docker Desktop):

```bash
docker compose up -d        # builds and runs on :8319
```

Pass keys via environment (compose reads your `.env`), or mount an `auth.json`. The image
exposes `8319`; map it to whatever host port you like.

## Hugging Face Space

You can host hermes-router as a **Docker** Space (not Gradio/Streamlit — it's a Flask
server, not a Gradio app). The one thing that trips people up is the **port**.

**1. Make it a Docker Space and line up the port.** HF serves your app on a single port set
by `app_port` (default **7860**), but the router listens on **8319**. Match them — either
set `app_port` in your Space `README.md` header:

```yaml
---
title: Hermes Router
sdk: docker
app_port: 8319
---
```

…or add a Space variable `PORT=7860` so the router listens where HF expects. Either way the
public URL `https://<user>-<space>.hf.space` will reach the router.

**2. Put keys in Secrets, not `auth.json`.** A Space's filesystem is ephemeral and the
runtime user can't reliably write to the app dir, so `auth.json` won't persist. Set provider
keys and your proxy key as **Settings → Secrets** (environment-variable form):

```
GEMINI_API_KEYS      = ...
OPENROUTER_API_KEYS  = ...
PROXY_API_KEYS       = <a strong secret you choose>
ROUTER_STATE_FILE    = /tmp/router_state.json     # writable path for the ratings cache
```

**3. 🔒 Lock it down.** A Space URL is **public** — anyone who finds it could spend your
quota. Set `PROXY_API_KEYS` to a strong value (never leave it as the default `sk-router-1`).

**4. Heads-up on free Spaces:** they sleep when idle, so the first request after a nap is
slow and may time out — have your client retry.

**Connect your app** to the Space:

```python
client = OpenAI(base_url="https://<user>-<space>.hf.space/v1",
                api_key="<your PROXY_API_KEYS>")
```

## Running as a service (Linux)

On Linux, `hr setup` can install a systemd unit so the router starts on boot and restarts on
failure; `hr restart` then manages it. Without systemd, `hr restart` falls back to a
background `nohup` process automatically.
