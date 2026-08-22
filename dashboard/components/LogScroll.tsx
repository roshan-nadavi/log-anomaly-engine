"use client";

import type { LiveLogEvent } from "@/lib/types";

function statusColor(code: number) {
  if (code >= 500) return "text-status-danger";
  if (code >= 400) return "text-status-warn";
  return "text-status-ok";
}

export default function LogScroll({ logs }: { logs: LiveLogEvent[] }) {
  return (
    // Recessed rather than raised: sits at page-background level with a
    // strong border and an inset shadow, so it reads as a terminal cut
    // into the surface instead of another floating card like every other
    // panel on the page.
    <div className="bg-base border border-edge-strong rounded-lg p-4 shadow-[inset_0_2px_10px_rgba(0,0,0,0.5)]">
      <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">Live log stream</h2>
      <div className="h-64 overflow-y-auto font-mono text-xs space-y-1">
        {logs.length === 0 && <div className="text-neutral-500">Waiting for traffic…</div>}
        {logs.map((log, i) => (
          <div key={i} className="flex gap-2 text-neutral-400 whitespace-nowrap">
            <span className="text-neutral-600">{new Date(log.timestamp).toLocaleTimeString()}</span>
            <span className="text-neutral-500">{log.service}</span>
            <span>{log.method}</span>
            <span className="text-neutral-300">{log.endpoint}</span>
            <span className={statusColor(log.status_code)}>{log.status_code}</span>
            <span className="text-neutral-600">{Math.round(log.latency_ms)}ms</span>
            <span className="truncate text-neutral-500">{log.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
