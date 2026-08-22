"""Phase 6 — read/query API + live streaming.

Separate from the ingestion service on purpose: this process holds
long-lived SSE connections and serves concurrent REST queries on the
same event loop, so it needs async DB access (psycopg's async
connection pool) rather than the sync-per-request style that's fine
for ingestion's short-lived writes. Mixing that into the ingestion
service would risk SSE connections stalling the write hot path, or
vice versa.

REST endpoints read historical data from Postgres. `/stream/live`
subscribes to the `windows:computed` and `incidents:created` Redis
streams directly (not via a consumer group — every connected dashboard
client should see every event from the moment it connects, which is
fan-out behavior, not the competing-consumer behavior a consumer group
provides) and forwards new entries as they arrive.
"""
import asyncio
import json
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg_pool import AsyncConnectionPool

from common.db import DATABASE_URL, get_conn, init_schema

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
WINDOW_STREAM = os.environ.get("WINDOW_STREAM", "windows:computed")
INCIDENT_STREAM = os.environ.get("INCIDENT_STREAM", "incidents:created")
LOG_STREAM = os.environ.get("LOG_STREAM", "logs:raw")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

STREAM_EVENT_TYPES = {WINDOW_STREAM: "window", INCIDENT_STREAM: "incident", LOG_STREAM: "log"}

INGESTION_URL = os.environ.get("INGESTION_URL", "http://ingestion:8000")
INJECT_SPIKE_COOLDOWN_SECONDS = int(os.environ.get("INJECT_SPIKE_COOLDOWN_SECONDS", "30"))
INJECT_SPIKE_BATCH_SIZE = int(os.environ.get("INJECT_SPIKE_BATCH_SIZE", "80"))
INJECT_SPIKE_MAX_SIZE = int(os.environ.get("INJECT_SPIKE_MAX_SIZE", "400"))
INJECT_SPIKE_MAX_DURATION_SECONDS = int(os.environ.get("INJECT_SPIKE_MAX_DURATION_SECONDS", "120"))

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One-time sync connection just to ensure the schema exists, matching
    # the pattern the worker services already use — safe to run even if
    # the workers already did this, since it's all CREATE ... IF NOT EXISTS.
    conn = get_conn()
    init_schema(conn)
    conn.close()

    pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=False)
    await pool.open()
    state["pool"] = pool
    state["redis"] = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield
    await pool.close()
    await state["redis"].aclose()


