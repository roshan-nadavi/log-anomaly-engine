"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "./api";
import type { LiveIncidentEvent, LiveLogEvent, WindowMetric } from "./types";

const MAX_WINDOWS = 60;
const MAX_LOGS = 200;
const MAX_LIVE_INCIDENTS = 50;

export type ConnectionState = "connecting" | "open" | "error";

interface LiveState {
  status: ConnectionState;
  windows: WindowMetric[];
  incidents: LiveIncidentEvent[];
  logs: LiveLogEvent[];
}

export function useLiveStream() {
  const [state, setState] = useState<LiveState>({
    status: "connecting",
    windows: [],
    incidents: [],
    logs: [],
  });
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const source = new EventSource(`${API_BASE_URL}/stream/live`);
    sourceRef.current = source;

    source.onopen = () => setState((s) => ({ ...s, status: "open" }));
    source.onerror = () => setState((s) => ({ ...s, status: "error" }));

    source.addEventListener("window", (evt) => {
      const data: WindowMetric = JSON.parse((evt as MessageEvent).data);
      setState((s) => ({
        ...s,
        windows: [...s.windows, data].slice(-MAX_WINDOWS),
      }));
    });

    source.addEventListener("incident", (evt) => {
      const data: LiveIncidentEvent = JSON.parse((evt as MessageEvent).data);
      setState((s) => ({
        ...s,
        incidents: [data, ...s.incidents].slice(0, MAX_LIVE_INCIDENTS),
      }));
    });

    source.addEventListener("log", (evt) => {
      const data: LiveLogEvent = JSON.parse((evt as MessageEvent).data);
      setState((s) => ({
        ...s,
        logs: [data, ...s.logs].slice(0, MAX_LOGS),
      }));
    });

    return () => {
      source.close();
    };
  }, []);

  return state;
}
