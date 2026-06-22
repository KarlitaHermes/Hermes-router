import * as vscode from "vscode";
import { execFile } from "child_process";

function cfg<T>(key: string, dflt: T): T {
  return vscode.workspace.getConfiguration("hermesRouter").get<T>(key, dflt);
}
function hrPath(): string {
  return cfg<string>("hrPath", "hr");
}
function dockerContainer(): string {
  return cfg<string>("dockerContainer", "").trim();
}

/** True when a Docker container name is configured (manage via docker exec/restart). */
export function isDocker(): boolean {
  return dockerContainer().length > 0;
}

/** True when the configured router is local (so the `hr` CLI can control it). */
export function isLocal(): boolean {
  const base = cfg<string>("baseUrl", "");
  return /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:|\/|$)/.test(base);
}

const REMOTE_NOTE =
  "hr controls are available only when the router runs locally. " +
  "Set hermesRouter.baseUrl to a localhost URL (or hermesRouter.dockerContainer for a " +
  "Docker container), or manage the remote router where it's hosted.";

const DOCS_URL = "https://hermes-router.vercel.app/vscode-extension/";

/** Probe whether the control tool (`docker` in Docker mode, else `hr`) is runnable. */
function toolAvailable(): Promise<boolean> {
  const [bin, args] = isDocker() ? ["docker", ["version"]] : [hrPath(), ["version"]];
  return new Promise((resolve) => {
    execFile(bin, args, { timeout: 8000 }, (err: any) => {
      // ENOENT = the binary isn't on PATH. Any other outcome means it ran.
      resolve(!(err && err.code === "ENOENT"));
    });
  });
}

/** Explain that the needed CLI is missing and how to proceed. */
function notifyMissing(): void {
  const msg = isDocker()
    ? "The `docker` CLI isn't on your PATH. Start Docker Desktop (or install Docker) so the " +
      "extension can manage the container `" + dockerContainer() + "`."
    : "The `hr` CLI isn't on your PATH, so this control can't run — it's the Linux/macOS/WSL " +
      "helper for a local install. Running the router in Docker? Set " +
      "`hermesRouter.dockerContainer` to your container name to manage it via Docker instead.";
  void vscode.window.showWarningMessage(msg, "Open docs").then((pick) => {
    if (pick === "Open docs") void vscode.env.openExternal(vscode.Uri.parse(DOCS_URL));
  });
}

/** Map an `hr <args>` control command to the actual binary + argv to run. */
function controlArgv(args: string[]): { bin: string; argv: string[] } {
  if (isDocker()) {
    const c = dockerContainer();
    // Restart is a container operation, NOT `hr restart` (which would kill PID 1).
    if (args.length === 1 && args[0] === "restart") {
      return { bin: "docker", argv: ["restart", c] };
    }
    return { bin: "docker", argv: ["exec", c, "hr", ...args] };
  }
  return { bin: hrPath(), argv: args };
}

/** Run a non-interactive control command, streaming output to an OutputChannel. */
export function runHr(out: vscode.OutputChannel, args: string[]): Promise<{ ok: boolean; stdout: string }> {
  return new Promise(async (resolve) => {
    if (!isDocker() && !isLocal()) {
      vscode.window.showWarningMessage(REMOTE_NOTE);
      return resolve({ ok: false, stdout: "" });
    }
    if (!(await toolAvailable())) {
      notifyMissing();
      return resolve({ ok: false, stdout: "" });
    }
    const { bin, argv } = controlArgv(args);
    out.show(true);
    out.appendLine(`$ ${bin} ${argv.join(" ")}`);
    execFile(bin, argv, { timeout: 120_000 }, (err, stdout, stderr) => {
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

/** Run an interactive control command (e.g. key entry) in a VS Code terminal. */
export async function runHrTerminal(args: string[]): Promise<void> {
  if (!isDocker() && !isLocal()) {
    vscode.window.showWarningMessage(REMOTE_NOTE);
    return;
  }
  if (!(await toolAvailable())) {
    notifyMissing();
    return;
  }
  const term = vscode.window.createTerminal({ name: "hermes-router" });
  term.show();
  if (isDocker()) {
    const c = dockerContainer();
    // You type the key into the container's hr prompt (extension never sees it),
    // then the container restarts so the new key/login takes effect.
    term.sendText(`docker exec -it ${c} hr ${args.join(" ")}`);
    term.sendText(`docker restart ${c}`);
  } else {
    term.sendText(`${hrPath()} ${args.join(" ")}`);
  }
}
