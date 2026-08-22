import redis

# A dropped Redis connection (container restart, brief network blip) is an
# expected, transient failure that every consumer loop should absorb by
# retrying, not a reason to crash the process — see Phase 8 chaos-test
# findings. redis-py's connection pool reconnects transparently on the
# next call, so callers just need to catch these, back off, and retry.
TRANSIENT_REDIS_ERRORS = (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)


def ensure_group(client: "redis.Redis", stream: str, group: str) -> None:
    try:
        client.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def read_batch(client, stream, group, consumer, count=500, block_ms=2000):
    resp = client.xreadgroup(
        groupname=group,
        consumername=consumer,
        streams={stream: ">"},
        count=count,
        block=block_ms,
    )
    if not resp:
        return []
    _, messages = resp[0]
    return messages


def ack(client, stream, group, ids):
    if ids:
        client.xack(stream, group, *ids)
