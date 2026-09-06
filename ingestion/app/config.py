from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379/0"
    stream_name: str = "logs:raw"
    # Approximate trim cap so an idle/crashed consumer can't grow the
    # stream unbounded and OOM a 1GB e2-micro box. ~200k entries at a
    # few hundred bytes each stays well under 1GB with headroom for
    # Postgres + the app processes running alongside it.
    stream_maxlen: int = 200_000
    # Per-IP request rate limit on the ingestion endpoints — this is the
    # only fully open, unauthenticated write path into the system, so
    # it's the one that most needs abuse protection.
    rate_limit_per_minute: int = 600
    rate_limit_window_seconds: int = 60
    # Caps a single /logs/batch request's entry count, independent of the
    # per-minute request-rate limit above — without this, one request
    # could carry an arbitrarily large payload regardless of how often
    # the client is allowed to POST.
    batch_max_size: int = 500

    class Config:
        env_file = ".env"


settings = Settings()
