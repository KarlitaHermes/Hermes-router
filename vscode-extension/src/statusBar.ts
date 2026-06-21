import * as vscode from "vscode";
import { RouterStatus } from "./client";

export class StatusBar {
  private item: vscode.StatusBarItem;

  constructor() {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.item.command = "hermesRouter.openDashboard";
    this.item.show();
    this.setUnknown();
  }

  setUnknown() {
    this.item.text = "$(sync~spin) hermes-router";
    this.item.tooltip = "hermes-router: checking…";
    this.item.backgroundColor = undefined;
  }

  setUnreachable(msg: string) {
    this.item.text = "$(warning) hermes-router";
    this.item.tooltip = `hermes-router unreachable — ${msg}`;
    this.item.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
  }

  setHealthy(status: RouterStatus) {
    const providers = status.providers || {};
    const total = Object.keys(providers).length;
    const up = Object.values(providers).filter((p) => p.available !== false).length;
    const mode = status.rotation?.mode ? ` · ${status.rotation.mode}` : "";
    this.item.text = `$(check) hermes-router ${up}/${total}`;
    this.item.tooltip = `hermes-router: ${up}/${total} providers available${mode}\nClick to open the dashboard`;
    this.item.backgroundColor =
      up === 0 ? new vscode.ThemeColor("statusBarItem.errorBackground") : undefined;
  }

  dispose() {
    this.item.dispose();
  }
}
