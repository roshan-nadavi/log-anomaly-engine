"""Rolling-window aggregator.

Consumes raw log entries from the `logs:raw` Redis Stream via a
consumer group, buckets them into tumbling windows (wall-clock based —
simpler than event-time bucketing and fine at this scale since the
generator publishes close to real time), computes throughput/latency/
status-code features per window, persists them to Postgres, and
republishes the feature vector (plus the raw log-key sequence) onto
`windows:computed` for the anomaly detector to consume.
"""
import json
import os
import time
from datetime import datetime, timezone

import redis

from common.db import get_conn, init_schema
from common.streams import TRANSIENT_REDIS_ERRORS, ack, ensure_group, read_batch

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
SOURCE_STREAM = os.environ.get("SOURCE_STREAM", "logs:raw")
SINK_STREAM = os.environ.get("SINK_STREAM", "windows:computed")
SINK_MAXLEN = int(os.environ.get("SINK_MAXLEN", "50000"))
GROUP = "aggregator-group"
CONSUMER = os.environ.get("HOSTNAME", "aggregator-1")
WINDOW_SECONDS = float(os.environ.get("WINDOW_SECONDS", "10"))
RECONNECT_INITIAL_BACKOFF = 2.0
RECONNECT_MAX_BACKOFF = 30.0


def status_bucket(code: int) -> str:
    if 200 <= code < 300:
        return "2xx"
    if 400 <= code < 500:
        return "4xx"
    if 500 <= code < 600:
        return "5xx"
    return "other"


def percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(pct * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def compute_window(entries: list[dict]) -> dict:
    n = len(entries)
    latencies = sorted(e["latency_ms"] for e in entries)
    status_counts = {"2xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    for e in entries:
        status_counts[status_bucket(e["status_code"])] += 1
    error_rate = status_counts["5xx"] / n if n else 0.0
    return {
        "event_count": n,
        "avg_latency_ms": sum(latencies) / n if n else 0.0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "status_2xx": status_counts["2xx"],
        "status_4xx": status_counts["4xx"],
        "status_5xx": status_counts["5xx"],
        "error_rate": error_rate,
        "unique_services": len({e["service"] for e in entries}),
    }


def insert_window(conn, window_start, window_end, features: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO window_metrics
                (window_start, window_end, event_count, avg_latency_ms,
                 p95_latency_ms, status_2xx, status_4xx, status_5xx,
                 error_rate, unique_services)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                window_start, window_end, features["event_count"],
                features["avg_latency_ms"], features["p95_latency_ms"],
                features["status_2xx"], features["status_4xx"],
                features["status_5xx"], features["error_rate"],
                features["unique_services"],
            ),
        )
        return cur.fetchone()[0]


def main():
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    ensure_group(r, SOURCE_STREAM, GROUP)
    conn = get_conn()
    init_schema(conn)

    print(f"[aggregator] starting, window={WINDOW_SECONDS}s", flush=True)

    backoff = RECONNECT_INITIAL_BACKOFF
    while True:
        try:
            window_start_dt = datetime.now(timezone.utc)
            deadline = time.monotonic() + WINDOW_SECONDS
            buffer: list[dict] = []
            pending_ids: list[str] = []

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                block_ms = max(int(remaining * 1000), 50)
                messages = read_batch(
                    r, SOURCE_STREAM, GROUP, CONSUMER, count=500, block_ms=block_ms
                )
                for msg_id, fields in messages:
                    pending_ids.append(msg_id)
                    try:
                        buffer.append(json.loads(fields["payload"]))
                    except (KeyError, json.JSONDecodeError):
                        continue

            window_end_dt = datetime.now(timezone.utc)

            if buffer:
                features = compute_window(buffer)
                window_id = insert_window(conn, window_start_dt, window_end_dt, features)
                sequence = [[e["endpoint"], status_bucket(e["status_code"])] for e in buffer]
                payload = {
                    "window_id": window_id,
                    "window_start": window_start_dt.isoformat(),
                    "window_end": window_end_dt.isoformat(),
                    **features,
                    "sequence": sequence,
                }
                r.xadd(
                    SINK_STREAM,
                    {"payload": json.dumps(payload)},
                    maxlen=SINK_MAXLEN,
                    approximate=True,
                )
                print(
                    f"[aggregator] window {window_id}: {features['event_count']} events, "
                    f"error_rate={features['error_rate']:.3f}, "
                    f"p95={features['p95_latency_ms']:.1f}ms",
                    flush=True,
                )
            else:
                print("[aggregator] empty window, skipping", flush=True)

            if pending_ids:
                ack(r, SOURCE_STREAM, GROUP, pending_ids)

            backoff = RECONNECT_INITIAL_BACKOFF
        except TRANSIENT_REDIS_ERRORS as exc:
            print(f"[aggregator] redis unavailable ({exc}), retrying in {backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF)


if __name__ == "__main__":
    main()
