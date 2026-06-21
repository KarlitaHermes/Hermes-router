# Changelog

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
