"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { colors } from "@/lib/colors";
import type { WindowMetric } from "@/lib/types";

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString([], { minute: "2-digit", second: "2-digit" });
}

export default function MetricsChart({ windows }: { windows: WindowMetric[] }) {
  const data = windows.map((w) => ({
    time: fmtTime(w.window_start),
    p95: Math.round(w.p95_latency_ms),
    avg: Math.round(w.avg_latency_ms),
    errorRate: Math.round(w.error_rate * 1000) / 10,
    throughput: w.event_count,
  }));

  return (
    <div className="bg-panel border border-edge rounded-lg p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">Latency &amp; error rate (live)</h2>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.edge} />
            <XAxis dataKey="time" stroke={colors.axis} fontSize={11} minTickGap={30} />
            <YAxis yAxisId="latency" stroke={colors.axis} fontSize={11} width={40} />
            <YAxis yAxisId="error" orientation="right" stroke={colors.axis} fontSize={11} width={40} unit="%" />
            <Tooltip
              contentStyle={{ background: colors.panel, border: `1px solid ${colors.edge}`, fontSize: 12 }}
              labelStyle={{ color: colors.text }}
            />
            <Line yAxisId="latency" type="monotone" dataKey="p95" stroke={colors.accent} dot={false} name="p95 latency (ms)" />
            <Line
              yAxisId="latency"
              type="monotone"
              dataKey="avg"
              stroke={colors.muted}
              dot={false}
              name="avg latency (ms)"
              strokeDasharray="4 3"
            />
            <Line yAxisId="error" type="monotone" dataKey="errorRate" stroke={colors.status.danger} dot={false} name="error rate (%)" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="h-28 mt-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={colors.edge} />
            <XAxis dataKey="time" stroke={colors.axis} fontSize={11} minTickGap={30} />
            <YAxis stroke={colors.axis} fontSize={11} width={40} />
            <Tooltip
              contentStyle={{ background: colors.panel, border: `1px solid ${colors.edge}`, fontSize: 12 }}
              labelStyle={{ color: colors.text }}
            />
            <Area type="monotone" dataKey="throughput" stroke={colors.status.ok} fill={`${colors.status.ok}33`} name="events/window" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
