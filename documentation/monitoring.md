# Monitoring

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

## JSON status (`/v1/status`)

`GET /v1/status` (proxy key required) returns the full picture as JSON: per-provider key
cooldown state, rating, model, latency, `supports_tools`, `reasoning`, circuit-breaker
status, plus cache and routing config. This is what `hr status` renders.
