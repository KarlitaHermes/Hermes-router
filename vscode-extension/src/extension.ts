import * as vscode from "vscode";
import { RouterClient } from "./client";
import { StatusBar } from "./statusBar";
import { DashboardProvider } from "./dashboard";
import { HermesChatModelProvider } from "./lmProvider";
import { runHr, runHrTerminal, isDocker } from "./cli";

const PROVIDERS = [
  "gemini", "openrouter", "sambanova", "github_models", "cerebras", "groq",
  "mistral", "cohere", "zai", "naga", "nvidia", "huggingface", "kimi",
  "openai", "anthropic",
];

// Providers whose model can be set via `hr model set`. Includes `local` (Ollama /
// LM Studio / llama.cpp), which is keyless so it isn't in the key-add list above.
const MODEL_PROVIDERS = [...PROVIDERS, "local"];

function makeClient(): RouterClient {
  const cfg = vscode.workspace.getConfiguration("hermesRouter");
  return new RouterClient(
    cfg.get<string>("baseUrl", "http://localhost:8319"),
    cfg.get<string>("apiKey", "sk-router-1")
  );
}

export function activate(context: vscode.ExtensionContext) {
  const out = vscode.window.createOutputChannel("hermes-router");
  const statusBar = new StatusBar();
  const dashboard = new DashboardProvider(makeClient);

  context.subscriptions.push(
    out,
    statusBar,
    vscode.window.registerWebviewViewProvider(DashboardProvider.viewType, dashboard),
    // Register hermes-router as a Language Model provider so it shows up in
    // Copilot Chat's model picker and any vscode.lm consumer can select it.
    vscode.lm.registerLanguageModelChatProvider(
      "hermes-router",
      new HermesChatModelProvider(makeClient)
    )
  );

  // ── Shared refresh: update the dashboard panel AND the status bar ────────────
  // Update the webview first and unconditionally — dashboard.refresh() always posts
  // a `status` or `error` message to it, so the panel can never get stuck on
  // "Loading…". The /health probe only feeds the status bar; a health blip must not
  // block the panel from rendering (that was the old bug).
  const refresh = async () => {
    const status = await dashboard.refresh();
    if (status) {
      statusBar.setHealthy(status);
      return;
    }
    // getStatus failed (unreachable or bad key). Fall back to /health so the status
    // bar can distinguish "router down" from "router up but /v1/status rejected".
    try {
      await makeClient().getHealth();
      statusBar.setUnknown();
    } catch (e: any) {
      statusBar.setUnreachable(e?.message || "no response");
    }
  };

  // ── Commands ─────────────────────────────────────────────────────────────────
  const reg = (id: string, fn: (...a: any[]) => any) =>
    context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  reg("hermesRouter.openDashboard", async () => {
    await vscode.commands.executeCommand("hermesRouter.dashboard.focus");
    await refresh();
  });
  // Open the full browser dashboard (served by the router at /dashboard). The
  // in-editor webview is a compact view; the web one has the live request log,
  // per-key usage, and richer charts.
  reg("hermesRouter.openWebDashboard", async () => {
    const url = makeClient().dashboardUrl();
    await vscode.env.openExternal(vscode.Uri.parse(url));
  });
  reg("hermesRouter.refresh", refresh);

  reg("hermesRouter.restart", async () => {
    await runHr(out, ["restart"]);
    await refresh();
  });
  reg("hermesRouter.doctor", () => runHr(out, ["doctor"]));
  reg("hermesRouter.update", async () => {
    if (isDocker()) {
      vscode.window.showInformationMessage(
        "To update a Docker router, pull a newer image and recreate the container — " +
          "e.g. `docker pull shafiq735/hermes-router:cli` then re-run it. `hr update` " +
          "doesn't apply inside a container."
      );
      return;
    }
    await runHr(out, ["update"]);
    await refresh();
  });

  reg("hermesRouter.authAdd", async () => {
    const provider = await vscode.window.showQuickPick(PROVIDERS, {
      placeHolder: "Provider to add a key for",
    });
    if (provider) runHrTerminal(["auth", "add", provider]);
  });
  reg("hermesRouter.importCodex", () => {
    if (isDocker()) {
      vscode.window.showInformationMessage(
        "Codex import reads your ChatGPT login (~/.codex) from this machine — it isn't inside " +
          "the container. Mount it when you run the container (`-v ~/.codex:/root/.codex`) and " +
          "then import, or import on the host."
      );
      return;
    }
    runHrTerminal(["auth", "import-codex"]);
  });

  reg("hermesRouter.setModel", async () => {
    const provider = await vscode.window.showQuickPick(MODEL_PROVIDERS, {
      placeHolder: "Provider to set model(s) for",
    });
    if (!provider) return;
    const model = await vscode.window.showInputBox({
      prompt: `Model(s) for ${provider} — comma-separate for multiple (rate-limit failover)`,
      placeHolder: "e.g. gemini-2.5-flash-lite,gemini-2.5-flash",
    });
    if (!model) return;
    await runHr(out, ["model", "set", provider, model]);
    await runHr(out, ["restart"]);
    await refresh();
  });

  // Toggle an optional add-on from the dashboard: `hr features enable|disable <name>`
  // then restart so it takes effect. Only flag add-ons reach here (the dashboard
  // renders config-driven ones as status-only).
  reg("hermesRouter.toggleFeature", async (name: string, enable: boolean) => {
    if (!name) return;
    const res = await runHr(out, ["features", enable ? "enable" : "disable", name]);
    if (!res.ok) {
      vscode.window.showWarningMessage(
        `Couldn't ${enable ? "enable" : "disable"} '${name}'. See the hermes-router output for details.`
      );
      await refresh();
      return;
    }
    await runHr(out, ["restart"]);
    await refresh();
    vscode.window.setStatusBarMessage(`hermes-router: ${name} ${enable ? "enabled" : "disabled"}`, 4000);
  });

  reg("hermesRouter.setMode", async () => {
    const mode = await vscode.window.showQuickPick(["round-robin", "sequential"], {
      placeHolder: "Key rotation mode",
    });
    if (!mode) return;
    await runHr(out, ["mode", mode]);
    await runHr(out, ["restart"]);
    await refresh();
  });

  // ── Polling ──────────────────────────────────────────────────────────────────
  let timer: NodeJS.Timeout | undefined;
  const startTimer = () => {
    if (timer) clearInterval(timer);
    const secs = vscode.workspace.getConfiguration("hermesRouter").get<number>("refreshSeconds", 10);
    timer = setInterval(refresh, Math.max(3, secs) * 1000);
  };
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("hermesRouter")) {
        startTimer();
        void refresh();
      }
    }),
    { dispose: () => timer && clearInterval(timer) }
  );

  startTimer();
  void refresh();
}

export function deactivate() {}
