# 2001 7.3L PCM — PID Reference

Everything we know about the OBD-II / Ford Mode 22 PIDs on the project
truck (2001 F-250 Super Duty, 7.3L Power Stroke, 4R100 trans, PCM type
`0x116`). Captured 2026-05-07 from probe + FORScan correlation.

Source data:
- Probe report: `obd2/probe-2.txt`
- FORScan dashboard CSV: `C:/Users/eric/Documents/FORScan/new.csv`
- FORScan internal log (confirms adapter): `%APPDATA%/FORScan/log/FORScan.log`

## Adapter setup required for Mode 22

The PCM ignores plain `22 PPQQ` requests until the Ford SCP diagnostic
header is set. This was the multi-hour blocker on the first probe
attempt. Daemon and probe script both send these on connect:

```
ATZ                # reset
ATE0               # echo off
ATL0               # linefeeds off
ATS0               # response spaces off
ATH1               # response headers on
ATSP1              # SAE J1850 PWM (Ford pre-2003 protocol)
ATST FF            # ~1 s per-message timeout
ATSH C410F1        # Ford SCP header: priority=C4, target=PCM (10), source=tester (F1)
```

Without `ATSH C410F1`, every Mode 22 request returns `NO DATA`. With it,
both positive and negative responses come back cleanly.

## Response framing

All Mode 22 replies start with the response header `64 F1 10`:
- `64` — priority byte from our `C4`, with the response bit set
- `F1` — target = tester (back to us)
- `10` — source = PCM functional address

Then either:

**Positive response:** `64 F1 10 62 PP QQ <data...>`
- `62` = `0x22 + 0x40` (service+response bit)
- `PP QQ` = echo of the requested PID
- `<data>` = payload bytes (count varies by PID)

**Negative response:** `64 F1 10 7F 22 PP QQ NN [trailing]`
- `7F` = negative response indicator
- `22` = the service that failed
- `PP QQ` = echo of the requested PID
- `NN` = NRC. We see `0x12` consistently = "service-not-supported" /
  "subFunctionNotSupported" — this PID just isn't implemented on this
  PCM calibration.

## Confirmed PIDs (math verified against FORScan)

### EOT — Engine Oil Temperature

- **Request:** `22 13 10`
- **Response payload:** 3 bytes (e.g. `24 D1 A9`)
- **Decode:** byte 0 only — direct °C
- **Bytes 1-2:** unrelated padding, not part of the temperature reading
- **Convert °C → °F:** `F = C × 1.8 + 32`
- **TOML:** `byte_count = 1, scale = 1.8, offset = 32.0, units = "°F"`
- **Validation:** raw `0x24` = 36 °C; FORScan CSV at the same idle
  showed exactly 36 °C ✓

### ICP — Injection Control Pressure

- **Request:** `22 14 34`
- **Response payload:** 2 bytes (e.g. `0F 06`)
- **Decode:** uint16 big-endian — direct kPa
- **Convert kPa → psi:** `psi = kPa × 0.1450377`
- **TOML:** `byte_count = 2, scale = 0.1450377, offset = 0.0, units = "psi"`
- **Validation:** raw `0x0F06` = 3846 kPa; FORScan CSV at the same idle
  showed 3700–3850 kPa range — within sample-to-sample variation ✓

### TFT / TOT — Transmission Fluid Temperature (4R100)

- **Request:** `22 11 28`
- **Response payload:** 3 bytes (e.g. `00 00 17`)
- **Decode:** uint24 big-endian — direct °C. The actual reading lives in
  byte 2; bytes 0-1 are zero padding for all realistic trans temps
  (max ~150 °C fits in 1 byte), so a uint24 read returns the same value
  as `byte_2` would.
