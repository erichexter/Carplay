from __future__ import annotations

import asyncio
import logging
import math
import re
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


_NEG_RE = re.compile(r"\b(NO DATA|CAN ERROR|BUS ERROR|UNABLE TO CONNECT|STOPPED|\?)\b", re.I)
_NON_HEX = re.compile(r"[^0-9A-Fa-f]")


class OBDAdapter(Adapter):
    """Direct-serial ELM327 adapter for Ford SCP PCMs.

    python-OBD's ``obd.OBD`` is unusable on a 2001 7.3L PCM: its connection
    flow sends ``0100`` to verify the protocol, but this PCM rejects every
    request without a Ford SCP header (``ATSH C410F1``) — and python-OBD
    offers no hook to inject AT commands before the verification probe.
    Instead we drive the ELM directly via pyserial, the same way
    ``tools/probe_mode22.py`` does (which is the only path proven to work
    on this truck — see ``memory/mode22_clone_blocker.md``).
    """

    def __init__(self, cfg: AdapterConfig):
        self.cfg = cfg
        self._ser = None  # type: ignore[assignment]
        self._initialized = False

    def is_ready(self) -> bool:
        return self._ser is not None and self._initialized

    async def ensure_connected(self) -> None:
        if self.is_ready():
            return
        device = self.cfg.device
        if not Path(device).exists():
            log.info("adapter device %s absent", device)
            return

        log.info("connecting to adapter at %s", device)
        try:
            self._ser = await asyncio.to_thread(self._open_serial, device)
            await asyncio.to_thread(self._init_elm)
        except Exception:
            log.exception("adapter init failed")
            self.close()
            return
        self._initialized = True

    def _open_serial(self, device: str):
        import serial
        return serial.Serial(device, baudrate=self.cfg.baudrate, timeout=0.2)

    def _init_elm(self) -> None:
        # Match probe_mode22.py's init sequence — known to elicit responses
        # from the 7.3L PCM and known to match FORScan's reported values
        # when the response is parsed by the byte_count layout in obd2.toml.
        # ATH1 (headers on) is required: with ATH0 the ELM auto-strips one
        # trailing byte after each response, which removes the actual data
        # for some PIDs (e.g. TOT @ 1128 carries its value in the last byte
        # of a "00 00 XX" payload — verified against FORScan 2026-05-07).
        # _decode below tolerates the leading J1850 PWM header bytes by
        # locating the ``62<pid>`` substring inside the full response.
        protocol = self.cfg.protocol if self.cfg.protocol not in ("", "auto") else "1"
        for cmd, timeout in (
            ("ATZ", 3.0),
            ("ATE0", 1.0),
            ("ATL0", 1.0),
            ("ATS0", 1.0),
            ("ATH1", 1.0),
            (f"ATSP{protocol}", 1.0),
            ("ATST FF", 1.0),
            # Ford SCP PCM functional address. Without this the 2001 7.3L PCM
            # returns NO DATA for every request. Confirmed 2026-05-07.
            ("ATSH C410F1", 1.0),
        ):
            r = self._chat(cmd, read_timeout=timeout)
            log.info("init %s -> %s", cmd, r or "<empty>")

    def _chat(self, command: str, read_timeout: float = 1.0) -> str:
        """Send one command, read until the ELM '>' prompt, return cleaned text."""
        if self._ser is None:
            return ""
        self._ser.reset_input_buffer()
        self._ser.write((command + "\r").encode("ascii"))
        self._ser.flush()

        deadline = time.monotonic() + read_timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._ser.read(256)
            if chunk:
                buf.extend(chunk)
                if b">" in buf:
                    break
            else:
                time.sleep(0.01)

        text = buf.decode("ascii", errors="replace").replace("\r", "\n")
        lines = [ln.strip() for ln in text.split("\n")]
        lines = [ln for ln in lines if ln and ln != ">" and ln != command]
        return " | ".join(lines)

    async def query(self, pid: PidConfig) -> Sample | None:
        if not self.is_ready():
            return None
        request = f"{pid.mode}{pid.pid}"

        def _run():
            return self._chat(request, read_timeout=1.5)

        try:
            raw = await asyncio.to_thread(_run)
        except Exception:
            log.exception("query %s failed", pid.name)
            self._initialized = False  # force re-init on next cycle
            return None

        log.debug("query %s (%s) -> %r", pid.name, request, raw)

        if not raw or _NEG_RE.search(raw):
            return None

        value = self._decode(pid, raw)
        if value is None:
            return None
        value = value * pid.scale + pid.offset
        return Sample(
            pid_name=pid.name,
            display=pid.display,
            value=value,
            unit=pid.units,
            ts=time.time(),
        )

    @staticmethod
    def _decode(pid: PidConfig, raw: str) -> float | None:
        """Pull the data bytes out of an ELM response.

        With ATS0 (spaces off) and ATH0 (headers off) the PCM payload arrives
        as one contiguous hex string, e.g. ``62131024EA`` for ``221310``.
        We strip every non-hex character (handles `|` line breaks, the few
        cases where the ELM does emit spaces, etc.) and look for the
        canonical positive-response prefix:

        - Mode 01: ``4<mode_low><pid>``
        - Mode 22: ``62<pid_hi><pid_lo>``

        Negative responses (``7F<mode>...``) and noise without the prefix
        return None — the daemon treats that as "no sample this cycle".
        """
        flat = _NON_HEX.sub("", raw).upper()
        if not flat:
            return None

        if pid.mode == "01":
            mode_low = int(pid.mode, 16) | 0x40
            prefix = f"{mode_low:02X}{pid.pid.upper()}"
        elif pid.mode == "22":
            prefix = f"62{pid.pid.upper()}"
        else:
            mode_low = int(pid.mode, 16) | 0x40
            prefix = f"{mode_low:02X}{pid.pid.upper()}"

        idx = flat.find(prefix)
        if idx == -1:
            return None
        payload = flat[idx + len(prefix):]
        # Take bytes in pairs of hex characters.
        n_bytes = len(payload) // 2
        if n_bytes == 0:
            return None
        bytes_out = bytes.fromhex(payload[: n_bytes * 2])
        if pid.byte_count is not None:
            bytes_out = bytes_out[: pid.byte_count]
        if not bytes_out:
            return None
        return float(int.from_bytes(bytes_out, "big"))

    def close(self) -> None:
        self._initialized = False
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None


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
