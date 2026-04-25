import type { GaugeConfig, Sample } from "./types";

const SIZE_PX: Record<GaugeConfig["size"], number> = {
  small: 52,
  medium: 72,
  large: 104,
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
        padding: "6px 10px",
        margin: "2px 0",
        color: LEVEL_COLOR[level],
        fontVariantNumeric: "tabular-nums",
        textAlign: "right",
      }}
    >
      <div
        style={{
          fontSize: 14,
          color: "#000",
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: 0.5,
        }}
      >
        {sample?.display ?? config.pid}
      </div>
      <div style={{ fontSize: size, fontWeight: 600, lineHeight: 1 }}>
        {value != null ? value.toFixed(0) : "--"}
      </div>
      <div style={{ fontSize: 13, color: "#000", opacity: 0.7 }}>{sample?.unit ?? ""}</div>
    </div>
  );
}
