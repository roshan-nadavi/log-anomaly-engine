import time

from fastapi import Request
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_client


def client_ip(request: Request) -> str:
    # Trusts X-Forwarded-For as-is, which is fine behind our own Caddy
    # reverse proxy (the deployment target) but would be spoofable if
    # this service were ever exposed directly to the internet without a
    # trusted proxy in front setting that header itself.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def is_rate_limited(ip: str) -> bool:
    """Fixed-window counter in Redis, so the limit holds even if this
    service ever runs as more than one replica. Fails open on Redis
    errors — if Redis is down, the actual xadd call downstream will
    already fail with a 503; a rate limiter that also fails should not
    additionally mask that with an unrelated 429."""
    bucket = int(time.time() // settings.rate_limit_window_seconds)
    key = f"ratelimit:ingest:{ip}:{bucket}"
    client = get_client()
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, settings.rate_limit_window_seconds)
    except RedisError:
        return False
    return count > settings.rate_limit_per_minute
