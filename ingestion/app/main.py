import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.config import settings
from app.models import IngestResponse, LogEntry
from app.rate_limit import client_ip, is_rate_limited
from app.redis_client import get_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingestion")

app = FastAPI(title="LogPulse Ingestion API")

RATE_LIMITED_PATHS = {"/logs", "/logs/batch"}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in RATE_LIMITED_PATHS and await is_rate_limited(client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "rate limit exceeded, slow down"})
    return await call_next(request)


def _to_stream_fields(entry: LogEntry) -> dict[str, str]:
    # Redis Streams fields are flat string k/v pairs, so nested/typed
    # fields get serialized. Consumers (aggregator, detectors) parse
    # `payload` back into the same LogEntry shape.
    return {"payload": entry.model_dump_json()}


@app.get("/health")
async def health():
    client = get_client()
    try:
        await client.ping()
    except RedisError:
        raise HTTPException(status_code=503, detail="redis unavailable")
    return {"status": "ok"}


@app.post("/logs", response_model=IngestResponse, status_code=202)
async def ingest_log(entry: LogEntry):
    client = get_client()
    try:
        stream_id = await client.xadd(
            settings.stream_name,
            _to_stream_fields(entry),
            maxlen=settings.stream_maxlen,
            approximate=True,
        )
    except RedisError as exc:
        logger.error("failed to publish log entry: %s", exc)
        raise HTTPException(status_code=503, detail="queue unavailable")
    return IngestResponse(accepted=1, stream_id=stream_id)


@app.post("/logs/batch", response_model=IngestResponse, status_code=202)
async def ingest_batch(entries: list[LogEntry]):
    if not entries:
        raise HTTPException(status_code=400, detail="empty batch")
    if len(entries) > settings.batch_max_size:
        raise HTTPException(
            status_code=413,
            detail=f"batch too large: {len(entries)} entries (max {settings.batch_max_size})",
        )
    client = get_client()
    try:
        pipe = client.pipeline()
        for entry in entries:
            pipe.xadd(
                settings.stream_name,
                _to_stream_fields(entry),
                maxlen=settings.stream_maxlen,
                approximate=True,
            )
        await pipe.execute()
    except RedisError as exc:
        logger.error("failed to publish batch: %s", exc)
        raise HTTPException(status_code=503, detail="queue unavailable")
    return IngestResponse(accepted=len(entries))
