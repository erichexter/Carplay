# `truckdash-carplay`

**Purpose:** Wireless Apple CarPlay rendered fullscreen via the Carlinkit
CPC200-CCPA USB dongle. Covers Phase 1 of `PRD.md`.

**Approach:** per PRD §6.1 we wrap `rhysmorgan134/react-carplay` rather than
reimplementing the CarPlay protocol. This directory is the thin wrapper
(launcher, config glue, systemd integration); the actual Electron app lives
under `vendor/react-carplay/` after `install-vendor.sh` runs.

## Config

- `/opt/truckdash/config/truckdash.toml` → `[carplay]` section
- Relevant keys: `carlinkit_vendor_id`, `carlinkit_product_id`, `audio_device`,
  `target_fps`

## Systemd unit

`truckdash-carplay.service` (installed from `../systemd/`). Runs as the
`truckdash` user with `plugdev`, `video`, `render`, `input` supplementary
groups. Auto-restarts on crash (5s, up to 3× in 60s before handing off to the
supervisor per PRD §6.1).

## Files

- `launch.sh` — systemd entrypoint. Reads config, locates the built
  react-carplay binary under `vendor/react-carplay/dist/`, execs it.
- `install-vendor.sh` — clones (or updates) the react-carplay fork into
  `vendor/react-carplay/` and runs `npm install && npm run build`.
- `vendor/` — the react-carplay fork. Not checked in (see `.gitignore`).

## Bring-up (on the Pi)

```sh
# Phase 0 must be done first (see scripts/phase0-setup.sh).

# 1. Pull react-carplay and build it.
sudo -u truckdash /opt/truckdash/carplay/install-vendor.sh

# Once your own fork exists, point at it:
# sudo -u truckdash /opt/truckdash/carplay/install-vendor.sh \
#     --remote https://github.com/erichexter/react-carplay.git \
#     --ref truckdash

# 2. Start the service.
sudo systemctl start truckdash-carplay.service
sudo systemctl status truckdash-carplay.service
```

## Run standalone for debugging

Skip systemd; run the launcher by hand in a terminal on the Pi so you see
Electron's stdout/stderr directly:

```sh
sudo -u truckdash XDG_RUNTIME_DIR=/run/user/$(id -u truckdash) \
    WAYLAND_DISPLAY=wayland-0 \
    /opt/truckdash/carplay/launch.sh
```

Or run react-carplay's own dev server from `vendor/react-carplay/`:

```sh
cd /opt/truckdash/carplay/vendor/react-carplay
npm run dev
```

## Tail logs

```sh
journalctl -u truckdash-carplay -f        # live
journalctl -u truckdash-carplay -b        # current boot
journalctl -u truckdash-carplay --since "1 hour ago"
```

## Phase 1 acceptance verification

Per PRD §5 Phase 1, on the bench:

1. iPhone pairs and CarPlay home screen appears.
2. Map scrolling / music playback sustains ≥ 30 fps (use Chrome DevTools
   performance overlay against the renderer, or eyeball it).
3. Touch works.
4. Audio routes to the USB DAC (verify `aplay -L` lists it; confirm via
   `audio_device` setting).
5. Unplug Carlinkit, wait 5s, replug — CarPlay recovers without a reboot.
6. `systemctl status truckdash-carplay` shows active after a fresh boot.
7. `systemctl kill truckdash-carplay` — service restarts within 10s.
