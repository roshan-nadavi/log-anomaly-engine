"""Raw log parsers — normalize free-text/log-line input from arbitrary
sources (syslog, generic app logs, JSON logs, unstructured text) into
the same LogEntry schema the rest of the pipeline already speaks, so
nothing downstream (aggregator, detector, agent, dashboard) needs to
know or care where an entry originally came from. One canonical schema,
an adapter at the ingestion boundary — not a second code path.

Tried in order per line; first structured match wins, freeform keyword
heuristics catch everything else. Fields a source format has no real
value for (status_code, latency_ms — meaningful only for HTTP-shaped
logs) are filled in from SEVERITY_DEFAULTS below rather than left
blank, since the whole detection pipeline (Isolation Forest features,
error-rate) is built around those two fields.

Known, deliberate limitation: synthetic and real (HTTP) latency/status
values land in the same window features today, so a burst of non-HTTP
logs sharing a window with real request traffic blends synthetic and
real numbers into one distribution. Every normalized entry is tagged
attributes.source_format + attributes.synthetic_metrics=true
specifically so a future revision of the aggregator could stratify or
exclude synthetic entries from latency-sensitive features — not done
here, to keep this change scoped to ingestion rather than forking
aggregation/detection for a second schema.
"""
import json
import re
from datetime import datetime, timezone

from app.models import LogEntry, Severity

SEVERITY_DEFAULTS: dict[Severity, tuple[int, float]] = {
    Severity.FATAL: (500, 5000.0),
    Severity.ERROR: (500, 2000.0),
    Severity.WARN: (400, 500.0),
    Severity.INFO: (200, 50.0),
    Severity.DEBUG: (200, 10.0),
}

_LEVEL_ALIASES = {
    "TRACE": Severity.DEBUG, "DEBUG": Severity.DEBUG,
    "INFO": Severity.INFO, "NOTICE": Severity.INFO,
    "WARN": Severity.WARN, "WARNING": Severity.WARN,
    "ERROR": Severity.ERROR, "ERR": Severity.ERROR, "SEVERE": Severity.ERROR,
    "FATAL": Severity.FATAL, "CRITICAL": Severity.FATAL, "CRIT": Severity.FATAL, "EMERG": Severity.FATAL,
}

# "2026-08-22T10:15:32Z ERROR [OrderService] connection timeout" or
# "2026-08-22 10:15:32,123 WARN  PaymentWorker - retrying"
_APP_LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?)\s+"
    r"(?P<level>[A-Za-z]+)\s+"
    r"(?:\[(?P<component1>[^\]]+)\]|(?P<component2>[\w.-]+)\s+-)?\s*"
    r"(?P<message>.*)$"
)

# RFC3164-ish syslog: "<PRI>Mon DD HH:MM:SS host process[pid]: message".
# No year in RFC3164 timestamps, so we don't attempt to parse it —
# ingestion time is used instead (see parse_syslog).
_SYSLOG_RE = re.compile(
    r"^(?:<(?P<pri>\d+)>)?"
    r"(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<process>[\w./-]+?)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<message>.*)$"
)

_JSON_LEVEL_KEYS = ("level", "severity", "lvl", "loglevel")
_JSON_MESSAGE_KEYS = ("message", "msg", "log", "text")
_JSON_SERVICE_KEYS = ("service", "logger", "component", "app", "application")
_JSON_TIME_KEYS = ("timestamp", "time", "ts", "@timestamp")

_FREEFORM_ERROR_TOKENS = ("error", "exception", "fail", "panic", "fatal", "traceback")
_FREEFORM_WARN_TOKENS = ("warn", "deprecated", "retry", "retrying")


def _severity_from_token(token: str) -> Severity:
    return _LEVEL_ALIASES.get(token.strip().upper(), Severity.INFO)


def _severity_from_syslog_pri(pri: str | None) -> Severity:
    if pri is None:
        return Severity.INFO
    level = int(pri) % 8  # low 3 bits of PRI = severity (RFC 5424)
    return {0: Severity.FATAL, 1: Severity.FATAL, 2: Severity.FATAL,
            3: Severity.ERROR, 4: Severity.WARN, 5: Severity.INFO,
            6: Severity.INFO, 7: Severity.DEBUG}[level]


def _try_parse_timestamp(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _finalize(severity: Severity, service: str, message: str,
              timestamp: datetime | None, source_format: str) -> LogEntry:
    status_code, latency_ms = SEVERITY_DEFAULTS[severity]
    return LogEntry(
        timestamp=timestamp or datetime.now(timezone.utc),
        severity=severity,
        service=service,
        endpoint=f"raw:{service}",
        method="LOG",
        status_code=status_code,
        latency_ms=latency_ms,
        message=message[:2000],
        attributes={"source_format": source_format, "synthetic_metrics": "true"},
    )


def parse_json_log(line: str, default_service: str) -> LogEntry | None:
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    level_token = next((data[k] for k in _JSON_LEVEL_KEYS if k in data), "INFO")
    message = next((data[k] for k in _JSON_MESSAGE_KEYS if k in data), line)
    service = next((data[k] for k in _JSON_SERVICE_KEYS if k in data), default_service)
    ts_raw = next((data[k] for k in _JSON_TIME_KEYS if k in data), None)
    timestamp = _try_parse_timestamp(str(ts_raw)) if ts_raw else None

    return _finalize(_severity_from_token(str(level_token)), str(service), str(message), timestamp, "json")


def parse_syslog(line: str, default_service: str) -> LogEntry | None:
    m = _SYSLOG_RE.match(line.strip())
    if not m:
        return None
    severity = _severity_from_syslog_pri(m.group("pri"))
    service = m.group("process") or default_service
    return _finalize(severity, service, m.group("message"), None, "syslog")


def parse_app_log(line: str, default_service: str) -> LogEntry | None:
    m = _APP_LOG_RE.match(line.strip())
    if not m:
        return None
    severity = _severity_from_token(m.group("level"))
    service = m.group("component1") or m.group("component2") or default_service
    timestamp = _try_parse_timestamp(m.group("ts"))
    return _finalize(severity, service, m.group("message"), timestamp, "app_log")


def parse_freeform(line: str, default_service: str) -> LogEntry:
    lowered = line.lower()
    if any(tok in lowered for tok in _FREEFORM_ERROR_TOKENS):
        severity = Severity.ERROR
    elif any(tok in lowered for tok in _FREEFORM_WARN_TOKENS):
        severity = Severity.WARN
    else:
        severity = Severity.INFO
    return _finalize(severity, default_service, line, None, "freeform")


PARSERS = (parse_json_log, parse_syslog, parse_app_log)


def normalize_line(line: str, default_service: str = "unknown") -> LogEntry:
    """Try each structured parser in turn; fall back to freeform keyword
    heuristics if nothing matches. Always returns a valid LogEntry."""
    line = line.rstrip("\n")
    for parser in PARSERS:
        result = parser(line, default_service)
        if result is not None:
            return result
    return parse_freeform(line, default_service)
