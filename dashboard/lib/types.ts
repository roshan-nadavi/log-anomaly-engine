export interface WindowMetric {
  id?: number;
  window_id?: number;
  window_start: string;
  window_end: string;
  event_count: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  status_2xx: number;
  status_4xx: number;
  status_5xx: number;
  error_rate: number;
  unique_services: number;
}

export interface Anomaly {
  id: number;
  window_id: number;
  window_start: string;
  window_end: string;
  iso_forest_score: number | null;
  iso_forest_flag: boolean;
  sequence_score: number | null;
  sequence_flag: boolean;
  combined_flag: boolean;
}

export interface Incident {
  id: number;
  anomaly_id: number;
  window_id: number;
  root_cause: string;
  severity: "low" | "medium" | "high" | "critical";
  remediation: string;
  confidence: number;
  created_at: string;
}

export interface LiveIncidentEvent {
  incident_id: number;
  anomaly_id: number;
  window_id: number;
  severity: Incident["severity"];
  confidence: number;
  root_cause: string;
  remediation: string;
}

export interface LiveLogEvent {
  timestamp: string;
  severity: string;
  service: string;
  method: string;
  endpoint: string;
  status_code: number;
  latency_ms: number;
  message: string;
}

export interface SpikeType {
  id: string;
  label: string;
  description: string;
}

export interface StatusResponse {
  redis_ok: boolean;
  window_count: number;
  incident_count: number;
  flagged_anomaly_count: number;
  last_window_at: string | null;
}
