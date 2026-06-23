---
title: "Monitoring"
description: "The hr status dashboard, Prometheus /metrics, and the /v1/status JSON endpoint."
---

## Live dashboard

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
| `hermes_router_key_requests_total` | counter | `key` | Requests per proxy key (key tail) |

## Usage analytics (`/v1/usage`)

`GET /v1/usage` (proxy key required) returns a JSON summary for dashboards and billing:

- **per provider** — requests, errors, tokens served
- **per key** — request and token totals (lifetime + today, plus the live RPM window);
  keys are shown by their **last 6 chars only**, never in full
- **cache** — hits, misses, hit-rate, semantic hits
- **totals** — total tokens and uptime

```bash
curl -H "Authorization: Bearer sk-router-1" http://localhost:8319/v1/usage
```

## JSON status (`/v1/status`)

`GET /v1/status` (proxy key required) returns the full picture as JSON: per-provider key
cooldown state, rating, model, latency, `supports_tools`, `reasoning`, tokens served,
circuit-breaker status, plus cache (incl. semantic + a `persistent` flag), routing, and per-key
limit/usage config. This is what `hr status` renders.

The `rotation` block reports the active key-rotation mode
(`{"rotation": {"mode": "round-robin"}}`); the `limits` block reports per-key budgets and live
usage; `hr status` shows both in the footer. See [configuration.md](/configuration/) for details.