API_RATE_LIMIT_PER_MINUTE = int(os.environ.get("API_RATE_LIMIT_PER_MINUTE", "120"))
API_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("API_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_EXEMPT_PATHS = {"/health"}

app = FastAPI(title="LogPulse Query & Streaming API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Fixed-window per-IP counter over every route (this is the public
    # read + demo API), independent of /demo/inject-spike's own stricter
    # per-IP cooldown below — that cooldown is already the binding limit
    # on that one route, this is the backstop for everything else
    # (including repeated /stream/live connection attempts).
    if request.url.path not in RATE_LIMIT_EXEMPT_PATHS:
        # Wall-clock time here (not monotonic, unlike the inject-spike
        # cooldown below) — this needs a bucket boundary aligned to real
        # time so it's independent of process start and observable/
        # debuggable directly from the Redis keys.
        bucket = int(time.time() // API_RATE_LIMIT_WINDOW_SECONDS)
        key = f"ratelimit:api:{_client_ip(request)}:{bucket}"
        try:
            count = await state["redis"].incr(key)
            if count == 1:
                await state["redis"].expire(key, API_RATE_LIMIT_WINDOW_SECONDS)
        except Exception:
            count = 0  # fail open — Redis being down surfaces via the route's own error handling
        if count > API_RATE_LIMIT_PER_MINUTE:
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded, slow down"})
    return await call_next(request)


async def fetch_all(query: str, params: tuple = ()) -> list[tuple]:
    async with state["pool"].connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


async def fetch_one(query: str, params: tuple = ()):
    async with state["pool"].connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/status")
async def get_status():
    window_count = (await fetch_one("SELECT count(*) FROM window_metrics"))[0]
    incident_count = (await fetch_one("SELECT count(*) FROM incidents"))[0]
    flagged_count = (await fetch_one("SELECT count(*) FROM anomalies WHERE combined_flag"))[0]
    last_window_at = (await fetch_one("SELECT max(window_end) FROM window_metrics"))[0]
    try:
        await state["redis"].ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {
        "redis_ok": redis_ok,
        "window_count": window_count,
        "incident_count": incident_count,
        "flagged_anomaly_count": flagged_count,
        "last_window_at": last_window_at,
    }


WINDOW_COLS = [
    "id", "window_start", "window_end", "event_count", "avg_latency_ms",
    "p95_latency_ms", "status_2xx", "status_4xx", "status_5xx",
    "error_rate", "unique_services",
]


@app.get("/metrics/windows")
async def list_windows(limit: int = Query(50, ge=1, le=500)):
    rows = await fetch_all(
        f"SELECT {', '.join(WINDOW_COLS)} FROM window_metrics ORDER BY id DESC LIMIT %s",
        (limit,),
    )
    return [dict(zip(WINDOW_COLS, row)) for row in rows]


ANOMALY_COLS = [
    "id", "window_id", "window_start", "window_end", "iso_forest_score",
    "iso_forest_flag", "sequence_score", "sequence_flag", "combined_flag",
]


@app.get("/anomalies")
async def list_anomalies(limit: int = Query(50, ge=1, le=500), flagged_only: bool = False):
    where = "WHERE combined_flag" if flagged_only else ""
    rows = await fetch_all(
        f"SELECT {', '.join(ANOMALY_COLS)} FROM anomalies {where} ORDER BY id DESC LIMIT %s",
        (limit,),
    )
    return [dict(zip(ANOMALY_COLS, row)) for row in rows]


INCIDENT_LIST_COLS = [
    "id", "anomaly_id", "window_id", "root_cause", "severity",
    "remediation", "confidence", "created_at",
]
INCIDENT_DETAIL_COLS = INCIDENT_LIST_COLS + ["log_slice", "similar_incident_ids", "raw_llm_response"]


@app.get("/incidents")
async def list_incidents(limit: int = Query(50, ge=1, le=500), severity: str | None = None):
    where, params = "", []
    if severity:
        where = "WHERE severity = %s"
        params.append(severity)
    params.append(limit)
    rows = await fetch_all(
        f"SELECT {', '.join(INCIDENT_LIST_COLS)} FROM incidents {where} ORDER BY id DESC LIMIT %s",
        tuple(params),
    )
    return [dict(zip(INCIDENT_LIST_COLS, row)) for row in rows]


@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: int):
    row = await fetch_one(
        f"SELECT {', '.join(INCIDENT_DETAIL_COLS)} FROM incidents WHERE id = %s",
        (incident_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return dict(zip(INCIDENT_DETAIL_COLS, row))


async def _sse_event_stream():
    r = state["redis"]
    last_ids = {stream: "$" for stream in STREAM_EVENT_TYPES}
    while True:
        try:
            resp = await r.xread(last_ids, block=15000, count=50)
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            break
        if not resp:
            yield ": keepalive\n\n"  # SSE comment line, keeps proxies/browsers from timing out
            continue
        for stream_name, messages in resp:
            for msg_id, fields in messages:
                last_ids[stream_name] = msg_id
                event_type = STREAM_EVENT_TYPES[stream_name]
                yield f"event: {event_type}\ndata: {fields.get('payload', '{}')}\n\n"


@app.get("/stream/live")
async def stream_live():
    return StreamingResponse(_sse_event_stream(), media_type="text/event-stream")


DEMO_SERVICES = ["checkout-api", "auth-service", "search-api", "recommendation-engine"]
DEMO_ENDPOINTS = ["/api/v1/orders", "/api/v1/login", "/api/v1/search", "/api/v1/recommend", "/api/v1/cart"]
DEMO_METHODS = ["GET", "GET", "POST", "PUT"]
DEMO_ERROR_MESSAGES = [
    "upstream timeout after 30000ms",
    "connection refused by downstream service",
    "database connection pool exhausted",
    "circuit breaker open for payment-gateway",
    "unhandled exception in request handler",
]
# Outside DEMO_ENDPOINTS on purpose: the sequence/n-gram detector learns
# normal endpoint-transition patterns, so hammering an endpoint it's never
# seen is what makes this profile a *sequence* anomaly rather than a
# statistical one — status/latency stay completely normal.
SEQUENCE_ANOMALY_ENDPOINT = "/internal/debug/dump"

_last_inject_by_ip: dict[str, float] = {}


def _synth_error_burst(n: int) -> list[dict]:
    # Elevated 5xx rate + high latency — stresses both detectors at once.
    return [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": "ERROR",
            "service": random.choice(DEMO_SERVICES),
            "endpoint": random.choice(DEMO_ENDPOINTS),
            "method": random.choice(DEMO_METHODS),
            "status_code": random.choice([500, 500, 502, 503]),
            "latency_ms": round(random.uniform(1500, 5000), 2),
            "message": random.choice(DEMO_ERROR_MESSAGES),
            "attributes": {"demo_injected": "true", "spike_type": "error_burst"},
        }
        for _ in range(n)
    ]


def _synth_latency_spike(n: int) -> list[dict]:
    # Requests stay 200 OK but slow to a crawl — isolates the latency
    # signal from error rate.
    return [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": "WARN",
            "service": random.choice(DEMO_SERVICES),
            "endpoint": random.choice(DEMO_ENDPOINTS),
            "method": random.choice(DEMO_METHODS),
            "status_code": 200,
            "latency_ms": round(random.uniform(1200, 4000), 2),
            "message": "request completed slowly",
            "attributes": {"demo_injected": "true", "spike_type": "latency_spike"},
        }
        for _ in range(n)
    ]


def _synth_traffic_surge(n: int) -> list[dict]:
    # Same shape as ordinary traffic — it's the caller-controlled volume
    # (a larger `size`, or a short `duration_seconds`) that makes this an
    # anomaly, isolating the throughput signal.
    return [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": "INFO",
            "service": random.choice(DEMO_SERVICES),
            "endpoint": random.choice(DEMO_ENDPOINTS),
            "method": random.choice(DEMO_METHODS),
            "status_code": 200,
            "latency_ms": round(random.uniform(15, 250), 2),
            "message": "request completed",
            "attributes": {"demo_injected": "true", "spike_type": "traffic_surge"},
        }
        for _ in range(n)
    ]


def _synth_sequence_anomaly(n: int) -> list[dict]:
    # Normal status/latency — only the access pattern is off, so this
    # exercises the sequence/n-gram detector specifically rather than the
    # Isolation Forest's aggregate features.
    return [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": "INFO",
            "service": random.choice(DEMO_SERVICES),
            "endpoint": SEQUENCE_ANOMALY_ENDPOINT,
            "method": "GET",
            "status_code": 200,
            "latency_ms": round(random.uniform(15, 250), 2),
            "message": "request completed",
            "attributes": {"demo_injected": "true", "spike_type": "sequence_anomaly"},
        }
        for _ in range(n)
    ]


