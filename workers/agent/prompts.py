"""Prompt construction for the incident agent.

`build_situation_summary` produces the text used for embedding — both
when querying for similar past incidents and when storing a new
incident's embedding — so retrieval is matching on "what does this
anomaly look like" (symptoms) rather than on a prior model's stated
conclusion, which is what actually makes the KNN lookup useful as
few-shot context instead of just retrieving whatever was labeled the
same severity by chance.
"""
import json

RESPONSE_SCHEMA_INSTRUCTIONS = """Respond with ONLY a JSON object (no markdown fences, no prose) matching exactly this shape:
{
  "root_cause": "<one or two sentence explanation of the most likely cause>",
  "severity": "<one of: low, medium, high, critical>",
  "remediation": "<concrete, actionable recommended steps>",
  "confidence": <float between 0 and 1, your confidence in this diagnosis>
}"""


def format_log_slice(log_slice: list[dict]) -> str:
    lines = []
    for entry in log_slice:
        lines.append(
            f"[{entry.get('timestamp', '?')}] {entry.get('severity', '?'):<5} "
            f"{entry.get('service', '?')} {entry.get('method', '?')} "
            f"{entry.get('endpoint', '?')} -> {entry.get('status_code', '?')} "
            f"({entry.get('latency_ms', '?')}ms) {entry.get('message', '')}"
        )
    return "\n".join(lines)


def build_situation_summary(features: dict, log_slice: list[dict]) -> str:
    error_messages = [
        e.get("message", "") for e in log_slice if int(e.get("status_code", 0)) >= 500
    ][:5]
    return (
        f"event_count={features.get('event_count')} "
        f"error_rate={features.get('error_rate'):.3f} "
        f"avg_latency_ms={features.get('avg_latency_ms'):.1f} "
        f"p95_latency_ms={features.get('p95_latency_ms'):.1f} "
        f"status_4xx={features.get('status_4xx')} status_5xx={features.get('status_5xx')} "
        f"sample_errors={' | '.join(error_messages)}"
    )


def build_prompt(features: dict, log_slice: list[dict], similar_incidents: list[dict]) -> str:
    sections = [
        "You are an SRE incident triage assistant analyzing a detected anomaly "
        "in a log ingestion pipeline. Determine the most likely root cause.",
        "",
        "## Window metrics",
        json.dumps(features, indent=2),
        "",
        "## Log slice (up to 30 entries from the anomalous window, "
        "error entries prioritized)",
        format_log_slice(log_slice),
    ]

    if similar_incidents:
        sections += ["", "## Similar past incidents (for reference, most similar first)"]
        for inc in similar_incidents:
            sections.append(
                f"- severity={inc['severity']} root_cause=\"{inc['root_cause']}\" "
                f"remediation=\"{inc['remediation']}\""
            )

    sections += ["", RESPONSE_SCHEMA_INSTRUCTIONS]
    return "\n".join(sections)
