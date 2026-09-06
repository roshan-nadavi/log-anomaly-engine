# Phase 8 — resilience, load testing, chaos testing

Results from the load and chaos tests run against this deployment.
Raw commands live in [infra/load-test/load_test.js](../infra/load-test/load_test.js).

## Rate limiting

- Ingestion (`POST /logs`, `/logs/batch`, `/logs/raw`): 600 req/min per IP,
  Redis-backed fixed-window counter (`ingestion/app/rate_limit.py`).
- API (all routes except `/health`): 120 req/min per IP
  (`api/app/main.py`).
- `/demo/inject-spike` additionally has its own 30s per-IP cooldown, independent
  of the general API limit.

## Load test results

k6, `constant-arrival-rate` executor, run via
`docker compose --profile tools run load-test`.

**Sustained baseline** (8 req/s, batch mode, 45s, comfortably under the
600/min ingestion limit):

| Metric | Value |
|---|---|
| p50 | 4.47ms |
| p90 | 7.72ms |
| p95 | 8.68ms |
| p99 | 12.51ms |
| Throughput | 8.04 req/s |
| Success rate | 100% (361/361) |

**Burst test** (30 req/s, single-entry mode, 30s, intentionally over the
10 req/s ceiling) — verifies the rate limiter holds under real concurrent
load rather than a single manual request:

| Metric | Value |
|---|---|
| Accepted | 772 / 901 (85.7%) |
| Rejected (429) | 129 / 901 (14.3%) |
| p50 (accepted requests) | 3.2ms |
| p99 (accepted requests) | 6.66ms |

Accepted-request latency did not degrade under the overage — the limiter
rejects overflow cleanly rather than causing cascading slowdown.

## Chaos test: Redis outage

**Before the fix:** `agent`, `aggregator`, and `detector` all crashed with
an unhandled `redis.exceptions.ConnectionError` when Redis was stopped
mid-run, and stayed down — no `restart:` policy was configured, and
`read_batch`/`ack`/`xadd` calls in each service's main loop had no error
handling around them. `ingestion` and `api` degraded gracefully (503s,
`redis_ok: false`) and auto-recovered the instant Redis came back, since
those errors are caught per-request rather than propagating out of the
process.

**Fix:** each worker's outer loop now catches `ConnectionError`/
`TimeoutError`, logs, and retries with exponential backoff (2s → 4s → 8s
→ 16s → capped at 30s) instead of crashing — see
`workers/common/streams.py` and the three `main.py` files. `redis-py`
reconnects its connection pool transparently on the next call, so no
manual reconnection logic is needed. `restart: unless-stopped` was also
added to all three services as a secondary safety net for genuinely
unexpected crashes, not as the primary recovery mechanism — restarting
loses the detector's in-memory fitted model and buffered baseline
windows, which a fresh process has to re-warm.

**Retest result:** all three services stayed alive through a full Redis
stop/start cycle, logging the outage and recovering automatically with
no manual intervention; a fresh anomaly sent immediately after recovery
was still processed correctly end-to-end.

## Chaos test: LLM API outage (circuit breaker)

Simulated by blackholing the Gemini API hostname in `/etc/hosts` inside
the running `agent` container (not a restart — this preserves real
in-memory breaker state and the real API key, rather than resetting
both by relaunching the process).

- Circuit breaker opened after repeated failures, as expected.
- While the outage was live, it correctly cycled through half-open
  trial attempts roughly every 60s, each failing and reopening — it
  never got stuck open or crashed the agent.
- After removing the blackhole, the very next half-open trial succeeded
  and the circuit closed — fully automatic, no restart involved.
- All anomalies that were left pending during the outage were later
  reclaimed via `XAUTOCLAIM` and processed successfully once the
  circuit recovered — zero data loss across the outage.

## Known limitation carried into Phase 9

The raw-log normalization layer (`ingestion/app/parsers.py`) assigns
synthetic `status_code`/`latency_ms` values (from a severity → proxy
table) to non-HTTP log sources, since they have no real values for
those fields. These synthetic numbers currently blend into the same
window features as real HTTP traffic in the aggregator. Each normalized
entry is tagged `attributes.source_format` + `synthetic_metrics=true`
so a future aggregator revision could stratify or exclude synthetic
entries from latency-sensitive features — not implemented yet.
