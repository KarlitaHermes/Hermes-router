# VS Code Extension

The **hermes-router** VS Code extension turns your editor into a control panel for the router
*and* lets you use the router's free provider pool as a model inside Copilot Chat. You never
have to leave VS Code to check provider health, add a key, or chat through hermes-router.

[![Visual Studio Marketplace](https://img.shields.io/visual-studio-marketplace/v/MohammedShafiq.hermes-router?label=VS%20Marketplace&logo=visualstudiocode)](https://marketplace.visualstudio.com/items?itemName=MohammedShafiq.hermes-router)

It does three things:

1. **Monitor** — a status-bar badge and a live dashboard showing every provider's health.
2. **Manage** — add keys, restart, set models/rotation, run the doctor, all from the palette.
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

Click the **hermes-router** icon in the activity bar (left edge) to open a live dashboard. It
shows, for every provider: up/down status and health rating, latency, the model(s) it's using,
and any key cooldowns — plus the overall cache hit-rate and the active key-rotation mode. It
refreshes on its own every few seconds.

This is the same information as `hr status` and the `/v1/status` endpoint — just always visible
in your editor.

---

## Managing the router

Open the Command Palette (`Ctrl/Cmd+Shift+P`) and type "hermes-router" to see every action (the
dashboard has buttons for them too):

| Command | What it does |
|---|---|
| **Open Dashboard** | Show the live provider table |
| **Restart Router** | Apply key/config changes (`hr restart`) |
| **Run Doctor (diagnose)** | Diagnose install/health problems (`hr doctor`) |
| **Update to Latest** | Upgrade the router (`hr update`) |
| **Add Provider Key** | Add a key for a provider — runs `hr auth add <provider>` in a terminal, where you paste the key (input hidden) |
| **Import Codex (ChatGPT) Login** | Bring in a ChatGPT-subscription login (`hr auth import-codex`) |
| **Set Provider Model(s)** | Set the model(s) for a provider — comma-separate several for per-model failover ([configuration.md](configuration.md)) |
| **Set Key Rotation Mode** | Switch between `round-robin` and `sequential` ([configuration.md](configuration.md)) |

> **Your keys stay private.** When you add a key, the extension opens a terminal that runs the
> `hr` command and *you* type the key there — the extension never reads or stores it.

> **Remote routers:** monitoring works against any `baseUrl` over HTTP. The *manage* commands
> use the local `hr` CLI, so they're disabled (with a notice) when `baseUrl` isn't localhost —
> manage a remote router on the machine that hosts it.

---

## Managing a router running in Docker

If your router runs in a **Docker container** (common on Windows), there's no `hr` on your host —
so by default the manage buttons can't do anything. Instead, point the extension at the container
and it will manage it *through Docker*.

**1. Run the `:cli` image with a volume.** The standard image is just the router; the **`:cli`**
variant also bundles the `hr` CLI, and the volume keeps your keys/settings across restarts:

```bash
docker run -d --name hermes-router -p 8319:8319 \
  -v hermes-data:/app/data -e PROXY_API_KEYS=sk-router-1 \
  shafiq735/hermes-router:cli
```

(On Windows PowerShell, put that on one line — see [deployment.md](deployment.md).)

**2. Tell the extension the container name.** In settings, set **`hermesRouter.dockerContainer`**
to `hermes-router` (and keep `baseUrl` = `http://localhost:8319`, `apiKey` = your `PROXY_API_KEYS`).

Now the manage buttons run against the container:

| Button | Runs |
|---|---|
| **Add Key** / **Import Codex** | a terminal with `docker exec -it <container> hr auth add …` — you type the key **inside the container** (the extension never sees it), then it `docker restart`s to apply |
| **Set Model** / **Rotation** | `docker exec <container> hr …` then `docker restart <container>` |
| **Restart** | `docker restart <container>` — *not* `hr restart` (that would stop the container) |

Requires the **`docker` CLI** on your PATH (Docker Desktop provides it). Because keys/settings
live on the `/app/data` volume, they survive `docker restart` and even recreating the container
(as long as you reuse the same volume).

> **Why a volume?** Without `-v …:/app/data`, anything you add with the buttons lives only inside
> that container and is lost the moment it's recreated.

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
- **"Add Key / Restart / …" says `hr` isn't on your PATH (or `spawn hr ENOENT`)** — those commands
  use the `hr` CLI, the **Linux/macOS/WSL** helper. It doesn't exist on a plain **Windows** host,
  and you don't use it when the **router runs in Docker**. Manage it to match how you run it:
  - **Docker:** either set `hermesRouter.dockerContainer` to your container name to manage it
    in-place (see "Managing a router running in Docker" above), or set keys as container env vars
    (`-e GEMINI_API_KEYS=…`) and apply with `docker restart <container>`. See
    [deployment.md](deployment.md).
  - **Windows without Docker:** run the router under **WSL2**, where `hr` works.
  - The dashboard and "use as a model" features work regardless.
- **The manage commands are greyed out for a remote router** — they use the local `hr` CLI, so they
  only work when `baseUrl` is localhost.

---

See also: [deployment.md](deployment.md) (run the router locally, in Docker, or on a Space) and
[monitoring.md](monitoring.md).
