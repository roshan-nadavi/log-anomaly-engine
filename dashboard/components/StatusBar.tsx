import type { StatusResponse } from "@/lib/types";
import type { ConnectionState } from "@/lib/useLiveStream";

export default function StatusBar({
  status,
  connectionState,
}: {
  status: StatusResponse | null;
  connectionState: ConnectionState;
}) {
  const liveDot =
    connectionState === "open"
      ? "bg-status-ok"
      : connectionState === "connecting"
      ? "bg-status-warn"
      : "bg-status-danger";
  const liveLabel =
    connectionState === "open" ? "Live" : connectionState === "connecting" ? "Connecting…" : "Disconnected";

  const redisDot = !status ? "bg-neutral-600" : status.redis_ok ? "bg-status-ok" : "bg-status-danger";
  const anomalyCount = status?.flagged_anomaly_count ?? null;
  const hasAnomalies = (anomalyCount ?? 0) > 0;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-[2fr_1fr] gap-3">
      {/* hero: the one number a visitor should notice first */}
      <div
        className={`rounded-lg border px-4 py-3 flex items-center justify-between transition-colors ${
          hasAnomalies ? "bg-status-danger/10 border-status-danger/40" : "bg-surface2 border-edge-strong"
        }`}
      >
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-widest text-muted">Flagged anomalies</div>
          <div className={`font-mono text-3xl font-semibold ${hasAnomalies ? "text-status-danger" : "text-neutral-100"}`}>
            {anomalyCount ?? "—"}
          </div>
        </div>
        {hasAnomalies && <span className="h-2.5 w-2.5 rounded-full bg-status-danger animate-pulse" />}
      </div>

      <div className="flex flex-col gap-2">
        {/* system health: status flags, not metrics — compact strip */}
        <div className="bg-panel border border-edge rounded-lg px-4 py-2.5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${liveDot}`} />
            <span className="text-xs text-neutral-300">{liveLabel}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${redisDot}`} />
            <span className="text-xs text-neutral-300">
              Redis {status ? (status.redis_ok ? "ok" : "degraded") : "—"}
            </span>
          </div>
        </div>
        {/* least urgent: muted counters */}
        <div className="px-1 text-xs text-neutral-500">
          {status ? `${status.window_count} windows · ${status.incident_count} incidents` : "—"}
        </div>
      </div>
    </div>
  );
}