- **Convert °C → °F:** `F = C × 1.8 + 32`
- **TOML:** `byte_count = 3, scale = 1.8, offset = 32.0, units = "°F"`
- **Validation:** three consecutive samples at KOEO returned identical
  payload `00 00 17` = 23. FORScan CSV (engine-running idle ~10 min
  earlier) showed TFT = 73 °F = 22.8 °C — match within rounding.
  Trans was at ambient both times (engine doesn't directly heat the
  trans fluid; it's heated by torque-converter slip when driving).
- **Origin note:** this address was originally probed under the label
  "ICP_alt" because it was in the community-list candidates marked as
  alternative ICP. The first probe (engine running) returned the same
  3-byte payload; I dismissed it as not-fitting-ICP. On the second pass
  I noticed `0x17 = 23 = matches FORScan TFT 22.8 °C`. Re-probe at
  KOEO with FORScan-comparable idle conditions confirmed the deduction.

## Probable PIDs (responded, math close, need varied-state confirmation)

These respond positively and the math is plausible, but only an idle
sample was captured. A second probe at warm idle + a brake-stall and/or
a free-rev would lock down the formulas.

### IPR — Injection Pressure Regulator duty

- **Request:** `22 11 05`
- **Response payload:** 2 bytes (e.g. `10 74`)
- **Suspected decode:** byte 0 × `0.392` → %
- **Idle reading:** byte 0 = `0x10` = 16 → 6.27%; FORScan said 6.64% —
  within IPR fluctuation but not exact. Could be `0.4096`, or there's a
  small offset.
- **Test plan:** brake-stall briefly to drive IPR to 30-50%; pair byte 0
  with FORScan IPR % to derive scale.

### MAP — Manifold Absolute Pressure

- **Request:** `22 11 02`
- **Response payload:** 2 bytes (e.g. `00 40`)
- **Suspected decode:** uint16 big-endian — direct kPa
- **Idle reading:** 64 kPa, plausible for a diesel idle (no throttle
  plate; MAP sits near atmospheric ~95 kPa minus some cooling/draw).
- **Test plan:** free-rev to load up the manifold and confirm scaling.
- **Note:** MAP isn't on the dashboard — bonus PID only.

## Responding but byte layout/scale unclear

These addresses returned positive responses, so the PID exists on this
PCM, but the math doesn't fit obvious formulas at idle. Preserved here
so we don't re-probe blindly later.

| Addr   | Suspected | Payload (3-byte if shown 3, else 2) | uint  | Notes |
|--------|-----------|--------------------------------------|-------|-------|
| `0010` | FPW       | `00 00 8B`                           | 139   | FORScan FUELPW=2.86 ms idle. `139 × 0.0205 = 2.85` matches; or maybe scale ≈ 1/48.8 ms. |
| `0011` | MGP       | `00 B7`                              | 183   | FORScan MGP=-0.2 psi idle. No obvious scale fits — maybe needs offset (e.g. raw - some_baseline). |
| `0012` | EBP       | `00 63`                              | 99    | Exhaust back pressure; idle EBP ≈ atmospheric ~100 kPa, so direct kPa is plausible. Not in FORScan CSV. |
| `0013` | MFD       | `00 2F`                              | 47    | Mass fuel desired; no FORScan reference, no obvious scale. |
| `0015` | EOT_alt   | `00 00 02`                           | 2     | Doesn't match 36 °C at any obvious scale. Probably a different signal mislabeled. |
| `0016` | EBPD      | `00 00 8E`                           | 142   | EBPV duty? `142 × 0.392 = 55.7%`; no reference value. |
| `0017` | BARO      | `00 00 01`                           | 1     | Far too low for barometric ~101 kPa expected. Wrong PID guess. |
| `1103` | BARO_alt  | `00 0C`                              | 12    | Same — too low for direct-kPa BARO. |

For any of these we'd need a FORScan correlation session that includes
the specific FORScan label (e.g. "FUELPW", "EBP") to back-solve the
formula. None are dashboard gauges so this is low priority.

## Confirmed not implemented (don't re-probe)

These addresses returned `7F 22 PP QQ 12 NN` (NRC `0x12` = service-not-
supported) on every sample. The 2001 calibration just doesn't expose
these IDs:

```
1110  1120  1137  111D  114F  115C  115F
1228  1256  1258  1290  1322  1341  1E1C
2800  2801
```

Both `ford-odbii-scanner` repos' Ford-specific tables (`f250_logger.py`
in the `12xx` range and `src/pid_definitions.py` in the `28xx` / `00xx`
range) were largely guesses for this PCM — only the original community
list's `1310` and `1434`, plus a handful of `00xx`/`11xx` addresses,
actually exist on this calibration.

## Outstanding gaps

All four dashboard Mode 22 PIDs (EOT, TOT, ICP — plus speed/RPM/fuel
on Mode 01) are now confirmed and configured. Nothing else blocks the
dashboard.

Bonus PIDs that responded but aren't on the dashboard (FPW, MGP, EBP,
MFD, IPR-probable, MAP-probable, etc.) remain in the
"responding-but-unsolved" section above. We can come back and pin those
down if they ever earn a gauge slot — formula derivation needs a
FORScan correlation pass that includes those specific labels.

The KOEO TFT-hunt probe (probe-tft.txt) also turned up these previously-
unknown positive responders worth recording for future reference:
`1107` (payload `00 21`), `0014` (`00 00 8D`), `0018` (`00 00 87`),
`0019` (`00 00 08`), `001A` (`00 00 84`). None decode cleanly to TFT
(which we found at 1128 instead). Identity TBD — could be ambient air,
fuel temp, sensor counts, etc.

## Standard OBD-II Mode 01 PIDs

Confirmed working from the first probe (Mode 01 didn't need the Ford
SCP header — auto-detect was enough):

| PID  | Description       | Idle reading at probe time      |
|------|-------------------|----------------------------------|
| `0C` | RPM               | `41 0C 0B A8` → 746 RPM ✓       |
| `00` | supported PIDs bitmap | `41 00 80 38 00 00`          |
| `05` | Coolant temp      | `41 05 00` → -40 °C (sentinel — Ford routes ECT through enhanced PIDs on this PCM, not Mode 01) |

The Mode 01 supported-PIDs bitmap (`80 38 00 00`) tells us the PCM
exposes via standard Mode 01: PID 01 (monitor status), PID 0C (RPM),
PID 0D (VSS), PID 0E (timing advance). Everything else (temps,
pressures, fuel) lives at Mode 22 / Ford SCP.
