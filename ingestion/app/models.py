from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


class LogEntry(BaseModel):
    """OTel-aligned log record. Kept intentionally small — extra context
    goes in `attributes` rather than new top-level fields, so the schema
    doesn't need to change as new services/detectors are added."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    severity: Severity = Severity.INFO
    service: str
    endpoint: str
    method: str = "GET"
    status_code: int = Field(ge=100, le=599)
    latency_ms: float = Field(ge=0)
    message: str = ""
    trace_id: Optional[str] = None
    attributes: dict[str, str] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    accepted: int
    stream_id: Optional[str] = None
