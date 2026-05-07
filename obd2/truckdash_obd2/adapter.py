from __future__ import annotations

import asyncio
import logging
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .config import AdapterConfig, PidConfig

log = logging.getLogger(__name__)


@dataclass
class Sample:
    pid_name: str
    display: str
    value: float | None
    unit: str
    ts: float


class Adapter(ABC):
    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    async def ensure_connected(self) -> None: ...

    @abstractmethod
    async def query(self, pid: PidConfig) -> Sample | None: ...

    @abstractmethod
    def close(self) -> None: ...


class OBDAdapter(Adapter):
    """Real adapter backed by python-OBD. Imports lazily so tests can run
    without the `obd` package installed."""

    def __init__(self, cfg: AdapterConfig):
        self.cfg = cfg
        self._conn = None  # type: ignore[assignment]
        self._commands: dict[str, object] = {}

    def is_ready(self) -> bool:
        return self._conn is not None and self._conn.is_connected()

    async def ensure_connected(self) -> None:
        if self.is_ready():
            return
        device = self.cfg.device
        if not Path(device).exists():
            log.info("adapter device %s absent", device)
            return

        import obd

        def _connect():
            return obd.OBD(
                portstr=device,
                baudrate=self.cfg.baudrate,
                fast=False,
                timeout=1.0,
            )

        log.info("connecting to adapter at %s", device)
        self._conn = await asyncio.to_thread(_connect)
        if not self._conn.is_connected():
            log.warning("adapter opened but ECU not responding (vehicle off?)")
            return

        # 2001 7.3L PCMs answer Mode 22 only with the Ford SCP diagnostic
        # header set: priority C4, target=PCM functional 10, source=tester F1.
        # Without this, every `22 PPQQ` request returns NO DATA. Discovered
        # 2026-05-07 — see memory/mode22_clone_blocker.md and
        # config/obd2.toml. We pin the protocol to J1850 PWM (`ATSP1`)
        # because adapter auto-detect is sometimes flaky on first connect.
        await asyncio.to_thread(self._send_at, "ATSP1")
        await asyncio.to_thread(self._send_at, "ATSH C410F1")

    def _send_at(self, command: str) -> None:
        """Send a raw AT command via python-OBD's underlying interface."""
        if self._conn is None:
            return
        # python-OBD exposes the ELM327 wrapper as `.interface`; older
        # versions used `.connection`. Cover both.
        iface = getattr(self._conn, "interface", None) or getattr(self._conn, "connection", None)
        if iface is None or not hasattr(iface, "send_and_parse"):
            log.warning("cannot send %s: no AT interface on python-OBD connection", command)
            return
        try:
            iface.send_and_parse(command)
            log.debug("sent %s", command)
        except Exception as e:
            log.warning("send %s failed: %s", command, e)

    async def query(self, pid: PidConfig) -> Sample | None:
        if not self.is_ready():
            return None
        cmd = self._command_for(pid)

        def _run():
            return self._conn.query(cmd, force=True)

        resp = await asyncio.to_thread(_run)
        if resp is None or resp.is_null():
            return None
        raw = resp.value
        if raw is None:
            return None
        value = float(raw.magnitude) if hasattr(raw, "magnitude") else float(raw)
        value = value * pid.scale + pid.offset
        return Sample(
            pid_name=pid.name,
            display=pid.display,
            value=value,
            unit=pid.units,
            ts=time.time(),
        )

    def _command_for(self, pid: PidConfig):
        import obd

        if pid.name in self._commands:
            return self._commands[pid.name]

        # Prefer python-OBD's built-in Mode 01 commands so we get their decoders
        # and units for free.
        if pid.mode == "01":
            try:
                pid_int = int(pid.pid, 16)
                cmd = obd.commands[1][pid_int]
                if cmd is not None:
                    self._commands[pid.name] = cmd
                    return cmd
            except (IndexError, KeyError, ValueError):
                pass

        # Fallback: build a raw command. Mode 22 and any Mode 01 PIDs that
        # python-OBD doesn't ship a decoder for go here. For Mode 22, the
        # 7.3L PCM sometimes returns more payload bytes than carry data
        # (e.g. EOT @ 1310 returns 3 bytes but only byte 0 is meaningful).
        # `byte_count` in obd2.toml lets us slice off the trailing junk.
        def _raw_decoder(messages):
            if not messages:
                return None
            data = messages[0].data
            # Strip the mode+pid echo. Mode 01 response echoes 2 bytes;
            # Mode 22 echoes 3. Use the pid string length as a cheap proxy.
            skip = 1 + (len(pid.pid) // 2)
            payload = data[skip:]
            if pid.byte_count is not None:
                payload = payload[: pid.byte_count]
            if not payload:
                return None
            return int.from_bytes(payload, "big")

        raw_cmd = f"{pid.mode}{pid.pid}".encode("ascii")
        cmd = obd.OBDCommand(
            name=pid.name,
            desc=pid.display,
            command=raw_cmd,
            bytes=0,
            decoder=_raw_decoder,
            ecu=obd.ECU.ENGINE,
            fast=False,
        )
        self._commands[pid.name] = cmd
        return cmd

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None


class MockAdapter(Adapter):
    """Synthetic adapter used for tests and bench dev without hardware."""

    def __init__(self, cfg: AdapterConfig | None = None):
        self.cfg = cfg or AdapterConfig()
        self._connected = True

    def is_ready(self) -> bool:
        return self._connected

    async def ensure_connected(self) -> None:
        self._connected = True

    async def query(self, pid: PidConfig) -> Sample | None:
        t = time.time()
        # Each gauge uses its own period + amplitude so they drift in and out
        # of warn/alert independently rather than all flashing together. Peaks
        # cross the alert threshold briefly each cycle (~10% of the period),
        # and the shoulder on either side crosses warn (~25%). Everything else
        # in the cycle stays normal.
        base = {
            "rpm":          max(600.0, 1500 + 2000 * math.sin(t / 7)),   # warn 3000 / alert 3200
            "coolant_temp": 90 + 2 * math.sin(t / 10),
            "speed":        max(0.0, 55 + 30 * math.sin(t / 5)),         # warn 70 / alert 75
            "intake_temp":  30.0,
            "engine_load":  40 + 20 * math.sin(t / 3),
            "throttle_pos": 20 + 20 * math.sin(t / 2),
            "fuel_level":   max(0.0, 35 + 30 * math.sin(t / 40)),        # warn <25 / alert <10
            "eot":          195 + 55 * math.sin(t / 12),                 # 140-250 °F, warn 220 / alert 228
            "tot":          160 + 90 * math.sin(t / 8),                  # 70-250 °F, warn 190 / alert 200
            "icp":          1500 + 1200 * math.sin(t / 9),               # warn <500 / alert <400
        }.get(pid.name, 0.0)
        value = base * pid.scale + pid.offset
        return Sample(
            pid_name=pid.name,
            display=pid.display,
            value=value,
            unit=pid.units,
            ts=t,
        )

    def close(self) -> None:
        self._connected = False
