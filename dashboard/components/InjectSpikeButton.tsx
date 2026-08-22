"use client";

import { useEffect, useState } from "react";
import { fetchSpikeTypes, injectSpike } from "@/lib/api";
import type { SpikeType } from "@/lib/types";

const FALLBACK_SPIKE_TYPES: SpikeType[] = [
  { id: "error_burst", label: "Error burst", description: "Elevated 5xx rate with high latency." },
];

const MIN_SIZE = 20;
const MAX_SIZE = 400;
const SIZE_STEP = 20;
const MAX_DURATION = 120;
const DURATION_STEP = 5;

export default function InjectSpikeButton() {
  const [spikeTypes, setSpikeTypes] = useState<SpikeType[]>(FALLBACK_SPIKE_TYPES);
  const [spikeType, setSpikeType] = useState(FALLBACK_SPIKE_TYPES[0].id);
  const [size, setSize] = useState(80);
  const [duration, setDuration] = useState(0);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchSpikeTypes()
      .then((types) => {
        if (types.length > 0) {
          setSpikeTypes(types);
          setSpikeType(types[0].id);
        }
      })
      .catch(() => {});
  }, []);

  async function handleClick() {
    setPending(true);
    setMessage(null);
    try {
      const res = await injectSpike(spikeType, size, duration);
      const timing = res.duration_seconds > 0 ? `over ${res.duration_seconds}s` : "instantly";
      setMessage(`Injecting ${res.injected} anomalous log entries ${timing} — watch the feed below.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to inject spike.");
    } finally {
      setPending(false);
    }
  }

  const activeDescription = spikeTypes.find((t) => t.id === spikeType)?.description;

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <select
          value={spikeType}
          onChange={(e) => setSpikeType(e.target.value)}
          disabled={pending}
          className="bg-panel border border-edge rounded-md text-sm px-2 py-2 text-neutral-200 disabled:opacity-50"
        >
          {spikeTypes.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </select>
        <button
          onClick={handleClick}
          disabled={pending}
          className="px-4 py-2 rounded-md bg-status-danger/90 hover:bg-status-danger disabled:opacity-50 text-sm font-medium transition-colors"
        >
          {pending ? "Injecting…" : "Inject Spike"}
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1.5 bg-panel border border-edge rounded-md px-3 py-2">
        <label className="flex items-center gap-2 text-xs text-neutral-400">
          Size
          <input
            type="range"
            min={MIN_SIZE}
            max={MAX_SIZE}
            step={SIZE_STEP}
            value={size}
            onChange={(e) => setSize(Number(e.target.value))}
            disabled={pending}
            className="accent-accent"
          />
          <span className="text-neutral-300 w-10 text-right tabular-nums">{size}</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-neutral-400">
          Duration
          <input
            type="range"
            min={0}
            max={MAX_DURATION}
            step={DURATION_STEP}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            disabled={pending}
            className="accent-accent"
          />
          <span className="text-neutral-300 w-14 text-right tabular-nums">
            {duration === 0 ? "instant" : `${duration}s`}
          </span>
        </label>
      </div>

      {activeDescription && (
        <span className="text-xs text-neutral-500 max-w-xs text-right">{activeDescription}</span>
      )}
      {message && <span className="text-xs text-neutral-400 max-w-xs text-right">{message}</span>}
    </div>
  );
}
