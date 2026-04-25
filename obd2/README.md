# `truckdash-obd2`

**Purpose:** Read OBD-II / Ford Mode 22 PIDs from the OBDLink EX, publish
JSON samples on a local WebSocket, and append each sample to a daily CSV
log. Covers Phase 2 of `PRD.md`.

## Config

- `/opt/truckdash/config/obd2.toml` — adapter settings + PID list (PRD §7.2)

Key fields:
- `[adapter]` — `device`, `baudrate`, `protocol`, `retry.*`
- `[[pids]]` — one per queried parameter; fields: `name`, `display`, `mode`,
  `pid`, `rate_hz`, `units`, `scale`, `offset`, `warn_above`, `warn_below`

Ford Mode 22 PIDs for the 7.3L (EOT / TOT / ICP) are present in
`obd2.toml` with placeholder addresses + `scale=1.0` so the daemon
queries them and the mock adapter supplies synthetic values for
overlay iteration. **Do not run against the real truck until the PIDs
are verified** — enabling unverified PIDs spams the PCM with requests
it rejects, and the engineering values will be garbage. Verification
workflow: run `tools/probe_mode22.py` at the truck with the OBDLink
EX, capture raw bytes, back-solve scale/offset against FORScan's
engineering readout, then update `obd2.toml`. See
[`tools/README.md`](tools/README.md) for the driveway session steps.

## Outputs

- **WebSocket** at `ws://127.0.0.1:8765` — one JSON message per sample:
  `{"pid":"rpm","display":"RPM","value":800.0,"unit":"rpm","ts":1745332200.123}`
- **CSV** at `/var/log/truckdash/obd2/YYYY-MM-DD.csv` — header
  `ts,pid,display,value,unit`, rolled at local midnight, retained 90 days by
  the standard systemd-journal retention (PRD §8).

## Systemd unit

`truckdash-obd2.service` (installed from `../systemd/`). Runs as
`truckdash:truckdash` with `dialout` supplementary group for /dev/obdlink.
Restart=on-failure, 5s delay, 3× in 60s before handing off to the supervisor
per PRD §6.2.

## Install / build

On the Pi, after `scripts/install.sh` has synced the repo to `/opt/truckdash/`:

```sh
sudo -u truckdash python3 -m venv /opt/truckdash/obd2/.venv
sudo -u truckdash /opt/truckdash/obd2/.venv/bin/pip install -e /opt/truckdash/obd2
```

`scripts/install.sh` does this automatically.

## Run standalone for debugging

Against the real adapter:

```sh
sudo -u truckdash /opt/truckdash/obd2/.venv/bin/truckdash-obd2 \
    --config /opt/truckdash/config/obd2.toml \
    --log-dir /var/log/truckdash/obd2
```

Against a synthetic mock (no hardware required — useful on the bench or
dev box):

```sh
/opt/truckdash/obd2/.venv/bin/truckdash-obd2 \
    --config /opt/truckdash/config/obd2.toml \
    --log-dir /tmp/obd2-dev \
    --mock
```

Tail samples from the WebSocket:

```sh
python3 -c '
import asyncio, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        while True:
            print(await ws.recv())
asyncio.run(main())
'
```

## Tail logs

```sh
journalctl -u truckdash-obd2 -f
tail -f /var/log/truckdash/obd2/$(date -I).csv
```

## Tests

```sh
cd /opt/truckdash/obd2
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -v
```

Tests mock `python-OBD` at the library boundary per PRD §9.1 (no real USB
access needed).

## Failure modes

Per PRD §6.2:

| Condition | Daemon behaviour |
|-----------|------------------|
| /dev/obdlink missing (adapter unplugged) | log info, sleep `adapter_missing` seconds, retry |
| Adapter present, ECU silent (key off) | log warning, sleep `vehicle_off` seconds, retry |
| Malformed response to a single PID | log exception, skip that sample, continue |
| WebSocket client disconnect | dropped from client set, no crash |
| CSV write error | log exception, continue in-memory publishing |

## Phase 2 acceptance verification

Per PRD §5 Phase 2, with the EX plugged into the truck:

1. `ls -l /dev/obdlink` shows a symlink (requires the udev rule VID/PID
   filled in — see `udev/99-truckdash.rules` TODO).
2. `systemctl status truckdash-obd2` shows active.
3. The WebSocket tail (above) streams samples at the configured rates for
   at least 6 PIDs.
4. Today's CSV in `/var/log/truckdash/obd2/` has one row per sample.
5. Unplug the EX → daemon logs "adapter device /dev/obdlink absent" every
   5 seconds, does not crash.
6. Cycle the ignition → daemon reconnects cleanly, continues sampling.
