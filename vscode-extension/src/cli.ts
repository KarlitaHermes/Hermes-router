import * as vscode from "vscode";
import { execFile } from "child_process";

function hrPath(): string {
  return vscode.workspace.getConfiguration("hermesRouter").get<string>("hrPath", "hr");
}

/** True when the configured router is local (so the `hr` CLI can control it). */
export function isLocal(): boolean {
  const base = vscode.workspace.getConfiguration("hermesRouter").get<string>("baseUrl", "");
  return /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:|\/|$)/.test(base);
}

const REMOTE_NOTE =
  "hr controls are available only when the router runs locally. " +
  "Set hermesRouter.baseUrl to a localhost URL, or manage the remote router where it's hosted.";

const DOCS_URL = "https://hermes-router.vercel.app/vscode-extension/";

/** Resolve true if the `hr` binary can actually be executed on this machine. */
function hrAvailable(): Promise<boolean> {
  return new Promise((resolve) => {
    execFile(hrPath(), ["version"], { timeout: 8000 }, (err: any) => {
      // ENOENT = not on PATH (Windows host, or router runs in Docker). Any other
      // outcome means the binary ran (even if `version` itself errored).
      resolve(!(err && err.code === "ENOENT"));
    });
  });
}

/** Explain that hr is missing and how to manage the router without it. */
function notifyNoHr(): void {
  void vscode.window
    .showWarningMessage(
      "The `hr` CLI isn't on your PATH, so this control can't run — it's the Linux/macOS/WSL " +
        "helper for a local install. Running the router in Docker? Set keys with " +
        "`-e <PROVIDER>_API_KEYS=…` (or a mounted auth.json) and use `docker restart` instead. " +
        "Monitoring (the dashboard) keeps working regardless.",
      "Open docs"
    )
    .then((pick) => {
      if (pick === "Open docs") void vscode.env.openExternal(vscode.Uri.parse(DOCS_URL));
    });
}

/** Run a non-interactive `hr` command, streaming output to an OutputChannel. */
export function runHr(out: vscode.OutputChannel, args: string[]): Promise<{ ok: boolean; stdout: string }> {
  return new Promise(async (resolve) => {
    if (!isLocal()) {
      vscode.window.showWarningMessage(REMOTE_NOTE);
      return resolve({ ok: false, stdout: "" });
    }
    if (!(await hrAvailable())) {
      notifyNoHr();
      return resolve({ ok: false, stdout: "" });
    }
    out.show(true);
    out.appendLine(`$ ${hrPath()} ${args.join(" ")}`);
    execFile(hrPath(), args, { timeout: 120_000 }, (err, stdout, stderr) => {
      if (stdout) out.appendLine(stdout.trimEnd());
      if (stderr) out.appendLine(stderr.trimEnd());
      if (err) {
        out.appendLine(`✗ ${err.message}`);
        resolve({ ok: false, stdout: stdout || "" });
      } else {
        resolve({ ok: true, stdout: stdout || "" });
      }
    });
  });
}

/** Run an interactive `hr` command (e.g. key entry) in a VS Code terminal. */
export async function runHrTerminal(args: string[]): Promise<void> {
  if (!isLocal()) {
    vscode.window.showWarningMessage(REMOTE_NOTE);
    return;
  }
  if (!(await hrAvailable())) {
    notifyNoHr();
    return;
  }
  const term = vscode.window.createTerminal({ name: "hermes-router" });
  term.show();
  term.sendText(`${hrPath()} ${args.join(" ")}`);
}
