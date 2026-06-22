# Changelog

## 0.5.0

- **Usage in the dashboard.** The dashboard now shows a **Tokens** column per provider, total
  tokens served, semantic-cache hits, and (when configured) per-key rate-limit/budget usage —
  all read from the router's `/v1/status`. Pairs with the router's new local-model provider,
  per-key budgets, semantic caching, and `/v1/usage` endpoint.

## 0.4.0

- **Manage a router running in Docker.** New `hermesRouter.dockerContainer` setting — set it to
  your container's name and the control actions run against the container instead of the host:
  **Add Key / Import Codex** open a terminal running `docker exec -it <container> hr …` (you type
  the key inside the container, then it `docker restart`s to apply); **Set Model / Rotation** run
  `docker exec <container> hr …` then restart; **Restart** runs `docker restart <container>`
  (never `hr restart`, which would kill the container's main process).
- Requires the new **`:cli`** image variant (e.g. `shafiq735/hermes-router:cli`) run with a
  mounted volume (`-v hermes-data:/app/data`) so keys/model/rotation persist across restarts.
- **Update** and **Import Codex** show Docker-specific guidance instead of running (you update a
  container by pulling a new image; the Codex login lives on your machine, not the container).

## 0.3.1

- **Friendlier control errors when `hr` isn't installed.** The Restart / Add Key / Model /
  Rotation commands shell out to the `hr` CLI, which only exists on Linux/macOS/WSL — not on a
  Windows host or when the router runs in Docker. Previously these failed with a cryptic
  `spawn hr ENOENT` / "term 'hr' is not recognized". The extension now detects a missing `hr`
  and shows clear, Docker-aware guidance (set keys via `-e <PROVIDER>_API_KEYS=…`, use
  `docker restart`) with a link to the docs. Monitoring is unaffected and keeps working.

## 0.3.0

- **Agent-mode tool calling.** The hermes-router model now supports tool/function calling, so it
  works in **Copilot agent mode** (run commands, edit files, call MCP tools). Tool definitions and
  results are translated both ways; the router routes tool requests only to tool-capable providers.

## 0.2.0

- **Use hermes-router as an AI model.** Registers a Language Model provider, so hermes-router
  appears in **Copilot Chat's model picker** (and is usable by any `vscode.lm` consumer);
  prompts route through the router's free pool with streamed replies.
- Requires VS Code ≥ 1.104. v1 is text chat; agent-mode tool-calling is planned.

## 0.1.0

Initial release — a control panel for hermes-router.

- Status-bar health indicator (providers available / total, rotation mode).
- Dashboard sidebar: live per-provider health, rating, latency, model(s), key cooldowns,
  cache hit-rate, and rotation mode (auto-refreshing).
- Commands: Restart, Doctor, Update, Add Provider Key, Import Codex login, Set Model(s),
  Set Rotation Mode.
- Works against a local or remote (`baseUrl`) router; control commands require a local `hr`.
