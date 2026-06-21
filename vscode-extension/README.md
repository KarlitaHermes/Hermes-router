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

## Use it as an AI model (Copilot Chat)

The extension registers **hermes-router** as a language model in VS Code. Open **Copilot Chat**,
click the **model picker**, and choose **hermes-router** — your prompts now route through the
router's free pool. It's also available to any extension via the `vscode.lm` API.

> Requires **VS Code ≥ 1.104** and the **GitHub Copilot Chat** extension (for the chat UI +
> model picker). Supports streamed text **and tool calling**, so it works in Copilot **agent
> mode** (run commands, edit files, call MCP tools) — the router automatically routes
> tool-using requests to tool-capable providers.

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

[![Visual Studio Marketplace](https://img.shields.io/visual-studio-marketplace/v/MohammedShafiq.hermes-router?label=VS%20Marketplace)](https://marketplace.visualstudio.com/items?itemName=MohammedShafiq.hermes-router)

**One-click:** search **hermes-router** in the VS Code Extensions view and click Install, or:

```bash
code --install-extension MohammedShafiq.hermes-router
```

Or grab a `.vsix` from the [releases](https://github.com/Shaf2665/Hermes-router/releases) and
run **Extensions → … → Install from VSIX**.
