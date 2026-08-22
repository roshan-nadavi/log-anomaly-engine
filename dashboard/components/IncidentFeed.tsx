"use client";

import type { Incident, LiveIncidentEvent } from "@/lib/types";

const severityColor: Record<string, string> = {
  low: "bg-status-info/20 text-status-info border-status-info/40",
  medium: "bg-status-warn/20 text-status-warn border-status-warn/40",
  high: "bg-status-high/20 text-status-high border-status-high/40",
  critical: "bg-status-danger/20 text-status-danger border-status-danger/40",
};

interface Item {
  id: number;
  severity: string;
  root_cause: string;
  remediation: string;
  confidence: number;
}

export default function IncidentFeed({
  liveIncidents,
  history,
}: {
  liveIncidents: LiveIncidentEvent[];
  history: Incident[];
}) {
  const liveIds = new Set(liveIncidents.map((i) => i.incident_id));
  const merged: Item[] = [
    ...liveIncidents.map((i) => ({
      id: i.incident_id,
      severity: i.severity,
      root_cause: i.root_cause,
      remediation: i.remediation,
      confidence: i.confidence,
    })),
    ...history.filter((h) => !liveIds.has(h.id)),
  ].slice(0, 20);

  return (
    <div className="bg-panel border border-edge rounded-lg p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">Incidents</h2>
      <div className="flex flex-col gap-3 max-h-[36rem] overflow-y-auto">
        {merged.length === 0 && <div className="text-neutral-500 text-sm">No incidents yet.</div>}
        {merged.map((incident) => (
          <div key={incident.id} className="bg-surface2 rounded-md p-3">
            <div className="flex items-center justify-between mb-1.5">
              <span
                className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border ${
                  severityColor[incident.severity] ?? severityColor.low
                }`}
              >
                {incident.severity}
              </span>
              <span className="text-[11px] text-neutral-500">
                confidence {Math.round(incident.confidence * 100)}%
              </span>
            </div>
            <p className="text-sm text-neutral-200 mb-1.5">{incident.root_cause}</p>
            <p className="text-xs text-neutral-500">{incident.remediation}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
