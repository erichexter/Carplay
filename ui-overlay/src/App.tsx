import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Gauge } from "./Gauge";
import { SampleStream } from "./ws";
import type { GaugesConfig, Sample } from "./types";

const CORNER_STYLE: Record<string, CSSProperties> = {
  "top-left": { top: 0, left: 0 },
  "top-right": { top: 0, right: 0 },
  "bottom-left": { bottom: 0, left: 0 },
  "bottom-right": { bottom: 0, right: 0 },
};

export function App() {
  const [cfg, setCfg] = useState<GaugesConfig | null>(null);
  const samplesRef = useRef<Map<string, Sample>>(new Map());
  // tick drives repaints at overlay.render_hz without re-rendering on every
  // incoming sample (avoids flicker from out-of-order paints).
  const [, setTick] = useState(0);

  useEffect(() => {
    let stream: SampleStream | null = null;
    let interval: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    window.truckdash.getConfig().then(({ config, wsUrl }) => {
      if (cancelled) return;
      setCfg(config);
      stream = new SampleStream(wsUrl);
      stream.subscribe((s) => {
        samplesRef.current.set(s.pid, s);
      });
      stream.start();
      const hz = Math.max(1, config.overlay.render_hz ?? 10);
      interval = setInterval(() => setTick((t) => t + 1), 1000 / hz);
    });

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
      stream?.stop();
    };
  }, []);

  if (!cfg) return null;

  const corner = CORNER_STYLE[cfg.overlay.position] ?? CORNER_STYLE["top-right"];
  const margin = cfg.overlay.margin_px ?? 16;

  return (
    <div
      style={{
        position: "fixed",
        ...corner,
        margin,
        opacity: cfg.overlay.opacity,
        background: cfg.overlay.background,
        borderRadius: 8,
        padding: 8,
        minWidth: 120,
        pointerEvents: "none",
        userSelect: "none",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      {cfg.gauges.map((g) => (
        <Gauge key={g.pid} config={g} sample={samplesRef.current.get(g.pid)} />
      ))}
    </div>
  );
}
