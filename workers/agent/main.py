"""Phase 5 — LLM incident agent.

Consumes flagged anomalies from `anomalies:triggered`, pulls the ~30
surrounding raw log entries out of the `logs:raw` Redis stream by time
range (error entries prioritized), retrieves similar past incidents via
pgvector cosine-similarity KNN as few-shot context, and asks an LLM for
a structured root-cause report. Network calls to the LLM API go through
a circuit breaker + exponential backoff (llm_client.py); on failure the
message is left unacked so a later XAUTOCLAIM pass retries it once the
circuit recovers, instead of dropping the anomaly on the floor.

Set LLM_DRY_RUN=true to run the full pipeline (log slice extraction,
retrieval, Postgres persistence) without calling a real LLM API —
useful for verifying the plumbing before wiring up an API key.
"""
import hashlib
import json
import os
import random
import time
from datetime import datetime

import redis
from pgvector.psycopg import register_vector
from pydantic import ValidationError

import llm_client
from circuit_breaker import CircuitOpenError
from common.db import get_conn, init_schema
from common.streams import TRANSIENT_REDIS_ERRORS, ack, ensure_group, read_batch
from models import IncidentReport
from prompts import build_prompt, build_situation_summary

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
LOG_STREAM = os.environ.get("LOG_STREAM", "logs:raw")
SOURCE_STREAM = os.environ.get("SOURCE_STREAM", "anomalies:triggered")
INCIDENT_CREATED_STREAM = os.environ.get("INCIDENT_CREATED_STREAM", "incidents:created")
GROUP = "agent-group"
CONSUMER = os.environ.get("HOSTNAME", "agent-1")

LOG_SLICE_CAP = int(os.environ.get("LOG_SLICE_CAP", "30"))
SIMILAR_INCIDENTS_K = int(os.environ.get("SIMILAR_INCIDENTS_K", "3"))
RECLAIM_IDLE_MS = int(os.environ.get("AGENT_RECLAIM_IDLE_MS", "30000"))
DRY_RUN = os.environ.get("LLM_DRY_RUN", "false").lower() == "true"
EMBEDDING_DIM = 768
RECONNECT_INITIAL_BACKOFF = 2.0
RECONNECT_MAX_BACKOFF = 30.0


def pseudo_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic stand-in for a real embedding, used only in dry-run
    mode so retrieval plumbing is exercisable without an API key. Not
    semantically meaningful — do not use outside DRY_RUN."""
    seed = hashlib.sha256(text.encode()).digest()
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(dim)]


def dry_run_chat_response(features: dict) -> str:
    error_rate = features.get("error_rate", 0) or 0
    severity = "critical" if error_rate > 0.5 else ("high" if error_rate > 0.1 else "low")
    return json.dumps({
        "root_cause": (
            f"[DRY RUN] Elevated error rate ({error_rate:.0%}) and p95 latency "
            f"({features.get('p95_latency_ms', 0):.0f}ms) suggest a downstream "
            "dependency failure or resource exhaustion."
        ),
        "severity": severity,
        "remediation": "[DRY RUN] Check downstream service health and recent "
                        "deploys; consider scaling out if resource-bound.",
        "confidence": 0.5,
    })


def _to_stream_id(dt: datetime, seq: str) -> str:
    ms = int(dt.timestamp() * 1000)
    return f"{ms}-{seq}"


def extract_log_slice(r: redis.Redis, window_start: str, window_end: str, cap: int) -> list[dict]:
    start_dt = datetime.fromisoformat(window_start)
    end_dt = datetime.fromisoformat(window_end)
    start_id = _to_stream_id(start_dt, "0")
    end_id = _to_stream_id(end_dt, "18446744073709551615")

    entries = r.xrange(LOG_STREAM, min=start_id, max=end_id)
    parsed = []
    for _id, fields in entries:
        try:
            parsed.append(json.loads(fields["payload"]))
        except (KeyError, json.JSONDecodeError):
            continue

    # Prioritize error entries so the LLM sees the most informative lines
    # first when the window has more events than the cap allows.
    parsed.sort(key=lambda e: 0 if int(e.get("status_code", 0)) >= 500 else 1)
    return parsed[:cap]


def fetch_window_features(conn, window_id: int) -> dict:
    cols = ["event_count", "avg_latency_ms", "p95_latency_ms", "error_rate",
            "status_2xx", "status_4xx", "status_5xx", "unique_services"]
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(cols)} FROM window_metrics WHERE id = %s",
            (window_id,),
        )
        row = cur.fetchone()
    return dict(zip(cols, row)) if row else {}


def find_similar_incidents(conn, embedding: list[float], k: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, root_cause, severity, remediation
            FROM incidents
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (embedding, k),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "root_cause": r[1], "severity": r[2], "remediation": r[3]} for r in rows]


def insert_incident(conn, anomaly_id, window_id, report: IncidentReport,
                     log_slice, similar_ids, raw_response, embedding) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incidents
                (anomaly_id, window_id, root_cause, severity, remediation,
                 confidence, log_slice, similar_incident_ids, raw_llm_response, embedding)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
            RETURNING id
            """,
            (
                anomaly_id, window_id, report.root_cause, report.severity.value,
                report.remediation, report.confidence, json.dumps(log_slice),
                similar_ids, json.dumps(raw_response), embedding,
            ),
        )
        return cur.fetchone()[0]


