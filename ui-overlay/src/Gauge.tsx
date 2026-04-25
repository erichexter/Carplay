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

export function Gauge({ config, sample }: Props) {
  const size = SIZE_PX[config.size];
  const value = sample?.value ?? null;
  const level = levelFor(config, value);

  return (
    <div
      style={{
        padding: "8px 14px",
        margin: "4px 0",
        color: LEVEL_COLOR[level],
        fontVariantNumeric: "tabular-nums",
        textAlign: "right",
      }}
    >
      <div
        style={{
          fontSize: 30,
          color: "#f5b50d",
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: 1.5,
        }}
      >
        {sample?.display ?? config.pid}
      </div>
      <div style={{ fontSize: size, fontWeight: 600, lineHeight: 1 }}>
        {value != null ? value.toFixed(0) : "--"}
      </div>
      <div style={{ fontSize: 24, color: "#aaa" }}>{sample?.unit ?? ""}</div>
    </div>
  );
}
