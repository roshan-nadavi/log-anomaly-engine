"""Thin REST client for Gemini chat completion + embeddings.

Uses raw httpx calls against the Gemini API instead of the SDK to keep
the dependency footprint small. Each call type (chat, embeddings) has
its own circuit breaker since they're different endpoints with
independent failure modes (e.g. the embeddings quota can be exhausted
while chat is still healthy). Transient errors (429, 5xx) are retried
with exponential backoff via tenacity; anything else (4xx auth/schema
errors) fails immediately since retrying won't help.

Model IDs are configurable via env vars — verify the defaults against
the current Gemini API docs before relying on them, since model names
and availability change over time.
"""
import os

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from circuit_breaker import CircuitBreaker, CircuitOpenError
from common.db import EMBEDDING_DIM

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# gemini-2.0-flash/text-embedding-004 (the original defaults here) 404'd
# against a live key as of 2026-08 — the model lineup moves fast, so
# these use a stable alias and the current non-preview embedding model.
# Re-verify against GET /v1beta/models?key=... if these ever 404 again.
GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-flash-latest")
GEMINI_EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "20"))

CHAT_FAILURE_THRESHOLD = int(os.environ.get("LLM_CHAT_FAILURE_THRESHOLD", "5"))
CHAT_RESET_TIMEOUT = float(os.environ.get("LLM_CHAT_RESET_TIMEOUT", "60"))
EMBED_FAILURE_THRESHOLD = int(os.environ.get("LLM_EMBED_FAILURE_THRESHOLD", "5"))
EMBED_RESET_TIMEOUT = float(os.environ.get("LLM_EMBED_RESET_TIMEOUT", "60"))

chat_breaker = CircuitBreaker(CHAT_FAILURE_THRESHOLD, CHAT_RESET_TIMEOUT)
embed_breaker = CircuitBreaker(EMBED_FAILURE_THRESHOLD, EMBED_RESET_TIMEOUT)


class RetryableError(Exception):
    """Transient API failure (rate limit / server error) worth retrying."""


def _raise_for_retry(resp: httpx.Response) -> None:
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RetryableError(f"transient LLM API error: {resp.status_code} {resp.text[:200]}")
    resp.raise_for_status()


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(RetryableError),
)
def _post(url: str, json_body: dict) -> dict:
    resp = httpx.post(url, json=json_body, timeout=REQUEST_TIMEOUT)
    _raise_for_retry(resp)
    return resp.json()


def chat_complete(prompt: str) -> str:
    if not chat_breaker.allow_request():
        raise CircuitOpenError("chat completion circuit is open")
    url = f"{GEMINI_BASE_URL}/{GEMINI_CHAT_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    try:
        data = _post(url, body)
    except Exception:
        chat_breaker.record_failure()
        raise
    chat_breaker.record_success()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def embed_text(text: str) -> list[float]:
    if not embed_breaker.allow_request():
        raise CircuitOpenError("embedding circuit is open")
    url = f"{GEMINI_BASE_URL}/{GEMINI_EMBED_MODEL}:embedContent?key={GEMINI_API_KEY}"
    body = {
        "content": {"parts": [{"text": text}]},
        "taskType": "SEMANTIC_SIMILARITY",
        "outputDimensionality": EMBEDDING_DIM,
    }
    try:
        data = _post(url, body)
    except Exception:
        embed_breaker.record_failure()
        raise
    embed_breaker.record_success()
    return data["embedding"]["values"]
