# TruckDash

Raspberry Pi based in-dash infotainment for a 2001 Ford F-250 7.3L Power
Stroke. Targets a Pi 5 8GB — the Pi 4B was tested in Phase 1 bring-up and
ruled out (see [`docs/phase1-notes.md`](docs/phase1-notes.md) for why).
See [`PRD.md`](PRD.md) for scope, architecture, and phased plan.

## Status

| Phase | Description                        | State       |
|-------|------------------------------------|-------------|
| 0     | Bench setup                        | done (Pi 4B) |
| 1     | CarPlay core                       | bring-up on Pi 4B done; re-verify on Pi 5 |
| 2     | OBD2 service + overlay             | mock loop end-to-end on Pi 4B; awaiting real PIDs + Pi 5 re-verify |
| 3     | Reverse camera                     | not started |
| 4     | GPS + offline nav                  | not started |
| 5     | Power management                   | not started |
| 6     | Polish and install                 | not started |

Phase 2 currently runs end-to-end against the synthetic mock adapter:
OBD2 daemon publishes samples on the WebSocket, the Electron overlay
renders gauges with tri-state (normal / warn / alert) coloring on top
of the CarPlay window via labwc. Real-truck values for the Ford
Mode 22 PIDs (EOT / TOT / ICP) are placeholders pending a driveway
session with `obd2/tools/probe_mode22.py` against the OBDLink EX.

## Layout

```
scripts/   phase0-setup.sh, install.sh — run on the Pi
config/    TOML config files, deployed to /opt/truckdash/config/
udev/      udev rules, deployed to /etc/udev/rules.d/
systemd/   unit files, deployed to /etc/systemd/system/
carplay/   truckdash-carplay service wrapper around react-carplay
```

On the Pi these land under `/opt/truckdash/` — see PRD §4.4.

## Bring-up on a fresh Pi (4B or 5)

1. Flash Raspberry Pi OS Bookworm 64-bit and boot the Pi.
2. Copy this repo to the Pi (`git clone` or `scp`).
3. Phase 0:
   ```sh
   sudo ./scripts/phase0-setup.sh --skip-ssh-harden  # first run
   ssh-copy-id pi@<ip>
   sudo ./scripts/phase0-setup.sh                    # re-run to harden SSH
   ```
4. Phase 1 + 2:
   ```sh
   sudo ./scripts/install.sh
   sudo -u truckdash /opt/truckdash/carplay/install-vendor.sh      # CarPlay
   sudo -u truckdash /opt/truckdash/ui-overlay/install-overlay.sh  # overlay
   sudo systemctl start truckdash.target
   journalctl -u truckdash-carplay -u truckdash-obd2 -u truckdash-overlay -f
   ```

Per-service details:
- [`carplay/README.md`](carplay/README.md)
- [`obd2/README.md`](obd2/README.md)
- [`ui-overlay/README.md`](ui-overlay/README.md)
