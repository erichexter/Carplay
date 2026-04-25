# obd2/tools

Scratch scripts for bring-up and PCM reverse-engineering. Not part of the
daemon, not packaged — run directly with the obd2 venv.

## probe_mode22.py

One-shot probe that cycles candidate Ford Mode 22 PIDs on the truck and
logs what the PCM actually replies with. Used to turn the placeholder
`[[pids]]` entries in `config/obd2.toml` (EOT, TOT, ICP, ...) into real
addresses + scale factors for the 2001 7.3L.

### Driveway workflow

1. **Close FORScan** if it's connected — only one app can own the EX at
   a time. When this script finishes, reopen FORScan to confirm
   engineering values against the raw bytes we captured.
2. Plug the OBDLink EX into the truck's OBD port. Key on, engine off or
   idle — either works for Mode 22.
3. Find the EX's COM port: **Device Manager → Ports**, usually shows as
   "OBDLink ... (COMx)" or the FTDI bridge.
4. Run from this repo:
   ```sh
   cd obd2
   .venv/Scripts/python.exe tools/probe_mode22.py --port COM5 --protocol 1
   ```
   `--protocol 1` is J1850 PWM — correct for a 2001 7.3L. Use
   `--protocol 0` (auto) if unsure; first query costs a second or two
   while the adapter negotiates.
5. The script prints one line per candidate PID. Hits look like:
   ```
     1310  EOT    2B  n=5  ex=[6E 80]  uint_mean=28288.0  range=[28285..28291]  — ...
   ```
   Misses look like:
   ```
     1E1C  TFT    NO DATA
   ```
6. A timestamped `probe-YYYYMMDD-HHMMSS.txt` is written next to where
   you ran it. Send that back along with what FORScan shows for EOT /
   TFT / ICP at the same moment — the raw bytes + FORScan engineering
   values let us back-solve scale/offset for each real PID, and those
   replace the TODO placeholders in `config/obd2.toml`.

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
