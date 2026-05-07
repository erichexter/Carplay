from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RetryConfig:
    adapter_missing: int = 5
    vehicle_off: int = 30
    backoff_max: int = 60


@dataclass
class AdapterConfig:
    device: str = "/dev/obdlink"
    baudrate: int = 115200
    protocol: str = "auto"
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass
class PidConfig:
    name: str
    display: str
    mode: str  # "01", "22", etc.
    pid: str   # hex string without 0x
    rate_hz: float
    units: str = ""
    scale: float = 1.0
    offset: float = 0.0
    # Number of payload bytes to use for the integer value, big-endian. None
    # means use the full payload. Needed for Mode 22 PIDs where the response
    # carries trailing bytes that aren't part of the value (e.g. EOT @ 1310
    # returns 3 bytes but only byte 0 is the °C reading).
    byte_count: int | None = None
    warn_above: float | None = None
    warn_below: float | None = None


@dataclass
class Config:
    adapter: AdapterConfig
    pids: list[PidConfig]


_PID_KEYS = {
    "name", "display", "mode", "pid", "rate_hz",
    "units", "scale", "offset", "byte_count",
    "warn_above", "warn_below",
}


def _pid_from_dict(raw: dict) -> PidConfig:
    return PidConfig(**{k: v for k, v in raw.items() if k in _PID_KEYS})


def load(path: Path | str) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    adapter_raw = data.get("adapter", {})
    retry_raw = adapter_raw.get("retry", {})
    adapter = AdapterConfig(
        device=adapter_raw.get("device", "/dev/obdlink"),
        baudrate=adapter_raw.get("baudrate", 115200),
        protocol=adapter_raw.get("protocol", "auto"),
        retry=RetryConfig(**retry_raw),
    )
    pids = [_pid_from_dict(p) for p in data.get("pids", [])]
    return Config(adapter=adapter, pids=pids)
