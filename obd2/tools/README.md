# obd2/tools

Scratch scripts for bring-up and PCM reverse-engineering. Not part of the
daemon, not packaged — run directly with the obd2 venv.

## probe_mode22.py

One-shot probe that cycles candidate Ford Mode 22 PIDs on the truck and
logs what the PCM actually replies with. Used to turn the placeholder
`[[pids]]` entries in `config/obd2.toml` (EOT, TOT, ICP, ...) into real
addresses + scale factors for the 2001 7.3L.

### Two separate problems this solves

The script does two things, and they have very different uncertainty:

**1. Address discovery (the main job).** Community Ford-enhanced PID
lists give 2-3 candidate addresses for each measurement (EOT, TFT, ICP,
...). Which one a 2001 PCM actually answers to varies by year and PCM
strategy. The script just walks every candidate and records which ones
respond with `62 ...` vs. `NO DATA`. **This is genuinely unknown until
the truck tells us — that's why we run the probe.**

**2. Formula derivation (only sometimes needed).** Once we know an
address responds, we still need raw-bytes → engineering-units math. For
most PIDs the formula is well-documented community lore and we can
just use it. A few are year-variant and need a FORScan cross-check.

#### Formulas we trust without verification

These follow standard Ford SAE-J1979 conventions and are stable across
the 1996-2003 PCM family:

| PID  | Formula                          | Width  |
|------|----------------------------------|--------|
| EOT  | `°F = (raw - 40) × 9/5 + 32`     | 1 byte |
| TFT  | `°F = (raw - 40) × 9/5 + 32`     | 1 byte |
| BARO | `kPa = raw`                      | 1 byte |
| IPR  | `% = raw × 100 / 255`            | 1 byte |

For these, finding which address responds is enough — drop the formula
into `obd2.toml` and move on.

#### Formulas that need FORScan cross-check

Scale factors here vary by PCM revision; community threads disagree:

| PID  | Candidate formulas                          | Why uncertain                         |
|------|----------------------------------------------|---------------------------------------|
| ICP  | `psi ≈ (A×256+B) × 0.580` or `kPa = raw / 5` | 3 different scales seen for 7.3L      |
| MAP  | `kPa = raw` or `kPa = raw × 0.5`             | 1-byte vs. 2-byte varies              |
| MGP  | `psi = ((A×256+B) - baro) / 6.895`           | abs vs. gauge varies                  |
| FPW  | `ms = raw × 0.004`                           | endianness flipped on some PCMs       |

For these, run the script + a FORScan log at the same engine state, and
back-solve scale/offset from paired (raw bytes, engineering value)
points. The script writes a per-sample timestamp into the report so you
can match it against the FORScan CSV row.

### Driveway workflow

1. **Plug the OBDLink EX into the truck's OBD port.** Key on, engine
   running (idle is fine). Engine-running matters for ICP/IPR/MGP — at
   key-on-engine-off they read zero or near-zero.
2. **Find the EX's COM port:** Device Manager → Ports, usually shows as
   "OBDLink ... (COMx)" or the FTDI bridge.
3. **(Optional, for the year-variant PIDs only)** start a FORScan
   dashboard log to CSV *before* running the script. Cycle through
   states you care about (warm idle, brake stall for ICP, etc.) so the
   CSV captures engineering values across a useful range.
4. **Close FORScan** (the OBDLink EX is a single serial endpoint —
   only one app can own the COM port at a time).
5. **Run the script:**
   ```sh
   cd obd2
   .venv/Scripts/python.exe tools/probe_mode22.py --port COM5 --protocol 1
   ```
   `--protocol 1` is J1850 PWM — correct for a 2001 7.3L. Use
   `--protocol 0` (auto) if unsure.
6. **Read the report.** Hits look like:
   ```
     1310  EOT    1B  n=5  ex=[6E]  uint_mean=110.0  range=[108..112]  t=2026-05-07T15:42:10.123..2026-05-07T15:42:11.350  — ...
   ```
   Misses look like:
   ```
     1E1C  TFT    NO DATA
   ```
7. The report (`probe-YYYYMMDD-HHMMSS.txt`) ends with a per-sample
   detail block — one line per sample with timestamp, hex bytes, and
   uint interpretation. That's what you cross-reference against the
   FORScan CSV for the year-variant PIDs.

### Seeded candidates

The script ships with community-known Ford-enhanced PID addresses for
the 7.3L:

- **EOT** (engine oil temp): 3 candidates
- **TFT** (4R100 trans fluid temp): 3 candidates
- **ICP** (injection control pressure): 3 candidates
- **IPR** (injection pressure regulator duty): 2 candidates
- **Bonus** — MAP, BARO, MGP (boost), FPW (fuel pulse width): probed
  while the bus is open, zero cost, tells us what else is available
  for future gauges.

### Adding candidates

Edit the `CANDIDATES` list at the top of `probe_mode22.py`. Same shape:
`(pid_hex, label, note)`. The script de-dupes by PID so adding multiple
labels for the same address is fine.
