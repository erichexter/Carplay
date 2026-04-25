import type { GaugeConfig, Sample } from "./types";

// Sized for a 640px-wide right-edge strip on a 2560-wide panel. Vertical
// budget for the default 6 gauges (1 large, 4 medium, 1 small): roughly
// 310 + 4*230 + 190 = 1420px in a 1600px column, leaving ~180px slack.
// If you add a 7th gauge or bump values further, drop a `medium` to
// `small` in config/gauges.toml first — packing past 1500px starts to
// look cramped.
const SIZE_PX: Record<GaugeConfig["size"], number> = {
  small: 120,
  medium: 160,
  large: 240,
};

interface Props {
  config: GaugeConfig;
  sample: Sample | undefined;
}

type Level = "normal" | "warn" | "alert";

function levelFor(config: GaugeConfig, value: number | null): Level {
  if (value == null) return "normal";
  if (config.alert_above != null && value >= config.alert_above) return "alert";
  if (config.alert_below != null && value <= config.alert_below) return "alert";
  if (config.warn_above != null && value >= config.warn_above) return "warn";
  if (config.warn_below != null && value <= config.warn_below) return "warn";
  return "normal";
}

const LEVEL_COLOR: Record<Level, string> = {
  normal: "#e8e8e8",
  warn: "#ffd24a",
  alert: "#ff4a4a",
};

const BAND_GREEN = "#2ea043";
const BAND_YELLOW = "#ffd24a";
const BAND_RED = "#ff4a4a";

// Build a CSS linear-gradient with hard color stops at each threshold so
// the bar shows discrete green/yellow/red regions instead of a smooth
// fade. Returns null when the gauge has no range_min/range_max — those
// gauges fall back to digits-only.
function bandGradient(config: GaugeConfig): string | null {
  const lo = config.range_min;
  const hi = config.range_max;
  if (lo == null || hi == null || hi <= lo) return null;

  const pct = (v: number) =>
    Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));

  const valAt = (p: number) => lo + (p / 100) * (hi - lo);

  const colorAt = (p: number): string => {
    const v = valAt(p);
    if (config.alert_below != null && v < config.alert_below) return BAND_RED;
    if (config.warn_below != null && v < config.warn_below) return BAND_YELLOW;
    if (config.alert_above != null && v >= config.alert_above) return BAND_RED;
    if (config.warn_above != null && v >= config.warn_above) return BAND_YELLOW;
    return BAND_GREEN;
  };

  const points = new Set<number>([0, 100]);
  for (const t of [
    config.alert_below,
    config.warn_below,
    config.warn_above,
    config.alert_above,
  ]) {
    if (t != null) points.add(pct(t));
  }
  const sorted = [...points].sort((a, b) => a - b);

  const stops: string[] = [];
  for (let i = 0; i < sorted.length - 1; i++) {
    const a = sorted[i];
    const b = sorted[i + 1];
    if (b <= a) continue;
    const c = colorAt((a + b) / 2);
    stops.push(`${c} ${a}%`, `${c} ${b}%`);
  }
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

function valuePct(config: GaugeConfig, value: number | null): number | null {
  const lo = config.range_min;
  const hi = config.range_max;
  if (lo == null || hi == null || hi <= lo || value == null) return null;
  return Math.max(0, Math.min(100, ((value - lo) / (hi - lo)) * 100));
}

export function Gauge({ config, sample }: Props) {
  const size = SIZE_PX[config.size];
  const value = sample?.value ?? null;
  const level = levelFor(config, value);
  const gradient = bandGradient(config);
  const markerPct = valuePct(config, value);

  return (
    <div
      style={{
        padding: "18px 14px",
        color: LEVEL_COLOR[level],
        fontVariantNumeric: "tabular-nums",
        textAlign: "right",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {gradient && (
          <div
            style={{
              position: "relative",
              flex: 1,
              height: 12,
              borderRadius: 2,
              background: gradient,
              opacity: 0.85,
            }}
          >
            {markerPct != null && (
              <div
                style={{
                  position: "absolute",
                  left: `${markerPct}%`,
                  top: -3,
                  bottom: -3,
                  width: 4,
                  marginLeft: -2,
                  background: "#ffffff",
                  boxShadow: "0 0 4px rgba(0,0,0,0.9)",
                  borderRadius: 1,
                }}
              />
            )}
          </div>
        )}
        <div
          style={{
            fontSize: 26,
            lineHeight: 1,
            color: "#f5b50d",
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: 1.5,
          }}
        >
          {sample?.display ?? config.pid}
        </div>
      </div>
      <div style={{ fontSize: size, fontWeight: 600, lineHeight: 1 }}>
        {value != null ? value.toFixed(0) : "--"}
      </div>
      <div style={{ fontSize: 20, lineHeight: 1, color: "#aaa" }}>
        {sample?.unit ?? ""}
      </div>
    </div>
  );
}
