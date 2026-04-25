export interface GaugeConfig {
  pid: string;
  type: "numeric" | "bar";
  size: "small" | "medium" | "large";
  warn_above?: number;
  alert_above?: number;
  warn_below?: number;
  alert_below?: number;
  // When both range_min and range_max are set, the gauge renders a
  // colored band (green/yellow/red) with a marker showing the current
  // value. Without a range the gauge is digits-only.
  range_min?: number;
  range_max?: number;
}

export interface OverlayConfig {
  position: "top-left" | "top-right" | "bottom-left" | "bottom-right";
  opacity: number;
  background: string;
  margin_px: number;
  render_hz: number;
}

export interface GaugesConfig {
  overlay: OverlayConfig;
  gauges: GaugeConfig[];
}

export interface Sample {
  pid: string;
  display: string;
  value: number | null;
  unit: string;
  ts: number;
}
