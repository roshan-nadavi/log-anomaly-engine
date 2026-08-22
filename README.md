# LogPulse AI

Cloud-native, event-driven log ingestion and real-time anomaly detection engine. Combines a statistical ML detector (Isolation Forest + sequence-based signal) with an LLM incident agent that generates root-cause summaries, deployed on a self-managed GCP VM instead of managed PaaS (no Vercel/Supabase).

## Architecture

```
Synthetic Log Generator (Faker / Docker script)
        │  HTTP POST
        ▼
FastAPI Ingestion Server (Uvicorn)
        │  publish
        ▼
Redis (Streams, self-hosted in docker-compose)
        │
   ┌────┴─────┐
   ▼          ▼
Rolling      Anomaly Detectors
Window       (Isolation Forest +
Aggregator   sequence/n-gram model)
   │          │
   └────┬─────┘
        │ spike/anomaly triggered
        ▼
LLM Incident Agent (Groq Llama 3.1 / Gemini Flash)
   - retrieves similar past incidents (embedding KNN)
   - emits root cause + severity + remediation + confidence
        ▼
PostgreSQL (self-hosted, logs + incidents)
        │ SSE / WebSockets
        ▼
Next.js Live Dashboard (self-hosted, served via Node/nginx)
```

## Tech stack & hosting

| Layer | Technology | Hosting | Notes |
|---|---|---|---|
| Frontend | Next.js (TypeScript), Tailwind, Recharts | Self-hosted on GCP VM (Node process behind nginx/Caddy) | Replaces Vercel |
| Backend API | Python (FastAPI), Uvicorn | Same GCP VM, Docker container | |
| Queue | Redis (Streams, not plain Pub/Sub) | Self-hosted container on the VM | Durable, replayable, no 10k/day cap |
| Database | PostgreSQL | Self-hosted container on the VM (or Cloud SQL if RAM-constrained) | Replaces Supabase |
| AI / LLM API | Groq API (Llama 3.1) / Gemini Flash | External API, free tier | |
| ML inference | Scikit-learn (Isolation Forest) + n-gram/Markov sequence model | Embedded in backend container | |
| Reverse proxy / TLS | Caddy | Same VM | Automatic HTTPS |
| Compute | GCP Compute Engine `e2-micro` (Always Free) | `us-west1` / `us-central1` / `us-east1` | Trial credits used to build/test on a larger instance first |
| CI/CD | GitHub Actions → GHCR → SSH deploy | | `docker compose pull && up -d` on push |

## Cost target

$0–5/month steady state: GCP `e2-micro` Always Free tier for hosting, free-tier LLM API quotas, no managed PaaS fees. GCP trial credits ($300 / 90 days, ~60 days remaining) used for initial build/load-testing on a larger instance before migrating to the free-forever box.

## Project structure (planned)

```
/ingestion       FastAPI app, log endpoint, Redis producer
/workers         rolling-window aggregator, anomaly detectors, LLM agent worker
/dashboard       Next.js app
/infra           docker-compose.yml, Caddyfile, GitHub Actions workflows
/synthetic-gen   Faker-based log generator / load script
/docs            architecture notes, ADRs
```

---

## Build Phases

### Phase 0 — Infra bootstrap
- Provision GCP `e2-micro` VM (or a larger trial-credit instance for initial dev), open firewall for 80/443/22 only.
- Install Docker + Docker Compose, set up Caddy for automatic HTTPS on a domain/subdomain.
- Set up GitHub repo, GitHub Actions skeleton (build + push images to GHCR).
- **Exit criteria:** empty "hello world" container reachable over HTTPS from the VM via CI-driven deploy.

### Phase 1 — Ingestion pipeline
- Build FastAPI ingestion endpoint (`POST /logs`) with async handling and request validation.
- Stand up Redis (Streams, consumer group) in docker-compose.
- Publish ingested logs onto the stream; confirm sub-10ms response time under load.
- **Exit criteria:** `k6`/Locust load test hitting the endpoint, logs verifiably landing in Redis.

