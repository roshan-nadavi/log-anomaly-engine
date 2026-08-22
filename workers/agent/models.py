from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentReport(BaseModel):
    root_cause: str
    severity: Severity
    remediation: str
    confidence: float = Field(ge=0, le=1)
