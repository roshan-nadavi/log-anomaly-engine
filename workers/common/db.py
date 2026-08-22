import os

import psycopg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://logpulse:logpulse@postgres:5432/logpulse",
)

EMBEDDING_DIM = 768  # matches Gemini text-embedding-004 output size

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS window_metrics (
    id SERIAL PRIMARY KEY,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    event_count INTEGER NOT NULL,
    avg_latency_ms DOUBLE PRECISION NOT NULL,
    p95_latency_ms DOUBLE PRECISION NOT NULL,
    status_2xx INTEGER NOT NULL,
    status_4xx INTEGER NOT NULL,
    status_5xx INTEGER NOT NULL,
    error_rate DOUBLE PRECISION NOT NULL,
    unique_services INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS anomalies (
    id SERIAL PRIMARY KEY,
    window_id INTEGER REFERENCES window_metrics(id),
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    iso_forest_score DOUBLE PRECISION,
    iso_forest_flag BOOLEAN NOT NULL,
    sequence_score DOUBLE PRECISION,
    sequence_flag BOOLEAN NOT NULL,
    combined_flag BOOLEAN NOT NULL,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomalies_combined_flag
    ON anomalies (combined_flag, created_at);

CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    anomaly_id INTEGER REFERENCES anomalies(id),
    window_id INTEGER REFERENCES window_metrics(id),
    root_cause TEXT NOT NULL,
    severity TEXT NOT NULL,
    remediation TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    log_slice JSONB,
    similar_incident_ids INTEGER[],
    raw_llm_response JSONB,
    embedding vector({EMBEDDING_DIM}),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
# No ivfflat/hnsw index on incidents.embedding yet: at demo-scale
# incident volume (dozens to low hundreds of rows) a plain sequential
# scan with `ORDER BY embedding <=> query LIMIT k` is fast enough, and
# ivfflat needs a meaningful amount of data to train useful clusters.
# Add one once incident volume actually justifies it.


def get_conn():
    return psycopg.connect(DATABASE_URL, autocommit=True)


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
