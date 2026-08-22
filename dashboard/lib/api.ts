import type { Anomaly, Incident, SpikeType, StatusResponse, WindowMetric } from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status}`);
  }
  return res.json();
}

export const fetchStatus = () => getJSON<StatusResponse>("/status");

export const fetchWindows = (limit = 50) =>
  getJSON<WindowMetric[]>(`/metrics/windows?limit=${limit}`);

export const fetchIncidents = (limit = 20) =>
  getJSON<Incident[]>(`/incidents?limit=${limit}`);

export const fetchAnomalies = (limit = 50) =>
  getJSON<Anomaly[]>(`/anomalies?limit=${limit}`);

export const fetchSpikeTypes = () => getJSON<SpikeType[]>("/demo/spike-types");

export async function injectSpike(
  spikeType: string,
  size: number,
  durationSeconds: number
): Promise<{ injected: number; spike_type: string; duration_seconds: number }> {
  const params = new URLSearchParams({
    spike_type: spikeType,
    size: String(size),
    duration_seconds: String(durationSeconds),
  });
  const res = await fetch(`${API_BASE_URL}/demo/inject-spike?${params}`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `inject-spike failed: ${res.status}`);
  }
  return res.json();
}
