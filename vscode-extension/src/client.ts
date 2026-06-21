import * as http from "http";
import * as https from "https";
import { URL } from "url";

export interface ProviderStatus {
  available?: boolean;
  rating?: number;
  latency_ms?: number;
  model?: string;
  models?: string[];
  supports_tools?: boolean;
  reasoning?: boolean;
  keys?: { key_tail: string; status: string; ready_in: number }[];
  breaker?: { open?: boolean };
  stats?: { total_requests?: number; error_rate?: number; errors?: number };
}

export interface RouterStatus {
  providers: Record<string, ProviderStatus>;
  cache?: { enabled?: boolean; hit_rate?: number; size?: number; max_size?: number };
  rotation?: { mode?: string };
}

export interface Health {
  status: string;
  providers: string[];
}

function get(urlStr: string, headers: Record<string, string>, timeoutMs = 6000): Promise<{ code: number; body: string }> {
  return new Promise((resolve, reject) => {
    let url: URL;
    try {
      url = new URL(urlStr);
    } catch (e) {
      return reject(new Error(`bad URL: ${urlStr}`));
    }
    const lib = url.protocol === "https:" ? https : http;
    const req = lib.request(
      url,
      { method: "GET", headers, timeout: timeoutMs },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => resolve({ code: res.statusCode || 0, body: data }));
      }
    );
    req.on("timeout", () => req.destroy(new Error("request timed out")));
    req.on("error", reject);
    req.end();
  });
}

export class RouterClient {
  constructor(private baseUrl: string, private apiKey: string) {}

  private base(): string {
    return this.baseUrl.replace(/\/+$/, "");
  }

  async getHealth(): Promise<Health> {
    const { code, body } = await get(`${this.base()}/health`, {});
    if (code !== 200) {
      throw new Error(`health HTTP ${code}`);
    }
    return JSON.parse(body) as Health;
  }

  async getStatus(): Promise<RouterStatus> {
    const { code, body } = await get(`${this.base()}/v1/status`, {
      Authorization: `Bearer ${this.apiKey}`,
    });
    if (code === 401) {
      throw new Error("unauthorized — check hermesRouter.apiKey (must match PROXY_API_KEYS)");
    }
    if (code !== 200) {
      throw new Error(`status HTTP ${code}`);
    }
    return JSON.parse(body) as RouterStatus;
  }

  /**
   * Stream a chat completion from the router. POSTs an OpenAI-format request with
   * stream:true to /v1/chat/completions and invokes onText() for each content
   * delta. Resolves when the stream ends; aborts when onAbort fires.
   */
  streamChat(
    messages: ChatMessage[],
    opts: { onText: (delta: string) => void; onAbort?: (cancel: () => void) => void }
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      let url: URL;
      try {
        url = new URL(`${this.base()}/v1/chat/completions`);
      } catch {
        return reject(new Error(`bad URL: ${this.base()}`));
      }
      const lib = url.protocol === "https:" ? https : http;
      const payload = JSON.stringify({ model: "hermes-router", messages, stream: true });
      const req = lib.request(
        url,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(payload),
            Authorization: `Bearer ${this.apiKey}`,
          },
          timeout: 120_000,
        },
        (res) => {
          if (res.statusCode === 401) {
            res.resume();
            return reject(new Error("unauthorized — check hermesRouter.apiKey"));
          }
          if ((res.statusCode || 0) < 200 || (res.statusCode || 0) >= 300) {
            let err = "";
            res.on("data", (c) => (err += c));
            res.on("end", () => reject(new Error(`router HTTP ${res.statusCode}: ${err.slice(0, 300)}`)));
            return;
          }
          let buf = "";
          res.setEncoding("utf-8");
          res.on("data", (chunk: string) => {
            buf += chunk;
            let nl: number;
            while ((nl = buf.indexOf("\n")) >= 0) {
              const line = buf.slice(0, nl).trim();
              buf = buf.slice(nl + 1);
              if (!line.startsWith("data:")) continue;
              const data = line.slice(5).trim();
              if (!data || data === "[DONE]") continue;
              try {
                const ev = JSON.parse(data);
                const delta = ev?.choices?.[0]?.delta?.content;
                if (typeof delta === "string" && delta) opts.onText(delta);
              } catch {
                /* ignore keepalive / partial lines */
              }
            }
          });
          res.on("end", () => resolve());
          res.on("error", reject);
        }
      );
      req.on("timeout", () => req.destroy(new Error("request timed out")));
      req.on("error", (e: any) => {
        if (e?.code === "ECONNRESET" && cancelled) resolve(); // aborted by user
        else reject(e);
      });
      let cancelled = false;
      opts.onAbort?.(() => {
        cancelled = true;
        req.destroy();
      });
      req.write(payload);
      req.end();
    });
  }
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}
