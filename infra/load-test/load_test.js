// Phase 8 load test — hits the ingestion API at a sustained arrival rate
// and reports p50/p90/p95/p99 latency and throughput. Uses a
// constant-arrival-rate executor rather than a fixed VU count so RATE
// stays accurate regardless of how latency shifts under load (VUs scale
// up automatically to sustain the target rate).
//
// Run via: docker compose --profile tools run --rm load-test
// Override target/rate/duration/mode with env vars, e.g.:
//   docker compose --profile tools run --rm -e RATE=50 -e DURATION=120s load-test
import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";

const TARGET_URL = __ENV.TARGET_URL || "http://ingestion:8000";
const RATE = Number(__ENV.RATE || 10); // requests/sec
const DURATION = __ENV.DURATION || "60s";
const MODE = __ENV.MODE || "batch"; // "single" -> POST /logs, "batch" -> POST /logs/batch
const BATCH_SIZE = Number(__ENV.BATCH_SIZE || 10);

const errorRate = new Rate("errors");
const rateLimitedRate = new Rate("rate_limited");

export const options = {
  scenarios: {
    steady_load: {
      executor: "constant-arrival-rate",
      rate: RATE,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: Math.max(10, RATE * 2),
      maxVUs: Math.max(50, RATE * 10),
    },
  },
  // Explicit p50/p99 in the printed summary, matching what Phase 8 asks
  // this test to report (k6's default summary only shows p90/p95).
  summaryTrendStats: ["avg", "min", "med", "max", "p(50)", "p(90)", "p(95)", "p(99)"],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "errors": ["rate<0.01"],
  },
};

const SERVICES = ["checkout-api", "auth-service", "search-api", "recommendation-engine"];
const ENDPOINTS = ["/api/v1/orders", "/api/v1/login", "/api/v1/search", "/api/v1/recommend", "/api/v1/cart"];
const METHODS = ["GET", "GET", "GET", "POST", "PUT"];

function randomLog() {
  return {
    service: SERVICES[Math.floor(Math.random() * SERVICES.length)],
    endpoint: ENDPOINTS[Math.floor(Math.random() * ENDPOINTS.length)],
    method: METHODS[Math.floor(Math.random() * METHODS.length)],
    status_code: 200,
    latency_ms: Math.random() * 200 + 15,
    message: "load test entry",
  };
}

export function setup() {
  const res = http.get(`${TARGET_URL}/health`);
  if (res.status !== 200) {
    throw new Error(`ingestion not healthy before load test started: HTTP ${res.status}`);
  }
}

export default function () {
  const url = MODE === "single" ? `${TARGET_URL}/logs` : `${TARGET_URL}/logs/batch`;
  const body = MODE === "single" ? randomLog() : Array.from({ length: BATCH_SIZE }, randomLog);

  const res = http.post(url, JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });

  const ok = res.status === 202;
  check(res, { "accepted (202)": () => ok });
  errorRate.add(!ok);
  rateLimitedRate.add(res.status === 429);
}
