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

/** Run a non-interactive `hr` command, streaming output to an OutputChannel. */
export function runHr(out: vscode.OutputChannel, args: string[]): Promise<{ ok: boolean; stdout: string }> {
  return new Promise((resolve) => {
    if (!isLocal()) {
      vscode.window.showWarningMessage(REMOTE_NOTE);
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
export function runHrTerminal(args: string[]): void {
  if (!isLocal()) {
    vscode.window.showWarningMessage(REMOTE_NOTE);
    return;
  }
  const term = vscode.window.createTerminal({ name: "hermes-router" });
  term.show();
  term.sendText(`${hrPath()} ${args.join(" ")}`);
}
