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
}
