# VS Code Extension

The **hermes-router** VS Code extension turns your editor into a control panel for the router
*and* lets you use the router's free provider pool as a model inside Copilot Chat. You never
have to leave VS Code to check provider health, add a key, or chat through hermes-router.

[![Visual Studio Marketplace](https://img.shields.io/visual-studio-marketplace/v/MohammedShafiq.hermes-router?label=VS%20Marketplace&logo=visualstudiocode)](https://marketplace.visualstudio.com/items?itemName=MohammedShafiq.hermes-router)

It does three things:

1. **Monitor** — a status-bar badge and a live in-editor panel showing every provider's health.
2. **Manage the basics** — restart, run the doctor, update, all from the palette. Everything else
   (API keys, provider models, add-ons, key rotation mode) is configured in the **web
   dashboard** (`/dashboard`), which the extension opens for you in one click — there's one place
   to configure the router, not two.
3. **Use as a model** — pick **hermes-router** in Copilot Chat and your prompts route through
   the free pool (text *and* tool calling, so it works in **agent mode**).

---

## Install

**Easiest:** open the **Extensions** view in VS Code (`Ctrl/Cmd+Shift+X`), search
**hermes-router**, and click **Install**.

Or from a terminal:

```bash
code --install-extension MohammedShafiq.hermes-router
```

Or install a `.vsix` by hand: download it from the
[GitHub releases](https://github.com/Shaf2665/Hermes-router/releases), then in VS Code run
**Extensions → ⋯ → Install from VSIX…**.

> **What you also need:** a hermes-router that's actually running — either locally
> (`hr setup`) or remotely (e.g. a [Hugging Face Space](deployment.md)). The extension is a
> *front-end*; it talks to a router, it isn't the router itself.

---

## First-time setup

After installing, tell the extension where your router is and how to authenticate. Open
**Settings** (`Ctrl/Cmd+,`), search "hermes-router", and set:

| Setting | Default | What to put |
|---|---|---|
| `hermesRouter.baseUrl` | `http://localhost:8319` | Your router's URL. For a remote router, use its full URL (e.g. your Space `https://you-hermes.hf.space`). |
| `hermesRouter.apiKey` | `sk-router-1` | Any value from your router's `PROXY_API_KEYS`. Used to read status and to chat. |
| `hermesRouter.hrPath` | `hr` | Path to the `hr` CLI, for the local *manage* actions. Usually leave as-is. |
| `hermesRouter.dockerContainer` | *(empty)* | Set to your container's name to manage a router running in **Docker** (see below). |
| `hermesRouter.refreshSeconds` | `10` | How often the dashboard and status bar refresh. |

If you run the router on your own machine with the defaults, you don't need to change
anything — it works out of the box.

---

## Monitoring

### Status bar

A small badge sits in the bottom status bar:

- `✓ hermes-router 11/12` — the router is up and 11 of 12 providers are available.
- It turns into a **warning** if the router is unreachable or down.

Click it to open the dashboard.

### Dashboard

Click the **hermes-router** icon in the activity bar (left edge) to open a live in-editor panel.
It shows, for every provider: up/down status and health rating, latency, the model it's
currently using, and any key cooldowns — plus the overall cache hit-rate and the active
key-rotation mode. It refreshes on its own every few seconds.

This panel is deliberately compact — an at-a-glance health check, not a config screen. Click
**⬈ Web dashboard** (in the panel or the palette) for the full picture: the live request log,
per-key usage, and every configuration action. See [monitoring.md](monitoring.md).

---

## Managing the router

Open the Command Palette (`Ctrl/Cmd+Shift+P`) and type "hermes-router" to see every action (the
in-editor panel has buttons for Refresh and Restart; the rest are palette-only):

| Command | What it does |
|---|---|
| **Open Dashboard** | Show the live provider table (in-editor panel) |
| **Open Web Dashboard (browser)** | Open the router's full browser dashboard at `/dashboard` — health, request log, per-key usage, and every config action |
| **Restart Router** | Apply config changes (`hr restart`) |
| **Run Doctor (diagnose)** | Diagnose install/health problems (`hr doctor`) |
| **Update to Latest** | Upgrade the router (`hr update`) |
| **Import Codex (ChatGPT) Login** | Bring in a ChatGPT-subscription login (`hr auth import-codex`) — the one config action that stays here, since it reads a local OAuth login file the web dashboard can't reach |

> **Adding keys, setting models, toggling add-ons, and changing key rotation mode** all live in
> the **web dashboard** now (open it with the button above) — see
> [monitoring.md → Web dashboard](monitoring.md#web-dashboard). This keeps configuration in one
> place instead of split between the extension and the browser.

> **Remote routers:** everything here — monitoring *and* the web dashboard — works against any
> `baseUrl` over HTTP, local or remote. Only **Restart / Doctor / Update / Import Codex** use the
> local `hr` CLI, so those stay disabled (with a notice) when `baseUrl` isn't localhost.

---

## Using the router in Docker

**Configuring** the router (add keys, set models, toggle add-ons) is done entirely through the
**web dashboard** now, and that works identically whether the router runs bare-metal or in
Docker — it's just HTTP to the router itself, no `hr` CLI needed inside the container. Point your
browser (or the extension's **Open Web Dashboard** button) at the container's mapped port, e.g.
`http://localhost:8319/`.

**Restarting** to apply a change is where Docker needs a little care, since it's an OS-level
operation on the container, not just an HTTP call:

- **Preferred: set `hermesRouter.dockerContainer`** to your container's name in the extension's
  settings. Its own **Restart Router** command then correctly runs `docker restart <container>`
  instead of `hr restart` (which would just kill the container's main process). This also makes
  **Doctor** and **Update** work via `docker exec` — see the `:cli` image setup below.
- **Or use the web dashboard's own "Restart Now" button.** This restarts the router process
  in-place. Inside a container where `router.py` is the main process, that process exiting stops
  the *container* — it only comes back on its own if the container has a restart policy. The
  provided `docker-compose.yml` already sets `restart: unless-stopped`, so Compose users are
  covered automatically. A bare `docker run` with no restart flag would need a manual
  `docker start <container>` afterward — add `--restart unless-stopped` to avoid that.

**1. Run the `:cli` image with a volume** — the standard image is just the router; the **`:cli`**
variant also bundles the `hr` CLI (for the extension's Restart/Doctor/Update/Import-Codex via
`docker exec`), and the volume keeps your keys/settings across restarts:

```bash
docker run -d --name hermes-router -p 8319:8319 --restart unless-stopped \
  -v hermes-data:/app/data -e PROXY_API_KEYS=sk-router-1 \
  shafiq735/hermes-router:cli
```

**2. Set `hermesRouter.dockerContainer`** to `hermes-router` in the extension's settings (keep
`baseUrl` = `http://localhost:8319`).

Codex import (the one config action that stays in the extension, since it reads a local `~/.codex`
OAuth login the web dashboard can't reach) needs `-v ~/.codex:/root/.codex` mounted too — see
[Providers](providers.md#codex-chatgpt-subscription).

---

## Use hermes-router as an AI model (Copilot Chat)

This is the headline feature. The extension registers **hermes-router** as a language model in
VS Code, so you can chat through your free provider pool right inside Copilot.

1. Make sure the **GitHub Copilot Chat** extension is installed and you're on **VS Code ≥ 1.104**.
2. Open the Chat view, click the **model picker** (the model name near the input box).
3. Choose **hermes-router**.

Now every prompt is answered by whichever free provider the router picks — no per-token bill.
Replies **stream** in just like any built-in model.

### Agent mode (tool calling)

hermes-router supports **tool calling**, so it works in Copilot **agent mode**: it can run
terminal commands, edit files, and call MCP tools to complete a task. The router automatically
sends tool-using requests only to providers whose models support function calling, so tools
"just work" without you choosing a specific provider.

> **It's also available to other extensions.** Anything that uses the VS Code `vscode.lm` API
> can select the hermes-router model too — not just Copilot Chat.

---

## Troubleshooting

- **Status bar says the router is down / "unreachable"** — the extension can't reach `baseUrl`.
  Confirm the router is running (`curl <baseUrl>/health`) and that `hermesRouter.baseUrl` points
  at it. For a remote router, include the full `https://…` URL.
- **`401` / dashboard is empty** — `hermesRouter.apiKey` must be one of the router's
  `PROXY_API_KEYS`. Make them match.
- **hermes-router doesn't appear in the Copilot model picker** — you need **VS Code ≥ 1.104**
  *and* the **GitHub Copilot Chat** extension. Reload the window after installing both.
- **"Restart / Doctor / Update" says `hr` isn't on your PATH (or `spawn hr ENOENT`)** — those
  commands use the `hr` CLI, the **Linux/macOS/WSL** helper. It doesn't exist on a plain
  **Windows** host or inside a container that doesn't bundle it:
  - **Docker:** set `hermesRouter.dockerContainer` to your container's name so these commands run
    via `docker exec`/`docker restart` instead (see "Using the router in Docker" above) — or just
    use the web dashboard's own Restart button, which needs no `hr` at all (works as long as your
    container has a restart policy, e.g. `--restart unless-stopped`).
  - **Windows without Docker:** run the router under **WSL2**, where `hr` works.
  - Monitoring, the web dashboard, and "use as a model" all work regardless — only these three
    commands need `hr` (or `docker`) reachable.
- **Restart / Doctor / Update are greyed out for a remote router** — they use the local `hr`
  CLI, so they only work when `baseUrl` is localhost. Everything else (monitoring, the web
  dashboard) works against any remote router over HTTP.

---

See also: [deployment.md](deployment.md) (run the router locally, in Docker, or on a Space) and
[monitoring.md](monitoring.md).
