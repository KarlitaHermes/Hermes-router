# Changelog

## 0.1.0

Initial release — a control panel for hermes-router.

- Status-bar health indicator (providers available / total, rotation mode).
- Dashboard sidebar: live per-provider health, rating, latency, model(s), key cooldowns,
  cache hit-rate, and rotation mode (auto-refreshing).
- Commands: Restart, Doctor, Update, Add Provider Key, Import Codex login, Set Model(s),
  Set Rotation Mode.
- Works against a local or remote (`baseUrl`) router; control commands require a local `hr`.