SPIKE_PROFILES = {
    "error_burst": {
        "label": "Error burst",
        "description": "Elevated 5xx rate with high latency — the default failure-cascade shape.",
    },
    "latency_spike": {
        "label": "Latency spike",
        "description": "Requests stay 200 OK but slow down sharply — isolates the latency signal.",
    },
    "traffic_surge": {
        "label": "Traffic surge",
        "description": "A much larger burst of otherwise-normal traffic — isolates the throughput signal.",
    },
    "sequence_anomaly": {
        "label": "Sequence anomaly",
        "description": "Repeated hits on an endpoint outside the normal access pattern — targets the sequence/n-gram detector.",
    },
}

SPIKE_SYNTHESIZERS = {
    "error_burst": _synth_error_burst,
    "latency_spike": _synth_latency_spike,
    "traffic_surge": _synth_traffic_surge,
    "sequence_anomaly": _synth_sequence_anomaly,
}


def _client_ip(request: Request) -> str:
    # Trusts X-Forwarded-For as-is, which is fine behind our own Caddy
    # reverse proxy (the deployment target) but would be spoofable if
    # this service were ever exposed directly to the internet without a
    # trusted proxy in front setting that header itself.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/demo/spike-types")
async def list_spike_types():
    return [{"id": spike_id, **profile} for spike_id, profile in SPIKE_PROFILES.items()]


async def _send_batch(entries: list[dict]) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{INGESTION_URL}/logs/batch", json=entries)
        resp.raise_for_status()


async def _send_batch_logged(entries: list[dict]) -> None:
    # Used from a background task, where there's no request left to raise
    # an HTTPException into — log and move on instead.
    try:
        await _send_batch(entries)
    except httpx.HTTPError as exc:
        print(f"[inject-spike] batch send failed: {exc}")


async def _run_spike_over_time(spike_type: str, size: int, duration_seconds: int) -> None:
    synth = SPIKE_SYNTHESIZERS[spike_type]
    chunks = max(1, min(duration_seconds, size))  # roughly one chunk per second
    base, extra = divmod(size, chunks)
    interval = duration_seconds / chunks
    for i in range(chunks):
        n = base + (1 if i < extra else 0)
        if n > 0:
            await _send_batch_logged(synth(n))
        if i < chunks - 1:
            await asyncio.sleep(interval)


@app.post("/demo/inject-spike")
async def inject_spike(
    request: Request,
    background_tasks: BackgroundTasks,
    spike_type: str = Query("error_burst"),
    size: int = Query(INJECT_SPIKE_BATCH_SIZE, ge=10, le=INJECT_SPIKE_MAX_SIZE),
    duration_seconds: int = Query(0, ge=0, le=INJECT_SPIKE_MAX_DURATION_SECONDS),
):
    if spike_type not in SPIKE_SYNTHESIZERS:
        raise HTTPException(status_code=400, detail=f"unknown spike_type: {spike_type}")

    client_ip = _client_ip(request)
    now = time.monotonic()
    last = _last_inject_by_ip.get(client_ip)
    if last is not None and (now - last) < INJECT_SPIKE_COOLDOWN_SECONDS:
        wait = INJECT_SPIKE_COOLDOWN_SECONDS - (now - last)
        raise HTTPException(status_code=429, detail=f"try again in {wait:.0f}s")
    _last_inject_by_ip[client_ip] = now

    if duration_seconds == 0:
        batch = SPIKE_SYNTHESIZERS[spike_type](size)
        try:
            await _send_batch(batch)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"ingestion unreachable: {exc}")
        return {"injected": len(batch), "spike_type": spike_type, "duration_seconds": 0}

    background_tasks.add_task(_run_spike_over_time, spike_type, size, duration_seconds)
    return {"injected": size, "spike_type": spike_type, "duration_seconds": duration_seconds}
