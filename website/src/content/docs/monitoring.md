---
title: "Monitoring"
description: "The built-in web dashboard, hr status, Prometheus /metrics, and the /v1/status and /v1/logs endpoints."
---

## Web dashboard

The router serves a built-in **browser dashboard** — no install, no extra service. It ships
inside `router.py`, so it's available the moment the router is running. Just open the router
in a browser:

```
http://localhost:8319/          # redirects to the dashboard
http://localhost:8319/dashboard
```

On first load it asks for your proxy API key (one of `PROXY_API_KEYS`) and remembers it in
the browser's local storage. The page then auto-refreshes every 5 seconds and shows:

- **Summary cards** — providers online, uptime, total requests, tokens + estimated spend,
  cache hit-rate, and live error rate
- **Provider health** — per-provider requests, errors, error %, latency, tokens, cost,
  key pool (ready/cooling), circuit-breaker state, and a health pill
- **Live request log** — the last requests (endpoint, provider, model, latency, complexity
  score, cascade count, tokens, status), filterable by status and endpoint
- **Cache & add-ons** — hit/miss counts, semantic cache, persistence, and which optional
  features are on
- **Key & budget usage** — per-key requests, daily tokens/cost, and RPM headroom

It's pure HTML/JS (no framework, no external CDN, ~25 KB) and reads only the existing
`/v1/status`, `/v1/usage`, and `/v1/logs` endpoints — so it adds essentially no memory or CPU
to the router itself.

> **Accessing it remotely.** By default the router binds to `0.0.0.0` (all interfaces). If you
> set `HOST=127.0.0.1` (localhost-only, recommended on a shared/VPS host), reach the dashboard
> over an SSH tunnel: `ssh -L 8319:127.0.0.1:8319 user@server`, then open
> `http://localhost:8319/` locally. With **Docker** the mapped port (`-p 8319:8319`) exposes it
> to your host automatically. The raw API endpoints stay key-protected either way.

From **VS Code**, the extension's dashboard panel has a **⬈ Web dashboard** button (and a globe
icon in the panel header) that opens this page in your browser.

## Terminal dashboard (`hr status`)

`hr status` prints a live, per-provider dashboard — rating, health (circuit-breaker
state), key pool, latency, and cache stats — without needing curl or an API key:

```bash
hr status
hr status --json   # raw JSON for scripts
```

## Prometheus metrics (`/metrics`)

A Prometheus-compatible endpoint is exposed at `/metrics`. It reveals only counts and
timings — never request content — so it's **unauthenticated by default**, like `/health`.
Set `METRICS_REQUIRE_AUTH=1` to require the proxy key.

```bash
curl http://localhost:8319/metrics
```

Point Prometheus/Grafana at it to track per-provider traffic and the cache over time.

### Exposed metrics

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `hermes_router_uptime_seconds` | gauge | — | Seconds since the router started |
| `hermes_router_providers` | gauge | — | Number of configured providers |
| `hermes_router_requests_total` | counter | `provider` | Total requests routed per provider |
| `hermes_router_errors_total` | counter | `provider` | Total errored requests per provider |
| `hermes_router_avg_latency_ms` | gauge | `provider` | Mean successful-request latency (ms) |
| `hermes_router_circuit_breaker_open` | gauge | `provider` | `1` if the breaker is open, else `0` |
| `hermes_router_cache_hits_total` | counter | — | Response-cache hits |
| `hermes_router_cache_misses_total` | counter | — | Response-cache misses |
| `hermes_router_cache_size` | gauge | — | Entries currently in the response cache |
| `hermes_router_semantic_cache_hits_total` | counter | — | Semantic-cache hits |
| `hermes_router_tokens_total` | counter | `provider` | Tokens served per provider (non-streaming) |
| `hermes_router_cost_usd_total` | counter | `provider` | Estimated USD cost served per provider |
| `hermes_router_key_requests_total` | counter | `key` | Requests per proxy key (key tail) |

## Usage analytics (`/v1/usage`)

`GET /v1/usage` (proxy key required) returns a JSON summary for dashboards and billing:

- **per provider** — requests, errors, tokens served, and estimated `cost` (`{"usd": …}`, plus a
  converted currency when `COST_FX_RATE` is set)
- **per key** — request, token, and cost totals (lifetime + today, plus the live RPM window);
  keys are shown by their **last 6 chars only**, never in full
- **cache** — hits, misses, hit-rate, semantic hits
- **totals** — total tokens, total estimated cost, and uptime

Cost is estimated from a built-in price table; free providers and subscription plans are `$0`.
See [Configuration → Cost awareness](/configuration/#cost--spend-awareness).

```bash
curl -H "Authorization: Bearer sk-router-1" http://localhost:8319/v1/usage
```

## JSON status (`/v1/status`)

`GET /v1/status` (proxy key required) returns the full picture as JSON: per-provider key
cooldown state, rating, model, latency, `supports_tools`, `reasoning`, tokens served,
circuit-breaker status, plus cache (incl. semantic + a `persistent` flag), routing, and per-key
limit/usage config. This is what `hr status` renders.

Each entry in a provider's `keys` array also reports `requests` — how many times that specific
**provider key** (last 6 chars only) has been handed out since the router started. This is the
direct evidence that round-robin is actually spreading load evenly: add more keys to a provider
and each one's `requests` count should climb roughly in step with the others. The built-in web
dashboard (`/dashboard`) shows this as a tooltip on each key's status dot.

The `rotation` block reports the active key-rotation mode
(`{"rotation": {"mode": "round-robin"}}`); the `limits` block reports per-key budgets and live
usage; `hr status` shows both in the footer. See [configuration.md](/configuration/) for details.

## Request log (`/v1/logs`)

`GET /v1/logs` (proxy key required) returns the most recent requests from an **in-memory ring
buffer** — the data source behind the web dashboard's live log. It never writes to disk: the
last `REQUEST_LOG_SIZE` entries (default **500**) are kept in RAM and the oldest fall off as new
ones arrive (~250 KB at the default size). Set `REQUEST_LOG_SIZE=0` to disable it entirely.

Each entry records: timestamp, endpoint (`chat`/`messages`/`embeddings`), caller (key tail),
streaming flag, complexity score (1–5), estimated tokens, chosen provider + model, latency,
cascade count, status (`success`/`error`/`cache_hit`), and prompt/completion token counts.
Request and response **content is never stored** — only metadata.

Query parameters (all optional): `limit` (default 100), `provider`, `status`
(`success`/`error`/`cache_hit`), and `endpoint` (`chat`/`messages`/`embeddings`).

```bash
curl -H "Authorization: Bearer sk-router-1" \
  "http://localhost:8319/v1/logs?limit=20&status=error"
```

---

**Next:** [How it works](/architecture/) — the full request pipeline and every moving part, under the hood.
