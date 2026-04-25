#!/usr/bin/env python3
"""
Probe Ford Mode 22 PIDs on a 2001 7.3L PCM via an OBDLink EX.

You run this in the driveway with FORScan open next to you so you can
correlate raw response bytes against the engineering values FORScan
displays. The output is a plaintext report we then turn into
obd2.toml entries with real scale/offset.

Usage:
    python -m probe_mode22 --port COM5
    python -m probe_mode22 --port COM5 --samples 20 --protocol 1

Nothing here writes to the ECU — Mode 22 is a read request.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import serial  # pyserial


# -----------------------------------------------------------------------------
# Candidate Mode 22 PIDs for 1999-2003 7.3L Power Stroke.
#
# Numbers collected from community Ford-enhanced PID lists (TheDieselStop,
# Forscan forum threads). These are UNVERIFIED for a 2001 PCM specifically —
# that's literally what this script exists to verify. A PID either responds
# with `62 XX YY ...` (positive Mode 22 reply) or with `NO DATA` (PCM does
# not implement that identifier). We run every candidate, log the outcome,
# and sit with the printout + FORScan to pick the winners.
#
# Feel free to add candidates inline — keep the same (hex_pid, label, note)
# shape.
# -----------------------------------------------------------------------------

CANDIDATES: list[tuple[str, str, str]] = [
    # Engine Oil Temp
    ("1310", "EOT",  "Engine Oil Temp — most commonly cited for 7.3L"),
    ("115C", "EOT",  "alt EOT address seen on some 7.3L lists"),
    ("1137", "EOT",  "alt EOT address"),

    # Transmission Fluid Temp (4R100)
    ("1E1C", "TFT",  "4R100 trans fluid temp — year-variant"),
    ("111D", "TFT",  "alt TFT address"),
    ("1120", "TFT",  "alt TFT address"),

    # Injection Control Pressure
    ("1434", "ICP",  "ICP sensor raw (kPa or counts, TBD)"),
    ("1110", "ICP",  "ICP filtered"),
    ("1128", "ICP",  "ICP demand / commanded"),

    # Injection Pressure Regulator duty cycle
    ("1341", "IPR",  "IPR duty %"),
    ("1105", "IPR",  "alt IPR address"),

    # Boost / MAP / Baro (not requested for the dash but useful to probe
    # while we have the bus open — rules out or in as future gauges)
    ("1102", "MAP",  "Manifold Absolute Pressure"),
    ("1103", "BARO", "Barometric pressure"),
    ("115F", "MGP",  "Manifold Gauge Pressure (boost)"),

    # Fuel Pulse Width
    ("114F", "FPW",  "Injector fuel pulse width"),
]


# -----------------------------------------------------------------------------
# ELM327 / STN chat helpers
# -----------------------------------------------------------------------------

PROMPT = b">"


@dataclass
class Reply:
    raw: str
    lines: list[str]


class Elm:
    def __init__(self, port: str, baudrate: int, timeout_s: float):
        self.ser = serial.Serial(port, baudrate=baudrate, timeout=timeout_s)

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def cmd(self, s: str, read_timeout_s: float = 2.0) -> Reply:
        """Send one AT / OBD line, read until the '>' prompt, return the lines."""
        self.ser.reset_input_buffer()
        self.ser.write((s + "\r").encode("ascii"))
        self.ser.flush()

        deadline = time.time() + read_timeout_s
        buf = bytearray()
        while time.time() < deadline:
            chunk = self.ser.read(256)
            if chunk:
                buf.extend(chunk)
                if PROMPT in buf:
                    break
            else:
                # short sleep keeps us off a tight poll without blocking too long
                time.sleep(0.01)

        text = buf.decode("ascii", errors="replace")
        # strip echo of the command we just sent and the final '>'
        text = text.replace("\r", "\n")
        lines = [ln.strip() for ln in text.split("\n")]
        lines = [ln for ln in lines if ln and ln != ">" and ln != s]
        return Reply(raw=text, lines=lines)


def init_adapter(elm: Elm, protocol: str, report: list[str]) -> None:
    def log(title: str, r: Reply) -> None:
        report.append(f"  {title}: {' | '.join(r.lines) or '<empty>'}")

    # Reset + silence noisy formatting so parsing is predictable.
    log("ATZ",    elm.cmd("ATZ", read_timeout_s=3.0))
    log("ATE0",   elm.cmd("ATE0"))
    log("ATL0",   elm.cmd("ATL0"))
    log("ATS0",   elm.cmd("ATS0"))
    log("ATH1",   elm.cmd("ATH1"))  # headers on — we want to see the ECU address
    log("ATSP",   elm.cmd(f"ATSP {protocol}"))
    log("ATST FF", elm.cmd("ATST FF"))  # ~1 s per-message timeout
    log("ATI",    elm.cmd("ATI"))
    log("ATDP",   elm.cmd("ATDP"))


# -----------------------------------------------------------------------------
# Mode 22 probe
# -----------------------------------------------------------------------------

NO_DATA_RES = re.compile(r"\b(NO DATA|CAN ERROR|BUS ERROR|UNABLE TO CONNECT|STOPPED|\?)\b", re.I)
HEX_LINE = re.compile(r"^[0-9A-Fa-f\s]+$")


def extract_data_bytes(lines: list[str], pid_hex: str) -> list[int] | None:
    """Find the `62 PP QQ DD DD...` positive response payload across the reply.

    Responses we care about come in one of two shapes:
      With headers on (ATH1) — one of the lines looks like:
          "7E8 06 62 13 10 6E 80 AA BB"  (CAN)
          "48 6B 10 62 13 10 6E 80 XX"    (J1850 PWM, header bytes vary)
      Without headers, a line is just:
          "62 13 10 6E 80"
    """
    target = f"62 {pid_hex[0:2]} {pid_hex[2:4]}".upper()
    flat = " ".join(ln.upper() for ln in lines if HEX_LINE.match(ln))
    idx = flat.find(target)
    if idx == -1:
        return None
    tail = flat[idx + len(target):].split()
    out: list[int] = []
    for tok in tail:
        # stop as soon as something non-hex sneaks in (extra ECU reply, etc.)
        if len(tok) != 2 or any(c not in "0123456789ABCDEF" for c in tok):
            break
        out.append(int(tok, 16))
    return out


@dataclass
class ProbeResult:
    pid: str
    label: str
    note: str
    samples: list[list[int]]
    errors: list[str]

    def summary(self) -> str:
        if not self.samples:
            err = self.errors[0] if self.errors else "no response"
            return f"  {self.pid}  {self.label:5s}  {err}"
        byte_count = len(self.samples[0])
        # Interpret as uint: big-endian concat is the simplest guess.
        as_int = [int.from_bytes(bytes(s), "big") for s in self.samples if len(s) == byte_count]
        mean = statistics.fmean(as_int) if as_int else 0
        span = (min(as_int), max(as_int)) if as_int else (0, 0)
        first_hex = " ".join(f"{b:02X}" for b in self.samples[0])
        return (
            f"  {self.pid}  {self.label:5s}  "
            f"{byte_count}B  n={len(self.samples)}  "
            f"ex=[{first_hex}]  uint_mean={mean:.1f}  range=[{span[0]}..{span[1]}]  "
            f"— {self.note}"
        )


def probe_one(elm: Elm, pid: str, samples: int, delay_s: float) -> ProbeResult:
    # The script runs through CANDIDATES with duplicate labels (several
    # candidate addresses for "EOT" etc.) — the caller picks the label.
    label, note = "", ""
    for p, l, n in CANDIDATES:
        if p == pid:
            label, note = l, n
            break

    results: list[list[int]] = []
    errors: list[str] = []
    for _ in range(samples):
        reply = elm.cmd(f"22 {pid[0:2]} {pid[2:4]}", read_timeout_s=1.5)
        joined = " | ".join(reply.lines)
        if NO_DATA_RES.search(joined):
            errors.append(joined)
            break  # PID not supported; don't bother with more samples
        data = extract_data_bytes(reply.lines, pid)
        if data is None:
            errors.append(f"unparsed: {joined}")
            continue
        results.append(data)
        time.sleep(delay_s)

    return ProbeResult(pid=pid, label=label, note=note, samples=results, errors=errors)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True, help="serial port (COM5, /dev/ttyUSB0, ...)")
    ap.add_argument("--baudrate", type=int, default=115200)
    ap.add_argument(
        "--protocol",
        default="0",
        help="ELM protocol number. 0=auto, 1=J1850 PWM (2001 7.3L default), 6=ISO 15765 CAN 11b/500k",
    )
    ap.add_argument("--samples", type=int, default=5,
                    help="samples per PID; low numbers are fine for a first pass")
    ap.add_argument("--delay", type=float, default=0.25, help="seconds between samples")
    ap.add_argument("--output", type=Path,
                    default=Path(f"probe-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"))
    args = ap.parse_args()

    report: list[str] = []
    report.append("TruckDash Mode 22 probe")
    report.append(f"  when:   {datetime.now().isoformat(timespec='seconds')}")
    report.append(f"  port:   {args.port} @ {args.baudrate}")
    report.append(f"  proto:  ELM {args.protocol}")
    report.append("")
    report.append("Adapter init:")

    try:
        elm = Elm(args.port, args.baudrate, timeout_s=0.5)
    except serial.SerialException as e:
        print(f"ERROR: could not open {args.port}: {e}", file=sys.stderr)
        return 2

    try:
        init_adapter(elm, args.protocol, report)
        report.append("")
        report.append(f"Probing {len(CANDIDATES)} candidates "
                      f"({args.samples} samples each, {args.delay}s delay):")
        report.append("")

        # de-dup pids while keeping order
        seen: set[str] = set()
        unique_pids: list[str] = []
        for p, _, _ in CANDIDATES:
            if p not in seen:
                seen.add(p)
                unique_pids.append(p)

        for pid in unique_pids:
            result = probe_one(elm, pid, args.samples, args.delay)
            line = result.summary()
            report.append(line)
            print(line, flush=True)
    finally:
        elm.close()

    args.output.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"\nreport written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
