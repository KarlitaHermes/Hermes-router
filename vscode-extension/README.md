# hermes-router — VS Code extension

A control panel for [hermes-router](https://github.com/Shaf2665/Hermes-router) inside VS Code:
**monitor** your provider pool and **manage** the router without leaving the editor.

## Features

- **Status bar** — at-a-glance health: `✓ hermes-router N/total` providers available (turns
  red/warns when the router is down or unreachable). Click to open the dashboard.
- **Dashboard** (activity-bar sidebar) — live table of every provider: up/down, rating,
  latency, model(s), and key cooldowns, plus cache hit-rate and the active key-rotation mode.
  Auto-refreshes.
- **Manage** (command palette or dashboard buttons):
  - **Restart**, **Run Doctor**, **Update**
  - **Add Provider Key** — opens a terminal running `hr auth add <provider>` (your key is typed
    hidden; the extension never handles it)
  - **Import Codex (ChatGPT) Login** — `hr auth import-codex`
  - **Set Provider Model(s)** — comma-separate for multi-model rate-limit failover
  - **Set Key Rotation Mode** — `round-robin` / `sequential`

## Requirements

A running hermes-router (locally, or remote e.g. a Hugging Face Space) and — for the *manage*
commands — the `hr` CLI on your PATH. See the
[hermes-router docs](https://hermes-router.vercel.app).

## Settings

| Setting | Default | Description |
|---|---|---|
| `hermesRouter.baseUrl` | `http://localhost:8319` | Router URL. Use your Space URL for a remote router. |
| `hermesRouter.apiKey` | `sk-router-1` | A value from `PROXY_API_KEYS` — used to read `/v1/status`. |
| `hermesRouter.hrPath` | `hr` | Path to the `hr` CLI (for local control actions). |
| `hermesRouter.refreshSeconds` | `10` | Dashboard / status-bar refresh interval. |

> **Remote routers:** Monitoring works over HTTP against any `baseUrl`. The control commands
> use the local `hr` CLI, so they're disabled (with a notice) when `baseUrl` is not localhost —
> manage a remote router where it's hosted.

## Install

Grab the `.vsix` and run **Extensions → … → Install from VSIX**, or:

```bash
code --install-extension hermes-router-0.1.0.vsix
```
