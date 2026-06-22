import * as vscode from "vscode";
import { RouterClient, RouterStatus } from "./client";

export class DashboardProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "hermesRouter.dashboard";
  private view?: vscode.WebviewView;

  constructor(private getClient: () => RouterClient) {}

  resolveWebviewView(view: vscode.WebviewView) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = this.shell();
    view.webview.onDidReceiveMessage((msg) => {
      if (msg?.type === "refresh") {
        void this.refresh();
      } else if (msg?.type === "command" && typeof msg.command === "string") {
        void vscode.commands.executeCommand(msg.command);
      }
    });
    void this.refresh();
  }

  /** Fetch /v1/status and push it to the webview. */
  async refresh(): Promise<RouterStatus | null> {
    if (!this.view) return null;
    try {
      const status = await this.getClient().getStatus();
      this.view.webview.postMessage({ type: "status", status });
      return status;
    } catch (e: any) {
      this.view.webview.postMessage({ type: "error", message: e?.message || String(e) });
      return null;
    }
  }

  private shell(): string {
    // The webview renders the JSON it receives via postMessage. Styling uses
    // VS Code theme variables so it matches light/dark automatically.
    return /* html */ `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<style>
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); padding: 8px; }
  .bar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border:none; padding:4px 10px; border-radius:3px; cursor:pointer; }
  button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
  button:hover { opacity:.9; }
  table { width:100%; border-collapse: collapse; }
  th, td { text-align:left; padding:4px 6px; border-bottom:1px solid var(--vscode-panel-border); font-size:12px; vertical-align:top; }
  th { color: var(--vscode-descriptionForeground); font-weight:600; }
  .ok { color: var(--vscode-testing-iconPassed, #3fb950); }
  .down { color: var(--vscode-testing-iconFailed, #f85149); }
  .muted { color: var(--vscode-descriptionForeground); }
  .pill { font-size:10px; padding:1px 5px; border-radius:8px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
  .err { color: var(--vscode-testing-iconFailed, #f85149); padding:8px 0; }
  .meta { margin:8px 0; color: var(--vscode-descriptionForeground); font-size:12px; }
  .models { color: var(--vscode-descriptionForeground); font-size:11px; }
</style></head>
<body>
  <div class="bar">
    <button onclick="send('refresh')">↻ Refresh</button>
    <button class="secondary" onclick="cmd('hermesRouter.restart')">Restart</button>
    <button class="secondary" onclick="cmd('hermesRouter.setMode')">Rotation</button>
    <button class="secondary" onclick="cmd('hermesRouter.authAdd')">Add key</button>
    <button class="secondary" onclick="cmd('hermesRouter.setModel')">Model</button>
  </div>
  <div id="content" class="muted">Loading…</div>
<script>
  const vscode = acquireVsCodeApi();
  function send(type){ vscode.postMessage({type}); }
  function cmd(command){ vscode.postMessage({type:'command', command}); }
  function esc(s){ return String(s==null?'':s).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

  window.addEventListener('message', (ev) => {
    const m = ev.data;
    const el = document.getElementById('content');
    if (m.type === 'error') {
      el.innerHTML = '<div class="err">⚠ ' + esc(m.message) + '</div>' +
        '<div class="muted">Is the router running? Check hermesRouter.baseUrl / apiKey.</div>';
      return;
    }
    if (m.type !== 'status') return;
    const s = m.status || {};
    const provs = s.providers || {};
    const names = Object.keys(provs).sort();
    const cache = s.cache || {};
    const mode = (s.rotation && s.rotation.mode) || '—';
    const limits = s.limits || {};
    let totalTokens = 0;

    let rows = names.map(n => {
      const p = provs[n] || {};
      totalTokens += (p.tokens || 0);
      const avail = p.available === false ? '<span class="down">● down</span>'
                  : p.available === true ? '<span class="ok">● up</span>'
                  : '<span class="muted">● ?</span>';
      const keys = (p.keys||[]);
      const ready = keys.filter(k=>k.status==='ready').length;
      const cooling = keys.filter(k=>k.status==='cooling').length;
      const keyStr = keys.length ? (ready + ' ready' + (cooling?(' · '+cooling+' cooling'):'')) : '—';
      const modelLine = (p.models && p.models.length > 1)
        ? '<div class="models">'+esc(p.models.join(', '))+'</div>'
        : '<div class="models">'+esc(p.model||'')+'</div>';
      const caps = [p.supports_tools?'tools':'', p.reasoning?'reasoning':''].filter(Boolean).join(' · ');
      const lat = p.latency_ms ? Math.round(p.latency_ms)+'ms' : '—';
      return '<tr><td><b>'+esc(n)+'</b> '+avail+modelLine+'</td>'+
             '<td>'+(p.rating??'—')+'</td>'+
             '<td>'+esc(lat)+'</td>'+
             '<td>'+esc(keyStr)+(caps?'<div class="models">'+esc(caps)+'</div>':'')+'</td>'+
             '<td>'+(p.tokens?p.tokens.toLocaleString():'—')+'</td></tr>';
    }).join('');

    const sem = cache.semantic || {};
    const cacheStr = cache.enabled
      ? ('hit-rate '+(cache.hit_rate??0)+' · '+(cache.size??0)+'/'+(cache.max_size??'?')
         + (sem.enabled ? (' · semantic '+(sem.hits??0)) : ''))
      : 'off';
    let limitStr = '';
    if (limits.enabled && (limits.keys||[]).length) {
      limitStr = '<div class="meta">limits: ' + limits.keys.map(k => {
        const L=k.limits||{}, U=k.usage||{}, parts=[];
        if (L.rpm) parts.push((U.rpm_window||0)+'/'+L.rpm+' rpm');
        if (L.req_per_day) parts.push((U.req_today||0)+'/'+L.req_per_day+' req');
        if (L.tokens_per_day) parts.push((U.tokens_today||0)+'/'+L.tokens_per_day+' tok');
        return '…'+esc(k.key_tail||'?')+' '+(parts.join(' · ')||'unlimited');
      }).join(' &nbsp; ') + '</div>';
    }

    el.innerHTML =
      '<div class="meta">rotation: <span class="pill">'+esc(mode)+'</span> &nbsp; ' +
      'cache: '+cacheStr+(totalTokens?(' &nbsp; tokens: '+totalTokens.toLocaleString()):'')+'</div>' +
      limitStr +
      '<table><thead><tr><th>Provider</th><th>Rating</th><th>Latency</th><th>Keys</th><th>Tokens</th></tr></thead><tbody>'+
      (rows || '<tr><td colspan="5" class="muted">No providers configured.</td></tr>')+
      '</tbody></table>';
  });
</script>
</body></html>`;
  }
}
