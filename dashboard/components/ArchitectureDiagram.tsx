"use client";

import { useState } from "react";
import { colors } from "@/lib/colors";

interface Node {
  id: string;
  label: string;
  x: number;
  y: number;
  description: string;
}

const W = 180;
const H = 60;

const nodes: Node[] = [
  { id: "gen", label: "Synthetic Log Generator", x: 20, y: 20, description: "Faker-based script producing realistic HTTP-style logs. Supports a scripted anomaly burst, plus this dashboard's Inject Anomaly Spike button triggers one server-side on demand." },
  { id: "ingest", label: "FastAPI Ingestion", x: 230, y: 20, description: "Async POST /logs and /logs/batch. Publishes each entry onto a Redis Stream and returns in well under 10ms — the write path never blocks on downstream processing." },
  { id: "redis", label: "Redis Streams", x: 440, y: 20, description: "Durable, replayable event queue decoupling ingestion from processing. Bounded with approximate MAXLEN trimming so it can't grow past available memory on a small VM." },
  { id: "agg", label: "Rolling Window Aggregator", x: 230, y: 140, description: "Consumer-group worker computing 5-10s tumbling window features: throughput, latency percentiles, status code mix, and the raw log-key sequence." },
  { id: "det", label: "Ensemble Detector", x: 440, y: 140, description: "Isolation Forest (aggregate features) + a Markov transition model over log-key sequences (DeepLog-inspired), combined as an OR-ensemble so either signal can flag a window." },
  { id: "agent", label: "LLM Incident Agent", x: 440, y: 260, description: "On a flagged anomaly: pulls the surrounding log slice, retrieves similar past incidents via pgvector cosine KNN, and asks Gemini for a structured root-cause report. Circuit breaker + exponential backoff around the API call." },
  { id: "pg", label: "PostgreSQL + pgvector", x: 230, y: 260, description: "Stores window metrics, anomaly scores, and incident reports (with embeddings for similarity search) — the durable system of record." },
  { id: "api", label: "Query & Streaming API", x: 20, y: 260, description: "Async FastAPI service: REST endpoints for history, plus an SSE stream fanning out live windows, incidents, and raw logs to every connected dashboard." },
  { id: "dash", label: "Next.js Dashboard", x: 20, y: 140, description: "This app — live charts, a live log scroll, the incident feed, and the Inject Anomaly Spike demo control. Self-hosted, not on Vercel." },
];

const edges: [string, string][] = [
  ["gen", "ingest"],
  ["ingest", "redis"],
  ["redis", "agg"],
  ["agg", "det"],
  ["agg", "pg"],
  ["det", "agent"],
  ["det", "pg"],
  ["agent", "pg"],
  ["redis", "api"],
  ["pg", "api"],
  ["api", "dash"],
];

function center(n: Node) {
  return { x: n.x + W / 2, y: n.y + H / 2 };
}

export default function ArchitectureDiagram() {
  const [selected, setSelected] = useState<Node>(nodes[0]);
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 bg-panel border border-edge rounded-lg p-4 overflow-x-auto">
        <svg viewBox="0 0 660 380" className="w-full min-w-[620px]">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={colors.edgeStrong} />
            </marker>
          </defs>

          {edges.map(([from, to], i) => {
            const a = center(byId[from]);
            const b = center(byId[to]);
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={colors.edgeStrong}
                strokeWidth={1.5}
                markerEnd="url(#arrow)"
              />
            );
          })}

          {nodes.map((n) => (
            <g key={n.id} onClick={() => setSelected(n)} className="cursor-pointer">
              <rect
                x={n.x}
                y={n.y}
                width={W}
                height={H}
                rx={8}
                fill={selected.id === n.id ? colors.selected : colors.panel}
                stroke={selected.id === n.id ? colors.accent : colors.edge}
                strokeWidth={selected.id === n.id ? 2 : 1}
              />
              <foreignObject x={n.x + 8} y={n.y + 8} width={W - 16} height={H - 16}>
                <div className="text-[11px] leading-tight text-neutral-200 flex items-center h-full">
                  {n.label}
                </div>
              </foreignObject>
            </g>
          ))}
        </svg>
      </div>
      <div className="bg-panel border border-edge rounded-lg p-4">
        <h3 className="text-sm font-medium text-neutral-200 mb-2">{selected.label}</h3>
        <p className="text-sm text-neutral-400">{selected.description}</p>
      </div>
    </div>
  );
}
