# `truckdash-overlay`

**Purpose:** Transparent gauge overlay rendered on top of CarPlay. Reads
samples from the `truckdash-obd2` WebSocket and displays the gauges defined
in `gauges.toml`. Covers Phase 2 of `PRD.md`.

**Note on architecture:** per PRD §4.2 the overlay is logically a *layer* of
the `truckdash-compositor` service (to be built in Phase 5). Until then we
run it as a standalone Electron window with `transparent: true`,
`alwaysOnTop: true`, and `setIgnoreMouseEvents(true, {forward: true})` so
touches pass through to the CarPlay window underneath. The
`truckdash-overlay.service` unit is a Phase-2 affordance that will fold
into the compositor service when Phase 5 lands.

## Config

- `/opt/truckdash/config/gauges.toml` — overlay position / opacity / gauge list
  (PRD §7.3)
- Gauges reference PID names defined in `obd2.toml`

Env overrides (set in the systemd unit):
- `TRUCKDASH_GAUGES_CONFIG` — path to `gauges.toml`
- `TRUCKDASH_OBD2_WS`       — WebSocket URL (default `ws://127.0.0.1:8765`)

## Systemd unit

`truckdash-overlay.service`. Starts after `truckdash-carplay.service` and
`truckdash-obd2.service` so the underlying CarPlay window and data source
are up first.

## Files

```
ui-overlay/
├── package.json             # npm deps: electron, react, vite, smol-toml
├── tsconfig.json            # renderer tsconfig
├── tsconfig.node.json       # Electron main tsconfig
├── vite.config.ts
├── index.html               # renderer entry
├── src/
│   ├── main.tsx             # React root
│   ├── App.tsx              # layout + ticker
│   ├── Gauge.tsx            # single gauge component
│   ├── ws.ts                # reconnecting WebSocket client
│   └── types.ts
├── electron/
│   ├── main.ts              # Electron main process (transparent window)
│   ├── preload.ts           # IPC bridge for config / ws URL
│   └── types.d.ts           # window.truckdash typing
├── launch.sh                # systemd entrypoint
├── install-overlay.sh       # npm install + build on the Pi
└── .gitignore               # node_modules/, dist/, dist-electron/
```

## Install / build

After `scripts/install.sh` has synced the repo to `/opt/truckdash/`:

```sh
sudo -u truckdash /opt/truckdash/ui-overlay/install-overlay.sh
```

That runs `npm install && npm run build`, producing `dist/` (renderer) and
`dist-electron/` (main + preload).

## Run standalone for debugging

In a dev checkout (e.g. Windows or Mac), test just the React layer in a
browser with a mock WebSocket server:

```sh
cd ui-overlay
npm install
npm run dev                  # vite on http://localhost:5173
# separately, point obd2 --mock at localhost and open the URL
```

Test the full Electron transparent window (on the Pi, with Wayland up):

```sh
cd /opt/truckdash/ui-overlay
npm run dev:electron
```

## Tail logs

```sh
journalctl -u truckdash-overlay -f
```

## Phase 2 acceptance verification

Per PRD §5 Phase 2:

1. Gauges visible in the configured corner over the CarPlay window.
2. Values update at ≥ 2 Hz for the PIDs configured with `rate_hz >= 2`.
3. Tap through the overlay onto CarPlay beneath — CarPlay receives the
   tap. (Electron's `setIgnoreMouseEvents(true, {forward:true})` handles
   this; no per-gauge hit testing needed in Phase 2 because gauges are
   read-only.)
4. Kill and restart `truckdash-obd2` — overlay shows stale values but
   does not crash; when the daemon comes back the values refresh.
5. Change `position = "top-left"` in `gauges.toml` and restart the
   overlay — gauges relocate.