### Phase 2 — Synthetic log generator
- Faker-based generator producing realistic HTTP-style logs (status codes, latency, endpoints, user agents) matching the OTel log data model.
- Dockerized script with configurable rate and an "inject anomaly spike" mode (burst of 5xx / latency spikes).
- **Exit criteria:** generator can run standalone and sustain configurable throughput against the ingestion API.

### Phase 3 — Stream aggregation
- Worker consuming the Redis stream, computing rolling 10s window metrics (throughput, avg latency, status code distribution).
- Persist rolled-up metrics to Postgres.
- **Exit criteria:** metrics table populates continuously and matches expected values against known synthetic input.

### Phase 4 — Anomaly detection (ML)
- Train/fit Isolation Forest on aggregated window features; wire into the worker path.
- Add a second, sequence-aware detector (n-gram/Markov transition model as a lightweight DeepLog-style signal) as an ensemble check.
- Tune thresholds against labeled synthetic anomalies; log detector scores to Postgres.
- **Exit criteria:** injected spikes reliably flagged, both detectors' outputs stored and comparable.

### Phase 5 — LLM incident agent
- On anomaly trigger, extract the surrounding log slice (~30 entries).
- Build the prompt payload (structured JSON output: root cause, severity, remediation, confidence).
- Add retrieval of similar past incidents (embedding KNN over Postgres) as few-shot context.
- Implement circuit breaker + exponential backoff around the LLM API call.
- **Exit criteria:** end-to-end path from injected spike → detector trigger → LLM call → structured incident row in Postgres.

### Phase 6 — Real-time API + streaming to frontend
- REST endpoints for historical metrics, incidents, system status.
- SSE (or WebSocket) endpoint streaming live metrics + incident alerts.
- **Exit criteria:** `curl`/browser can subscribe and see live events during a running synthetic load.

### Phase 7 — Dashboard
- Next.js app: live charts (Recharts), live log scroll, incident feed.
- "Inject Anomaly Spike" button wired to the generator's anomaly mode.
- "Architecture & Cloud Topology" interactive diagram tab.
- Guest/demo mode (no auth) with per-IP rate limiting on demo-triggered actions.
- **Exit criteria:** dashboard deployed on the VM, publicly reachable, guest mode functional end-to-end.

### Phase 8 — Resilience & load testing
- k6/Locust scripted load tests reporting p50/p99 latency and throughput.
- Chaos test: kill Redis and/or LLM API mid-run, confirm circuit breaker recovery, document behavior.
- Rate limiting / abuse protection on public ingestion and demo endpoints.
- **Detector threshold fix**: replace the sequence model's fixed mean+3σ threshold (`workers/detector/main.py`, `SequenceModel.fit`) with SPOT/EVT-based streaming thresholding (Siffer et al., "Anomaly Detection in Streams with Extreme Value Theory," KDD 2017) — fits a Generalized Pareto tail over the anomaly-score distribution instead of assuming it's Gaussian, and recalibrates online rather than only at fixed refit intervals. Directly targets the false-positive behavior observed during Phase 4 verification (windows 7–8 flagged on a too-small 6-window baseline) rather than just widening the baseline as a band-aid.
- **Exit criteria:** documented load test results + a recorded/reproducible chaos-recovery demo + measured false-positive rate before/after the SPOT threshold change.

### Phase 9 — CI/CD & deployment hardening
- Full GitHub Actions pipeline: test → build → push → SSH deploy on merge to main.
- Backup strategy for Postgres (cron + off-box storage, e.g. GCS free tier).
- Basic monitoring (container health checks, disk/memory alerts on the VM).
- **Exit criteria:** a merge to `main` deploys automatically with zero manual steps; backups verified restorable.

### Phase 10 — Polish & resume/demo readiness
- Write up architecture docs / ADRs in `/docs`.
- Record a short demo walkthrough (spike injection → detection → LLM root cause → dashboard update).
- Finalize resume bullets against what was actually built (update stack line to reflect GCP + self-hosted Postgres/Redis instead of Supabase/Vercel).
- **Exit criteria:** public link live, README complete, demo recording in hand.