def process_anomaly(r, conn, window: dict) -> None:
    anomaly_id = window["anomaly_id"]
    window_id = window["window_id"]

    features = fetch_window_features(conn, window_id)
    log_slice = extract_log_slice(r, window["window_start"], window["window_end"], LOG_SLICE_CAP)
    summary_text = build_situation_summary(features, log_slice)

    query_embedding = pseudo_embedding(summary_text) if DRY_RUN else llm_client.embed_text(summary_text)
    similar = find_similar_incidents(conn, query_embedding, SIMILAR_INCIDENTS_K)
    prompt = build_prompt(features, log_slice, similar)

    raw_text = dry_run_chat_response(features) if DRY_RUN else llm_client.chat_complete(prompt)

    try:
        report = IncidentReport.model_validate_json(raw_text)
    except (ValidationError, ValueError) as exc:
        print(f"[agent] failed to parse LLM response for anomaly {anomaly_id}: {exc}", flush=True)
        report = IncidentReport(
            root_cause="LLM response could not be parsed as structured JSON.",
            severity="low",
            remediation="Review raw_llm_response manually.",
            confidence=0.0,
        )

    # Re-embed rather than reuse query_embedding: keeps the stored vector
    # generation path identical regardless of which branch computed the
    # query embedding above, avoiding subtle drift between the two.
    new_embedding = pseudo_embedding(summary_text) if DRY_RUN else llm_client.embed_text(summary_text)
    incident_id = insert_incident(
        conn, anomaly_id, window_id, report, log_slice,
        [s["id"] for s in similar], {"raw": raw_text}, new_embedding,
    )
    print(
        f"[agent] incident {incident_id} for anomaly {anomaly_id}: "
        f"severity={report.severity.value} confidence={report.confidence:.2f}",
        flush=True,
    )

    r.xadd(INCIDENT_CREATED_STREAM, {"payload": json.dumps({
        "incident_id": incident_id,
        "anomaly_id": anomaly_id,
        "window_id": window_id,
        "severity": report.severity.value,
        "confidence": report.confidence,
        "root_cause": report.root_cause,
        "remediation": report.remediation,
    })})


def main():
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    ensure_group(r, SOURCE_STREAM, GROUP)
    conn = get_conn()
    init_schema(conn)
    register_vector(conn)

    print(f"[agent] starting, dry_run={DRY_RUN}", flush=True)

    backoff = RECONNECT_INITIAL_BACKOFF
    while True:
        try:
            try:
                _cursor, reclaimed, _deleted = r.xautoclaim(
                    SOURCE_STREAM, GROUP, CONSUMER, min_idle_time=RECLAIM_IDLE_MS, start_id="0-0"
                )
            except redis.ResponseError:
                reclaimed = []

            block_ms = 100 if reclaimed else 5000
            messages = list(reclaimed) + read_batch(
                r, SOURCE_STREAM, GROUP, CONSUMER, count=10, block_ms=block_ms
            )
            if not messages:
                continue

            for msg_id, fields in messages:
                try:
                    window = json.loads(fields["payload"])
                except (KeyError, json.JSONDecodeError):
                    ack(r, SOURCE_STREAM, GROUP, [msg_id])
                    continue

                try:
                    process_anomaly(r, conn, window)
                except CircuitOpenError as exc:
                    print(f"[agent] circuit open, leaving anomaly {window.get('anomaly_id')} "
                          f"pending: {exc}", flush=True)
                    continue  # don't ack — reclaimed by xautoclaim once circuit recovers
                except Exception as exc:
                    print(f"[agent] failure on anomaly {window.get('anomaly_id')}, "
                          f"leaving pending for retry: {exc}", flush=True)
                    continue  # don't ack — reclaimed by xautoclaim

                ack(r, SOURCE_STREAM, GROUP, [msg_id])

            backoff = RECONNECT_INITIAL_BACKOFF
        except TRANSIENT_REDIS_ERRORS as exc:
            print(f"[agent] redis unavailable ({exc}), retrying in {backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF)


if __name__ == "__main__":
    main()
