"use client";

import { useEffect, useState } from "react";
import ArchitectureDiagram from "@/components/ArchitectureDiagram";
import IncidentFeed from "@/components/IncidentFeed";
import InjectSpikeButton from "@/components/InjectSpikeButton";
import LogScroll from "@/components/LogScroll";
import MetricsChart from "@/components/MetricsChart";
import StatusBar from "@/components/StatusBar";
import { fetchIncidents, fetchStatus, fetchWindows } from "@/lib/api";
import type { Incident, StatusResponse, WindowMetric } from "@/lib/types";
import { useLiveStream } from "@/lib/useLiveStream";

function mergeWindows(history: WindowMetric[], live: WindowMetric[]): WindowMetric[] {
  const byKey = new Map<string, WindowMetric>();
  for (const w of history) byKey.set(w.window_start, w);
  for (const w of live) byKey.set(w.window_start, w);
  return Array.from(byKey.values())
    .sort((a, b) => a.window_start.localeCompare(b.window_start))
    .slice(-60);
}

export default function Home() {
  const [tab, setTab] = useState<"dashboard" | "architecture">("dashboard");
  const [history, setHistory] = useState<WindowMetric[]>([]);
  const [incidentHistory, setIncidentHistory] = useState<Incident[]>([]);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const live = useLiveStream();

  useEffect(() => {
    fetchWindows(60)
      .then((rows) => setHistory([...rows].reverse()))
      .catch(() => {});
    fetchIncidents(20)
      .then(setIncidentHistory)
      .catch(() => {});
    fetchStatus()
      .then(setStatus)
      .catch(() => {});

    const interval = setInterval(() => {
      fetchStatus().then(setStatus).catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  const windows = mergeWindows(history, live.windows);

  return (
    <main className="relative z-10 min-h-screen px-6 py-6 max-w-7xl mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">LogPulse AI</h1>
          <p className="text-sm text-muted">
            Public demo — no login required. Live event-driven log anomaly detection.
          </p>
        </div>
        <InjectSpikeButton />
      </header>

      <StatusBar status={status} connectionState={live.status} />

      <nav className="flex gap-2 my-4">
        <button
          onClick={() => setTab("dashboard")}
          className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
            tab === "dashboard"
              ? "bg-surface2 text-accent border border-accent/30"
              : "text-muted border border-transparent hover:text-neutral-200"
          }`}
        >
          Dashboard
        </button>
        <button
          onClick={() => setTab("architecture")}
          className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
            tab === "architecture"
              ? "bg-surface2 text-accent border border-accent/30"
              : "text-muted border border-transparent hover:text-neutral-200"
          }`}
        >
          Architecture &amp; Cloud Topology
        </button>
      </nav>

      {tab === "dashboard" ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 flex flex-col gap-4">
            <MetricsChart windows={windows} />
            <LogScroll logs={live.logs} />
          </div>
          <IncidentFeed liveIncidents={live.incidents} history={incidentHistory} />
        </div>
      ) : (
        <ArchitectureDiagram />
      )}
    </main>
  );
}
