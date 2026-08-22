"""Synthetic HTTP-log generator for LogPulse.

Sends batches of Faker-generated log entries to the ingestion API at a
configurable rate, with an optional anomaly burst partway through the
run (elevated 5xx rate + latency spike) to exercise the detectors in
later phases.
"""
import argparse
import asyncio
import random
import time
from datetime import datetime, timezone

import httpx
from faker import Faker

fake = Faker()

SERVICES = ["checkout-api", "auth-service", "search-api", "recommendation-engine"]
ENDPOINTS = ["/api/v1/orders", "/api/v1/login", "/api/v1/search", "/api/v1/recommend", "/api/v1/cart"]
METHODS = ["GET", "GET", "GET", "POST", "PUT"]
NORMAL_STATUS_WEIGHTS = [(200, 0.90), (201, 0.05), (404, 0.03), (500, 0.02)]


def _weighted_status(weights: list[tuple[int, float]]) -> int:
    r = random.random()
    cumulative = 0.0
    for status, weight in weights:
        cumulative += weight
        if r <= cumulative:
            return status
    return weights[-1][0]


def make_log_entry(anomalous: bool) -> dict:
    if anomalous:
        status = _weighted_status([(500, 0.55), (503, 0.25), (200, 0.20)])
        latency = random.uniform(800, 4000)
        severity = "ERROR" if status >= 500 else "WARN"
    else:
        status = _weighted_status(NORMAL_STATUS_WEIGHTS)
        latency = random.uniform(15, 250)
        severity = "ERROR" if status >= 500 else "INFO"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": severity,
        "service": random.choice(SERVICES),
        "endpoint": random.choice(ENDPOINTS),
        "method": random.choice(METHODS),
        "status_code": status,
        "latency_ms": round(latency, 2),
        "message": fake.sentence(nb_words=8),
        "trace_id": fake.uuid4(),
        "attributes": {
            "client_ip": fake.ipv4(),
            "user_agent": fake.user_agent(),
        },
    }


async def run(target_url: str, rate: float, duration: int, batch_size: int,
              anomaly_start: int | None, anomaly_duration: int) -> None:
    interval = batch_size / rate if rate > 0 else 0
    async with httpx.AsyncClient(timeout=5.0) as client:
        elapsed = 0.0
        sent = 0
        start = time.monotonic()
        while elapsed < duration:
            in_anomaly_window = (
                anomaly_start is not None
                and anomaly_start <= elapsed < anomaly_start + anomaly_duration
            )
            batch = [make_log_entry(in_anomaly_window) for _ in range(batch_size)]
            try:
                resp = await client.post(f"{target_url}/logs/batch", json=batch)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"[generator] request failed: {exc}")
            else:
                sent += len(batch)
                tag = " [ANOMALY]" if in_anomaly_window else ""
                print(f"[generator] sent {len(batch)} logs (total {sent}){tag}")

            await asyncio.sleep(max(interval, 0))
            elapsed = time.monotonic() - start

    print(f"[generator] done. sent {sent} logs over {duration}s")


def main():
    parser = argparse.ArgumentParser(description="LogPulse synthetic log generator")
    parser.add_argument("--target-url", default="http://localhost:8000")
    parser.add_argument("--rate", type=float, default=20.0, help="logs per second")
    parser.add_argument("--duration", type=int, default=60, help="run duration in seconds")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--anomaly-start", type=int, default=None,
                         help="seconds into the run to begin an anomaly burst")
    parser.add_argument("--anomaly-duration", type=int, default=15,
                         help="length of the anomaly burst in seconds")
    args = parser.parse_args()

    asyncio.run(run(
        target_url=args.target_url,
        rate=args.rate,
        duration=args.duration,
        batch_size=args.batch_size,
        anomaly_start=args.anomaly_start,
        anomaly_duration=args.anomaly_duration,
    ))


if __name__ == "__main__":
    main()
