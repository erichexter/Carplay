# PRD — F-250 Pi Infotainment System ("TruckDash")

**Status:** Draft v1
**Owner:** Eric
**Target hardware:** 2001 Ford F-250 7.3L Power Stroke (4R100 auto)
**Agent audience:** Claude Code

---

## 0. How to use this PRD (for Claude Code)

- This document is the source of truth for scope. Do not exceed it without proposing a scope change in writing.
- Work in phases. Do not start Phase N until Phase N-1 passes its acceptance criteria.
- Every service gets its own git commit series with conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
- Every service must have a README in its own directory covering: purpose, config file path, systemd unit name, how to run standalone for debugging, and how to tail logs.
- Prefer boring, well-supported libraries over novel ones. This runs in a truck; it cannot have exotic dependencies.
- Target platform is **Raspberry Pi OS Bookworm (64-bit, aarch64)** on a **Raspberry Pi 5 (8GB)**. The Pi 4B was tested in Phase 1 bring-up (see `docs/phase1-notes.md`) and ruled out: react-carplay's WebGL2 fallback path hits a `gl.readPixels` pipeline stall that V3D 4.2 on the 4B cannot avoid. Pi 5's V3D 7.1 has working Vulkan, which unlocks the WebGPU render path and bypasses the stall. Do not write code that assumes x86, glibc-only behaviors, or Debian versions other than Bookworm. Keep the Pi 4B bootable for diagnostics, but do not optimize for it.
- All code is Python 3.11+ (services) or TypeScript/React (UI work). No Rust, no Go, no C++ unless explicitly called out.
- All services run under a dedicated non-root user `truckdash` except where hardware access demands otherwise (GPIO, USB HID) — in those cases use `udev` rules to grant group access, not `sudo`.
- No cloud dependencies at runtime. The truck may have no cell signal.

---

## 1. Problem statement

The 2001 F-250 has a factory AM/FM/cassette head unit with no aux input, no navigation, no reversing aid, and no access to the 7.3L Power Stroke's OBD2 data while driving. Rather than replacing the head unit with an aftermarket CarPlay unit (expensive, uninteresting, and doesn't expose OBD2 telemetry), we are building a Raspberry Pi based in-dash infotainment system that:

1. Provides wireless Apple CarPlay via a Carlinkit CPC200-CCPA dongle
2. Overlays live 7.3L engine telemetry (ICP, IPR, EOT, FICM voltage, etc.) from an OBD2 adapter
3. Auto-switches to a backup camera when reverse is engaged
4. Provides fully offline GPS navigation
5. Boots cleanly with the ignition and shuts down cleanly when the ignition drops

The system is called **TruckDash**.

---

## 2. Goals and non-goals

### Goals (v1)

- Power-on-to-CarPlay in ≤ 45 seconds from ignition-on
- Wireless CarPlay from iPhone at a sustained 30fps minimum, 60fps target
- Live OBD2 overlay showing at least 6 configurable PIDs at ≥ 2 Hz refresh
- Backup camera preempts all other UI within 500 ms of reverse trigger
- Offline navigation covering Texas plus any pre-downloaded regions
- Zero data loss on unexpected power loss (filesystem must survive)
- All services auto-recover from crashes within 10 seconds
- Full system fits in the factory dash opening or behind a tasteful single-DIN trim plate

### Non-goals (v1)

- Android Auto (CarPlay only for v1)
- Media playback independent of the iPhone (no local music library)
- Voice control outside of Siri passthrough
- Dashcam recording (deferred to v2)
- Integration with the Synology NAS (deferred to v2)
- Steering wheel control integration (the 2001 F-250 has none)
- Over-the-air updates (manual `git pull` + `systemctl restart` is acceptable for v1)
- A mobile companion app
- Support for any vehicle other than the F-250

---

## 3. Users and use cases

Single user: the driver (Eric). Primary use cases, in order of frequency:

1. Daily driving — CarPlay for music/podcasts/phone, OBD2 gauges visible, nav when needed
2. Diagnostic driving — OBD2 gauges prominent, CarPlay backgrounded, logging to SD card for later analysis
3. Reversing with a trailer — backup camera fullscreen, audible beep from Pi speaker, no UI distractions
4. Off-grid driving in the Hill Country — offline nav primary, CarPlay may be offline
5. Cold-start diagnostics — system boots, OBD2 service captures the critical first 2 minutes of ICP/IPR/EBPV data to disk

---

## 4. System architecture

### 4.1 Hardware bill of materials

| Component | Part | Notes |
|---|---|---|
| Compute | Raspberry Pi 5 8GB | Pi 4B was tested and ruled out during Phase 1 (ReadPixels stall on V3D 4.2; see `docs/phase1-notes.md`). `phase0-setup.sh` still installs zram swap — harmless on the 5, kept in case we ever put the 4B back in for diagnostics. |
| Storage | NVMe SSD via Pi 5 M.2 HAT (preferred) **or** USB 3.0 SSD **or** 128GB A2 microSD | SSD strongly preferred for write endurance and map-tile read throughput. Pi 5 + NVMe HAT is the target; SD is an acceptable fallback for v1. |
| Display | 7" HDMI capacitive touchscreen, 1024×600 | Waveshare or equivalent; official Pi touchscreen not used due to DSI cable fragility in a vehicle |
| CarPlay bridge | Carlinkit CPC200-CCPA | The *wireless* variant. Not the CCPM or CCPW. |
| OBD2 adapter | OBDLink EX (USB) | Ford-specific variant. Supports MS-CAN in addition to HS-CAN / OBD-II — needed for full 7.3L enhanced-PID access. Wired USB over Bluetooth for reliability and to keep the BT radio free. |
| GPS | u-blox 7 or 8 USB dongle | NMEA-0183 over USB serial |
| Backup camera | Any RCA composite reverse camera | |
| Camera input | HDMI-to-USB or composite-to-USB capture dongle | UVC-compatible; MS2109 chipset acceptable |
| Reverse trigger | 12V → 3.3V opto-isolator board | Wired to reverse light circuit → Pi GPIO |
| Power supply | Automotive-grade 12V → 5V 5A buck converter with ignition-sense | Must handle cranking transients (down to 6V briefly) |
| Clean shutdown | UPS HAT with supercap or small LiPo | Must give ≥ 30 seconds after ignition drops for clean shutdown |
| Audio out | USB DAC → 3.5mm aux | Assumes aftermarket head unit with aux-in is installed separately |

### 4.2 Software services

Six `systemd` services, all grouped under a `truckdash.target`:

1. **`truckdash-carplay.service`** — React-CarPlay Electron app, renders CarPlay video from the Carlinkit dongle
2. **`truckdash-obd2.service`** — Python daemon, reads PIDs from the OBDLink EX, publishes to local WebSocket
3. **`truckdash-gps.service`** — `gpsd` (stock Debian package), reads NMEA from u-blox, publishes on `gpsd` socket
4. **`truckdash-camera.service`** — Python daemon, watches reverse GPIO, starts GStreamer pipeline to display camera feed on reverse
5. **`truckdash-compositor.service`** — Wayland compositor (`labwc` or `cage`) managing layers
6. **`truckdash-supervisor.service`** — top-level orchestrator that manages startup ordering, shutdown, and health checks

See §6 for per-service specs.

### 4.3 Data flow

```
iPhone ──(WiFi/BT)──> Carlinkit ──(USB)──> carplay service ──> compositor (layer 0)
F-250 OBD2 ──(OBD-II/MS-CAN)──> OBDLink EX ──(USB)──> obd2 service ──(WebSocket)──> overlay UI (layer 1)
Reverse light ──(GPIO)──> camera service ──(GStreamer)──> compositor (layer 2, top)
u-blox GPS ──(USB)──> gpsd ──(socket)──> nav UI (within compositor)
```

### 4.4 Directory layout

```
/opt/truckdash/
├── carplay/              # React-CarPlay fork or wrapper
├── obd2/                 # Python OBD2 service
├── camera/               # Python camera service
├── compositor/           # Compositor config and startup scripts
├── supervisor/           # Top-level supervisor
├── ui-overlay/           # React overlay (gauges) that renders on top of CarPlay
├── config/               # TOML config files
│   ├── truckdash.toml    # Global config
│   ├── obd2.toml         # PID definitions, sample rates
│   └── gauges.toml       # Which PIDs are visible on the overlay
├── scripts/              # Install, update, diagnostic scripts
└── logs/                 # Runtime logs (symlinked to /var/log/truckdash/)

/etc/systemd/system/
├── truckdash.target
├── truckdash-carplay.service
├── truckdash-obd2.service
├── truckdash-gps.service
├── truckdash-camera.service
├── truckdash-compositor.service
└── truckdash-supervisor.service
```

---

## 5. Phased delivery plan

Each phase ends with a working, testable system. Do not advance until acceptance criteria for the current phase pass.

### Phase 0 — Bench setup (est. 0.5 day)

Get the Pi booting Bookworm, networked, and reachable via SSH. Install base packages. No TruckDash code yet.

**Acceptance:**
- Pi boots Bookworm 64-bit (Pi 4B or Pi 5; arm64 enforced by the setup script)
- SSH key auth working, password auth disabled
- `git`, `python3.11`, `node 20`, `systemd` all present
- Screen attached and displaying desktop
- Hostname set to `truckdash`
- User `truckdash` created with appropriate group memberships (`dialout`, `gpio`, `video`, `plugdev`)

### Phase 1 — CarPlay core (est. 2 days)

Get wireless CarPlay working alone, no overlays, no other services. This is the highest-risk phase because the Carlinkit driver path is finicky.

**Acceptance:**
- iPhone connects wirelessly and CarPlay UI displays
- Sustained 30 fps minimum during typical use (map scrolling, music playback)
- Touch input works
- Audio routes correctly to the USB DAC
- System survives unplug/replug of the Carlinkit dongle without reboot
- `truckdash-carplay.service` starts on boot and auto-restarts on crash

### Phase 2 — OBD2 service + overlay (est. 3 days)

Add the OBD2 service and a transparent React overlay showing gauges on top of CarPlay.

**Acceptance:**
- OBDLink EX autodetected on USB at a stable `/dev/obdlink` symlink
- At least 6 PIDs readable at ≥ 2 Hz simultaneously: RPM, coolant temp, ICP, IPR, FICM voltage, EOT (or the 7.3L-specific equivalents via Mode 22)
- Overlay UI reads the local WebSocket and displays the PIDs at the configured refresh rate without flicker
- Overlay is positioned in a corner by default, user-configurable via `gauges.toml`
- Overlay does not block CarPlay touch input outside the overlay's own bounds
- If the OBD2 adapter is absent or vehicle is off, service logs and retries, does not crash
- CSV log is written to `/var/log/truckdash/obd2/YYYY-MM-DD.csv` with one row per sample

### Phase 3 — Reverse camera (est. 2 days)

Add the camera service with GPIO trigger and Wayland layer preemption.

**Acceptance:**
- Reverse light voltage change is detected within 100 ms on GPIO
- Camera feed appears fullscreen within 500 ms of reverse engagement
- Camera feed disappears within 1 second of reverse disengagement
- Feed resolution at least 720p, frame rate at least 20 fps
- Latency from camera to screen ≤ 200 ms (measured with a stopwatch on-screen)
- If the camera is unplugged, the service logs and retries, does not crash
- Reverse event while CarPlay is showing a full-screen map does not leave orphan touches or modal dialogs on return

### Phase 4 — GPS and offline nav (est. 2 days)

Add `gpsd` and an offline nav UI. OsmAnd is the preferred app but any offline-capable nav is acceptable if it can be wrapped in the compositor.

**Acceptance:**
- `gpsd` publishes valid fixes within 60 seconds of clear-sky power-on
- Offline tiles for Texas are pre-downloaded and rendered without network
- Nav UI is accessible from the main UI with a single tap
- Turn-by-turn voice prompts route to the audio out
- No crashes when GPS signal is lost (e.g., in a garage)

### Phase 5 — Power management and ignition behavior (est. 2 days)

Make the system behave correctly with respect to the truck's electrical system.

**Acceptance:**
- System begins boot within 3 seconds of ignition-on
- System reaches CarPlay-ready state in ≤ 45 seconds
- System performs clean shutdown within 30 seconds of ignition-off
- System survives a cold-crank voltage sag (bench-tested with a variable supply dropping to 6V briefly)
- No filesystem corruption across 50 consecutive clean shutdowns
- No filesystem corruption across 10 consecutive hard power pulls (with the UPS HAT absorbing the difference)

### Phase 6 — Polish and install (est. 2 days)

Harden logging, add a settings UI, physically install in the truck.

**Acceptance:**
- Journal-based logging for all services, with log rotation configured
- Simple settings UI for: selecting which PIDs are visible, adjusting overlay position, triggering a manual shutdown
- Physical install: screen is secure, all cables strain-relieved, no heat/vibration issues after a 1-hour drive
- Failure of any one service does not take down the others (CarPlay must keep working even if the OBD2 adapter is disconnected)

---

## 6. Service specifications

### 6.1 `truckdash-carplay`

- **Language:** TypeScript / Electron
- **Upstream:** fork `rhysmorgan134/react-carplay`; keep the fork clean and rebase-able on upstream
- **Runtime:** Electron window, fullscreen, frameless, always layer 0 in the compositor
- **Input:** Carlinkit CPC200-CCPA over USB (vendor/product IDs must be pinned in a `udev` rule)
- **Output:** Video on the HDMI display, audio on the configured ALSA device
- **Config:** `/opt/truckdash/config/truckdash.toml` → `[carplay]` section
- **Logs:** `journalctl -u truckdash-carplay`
- **Failure mode:** auto-restart via systemd; exponential backoff after 3 consecutive crashes

### 6.2 `truckdash-obd2`

- **Language:** Python 3.11
- **Key library:** `python-OBD` (for ELM327 protocol), `websockets` (for publishing)
- **7.3L specifics:** must support Ford Mode 22 enhanced PIDs for ICP, IPR, FICM voltage, EBPV position, EOT. Standard Mode 01 is insufficient.
- **PID list:** defined in `obd2.toml`, each entry specifies PID, sample rate, scaling, units, and display name
- **Sampling strategy:** round-robin through the PID list at each service's configured rate, adaptive backoff if ECU is unresponsive
- **Publishing:** WebSocket server on `ws://127.0.0.1:8765` with JSON messages `{pid, value, unit, ts}`
- **Logging:** CSV to `/var/log/truckdash/obd2/YYYY-MM-DD.csv`, rotated daily, retained 90 days
- **Failure modes:**
  - Adapter disconnected → log warning, retry every 5s, do not crash
  - Vehicle off (no response) → log info, retry every 30s
  - Malformed response → log, skip, continue
- **Config:** `/opt/truckdash/config/obd2.toml`

### 6.3 `truckdash-gps`

- Use stock Debian `gpsd` package. Do not write a custom GPS service.
- Systemd unit should be a thin wrapper that ensures `gpsd` points at the correct USB device and starts after `truckdash.target` is ready
- Downstream consumers (nav UI, overlay if showing speed) read from `gpsd`'s standard socket at `127.0.0.1:2947`

### 6.4 `truckdash-camera`

- **Language:** Python 3.11
- **Key libraries:** `gpiozero` (GPIO), `gstreamer` via `python-gst`
- **GPIO:** reverse trigger on a configurable BCM pin (default: GPIO 17), active-high, debounced 50ms
- **Video source:** first UVC device found, fallback to a configured device path
- **Video sink:** Wayland layer-shell surface at layer 2 (top), fullscreen
- **Behavior:**
  - Reverse engaged → start pipeline, raise surface, render feed
  - Reverse disengaged → 1-second grace period, then tear down pipeline and hide surface
- **Failure modes:**
  - Camera unplugged → log, retry on next trigger
  - GStreamer pipeline error → log, retry once, give up after 3 failures until next trigger
- **Config:** `/opt/truckdash/config/truckdash.toml` → `[camera]` section

### 6.5 `truckdash-compositor`

- **Compositor:** `labwc` preferred; `cage` as fallback if `labwc` proves too heavy
- **Layers:**
  - Layer 0 (bottom): CarPlay window
  - Layer 1 (middle): OBD2 overlay / nav UI
  - Layer 2 (top): camera feed (only visible when triggered)
- **No desktop environment.** No GNOME, no KDE, no Wayfire desktop shell.
- **Config:** compositor config files in `/opt/truckdash/compositor/`

### 6.6 `truckdash-supervisor`

- **Language:** Python 3.11
- **Responsibilities:**
  - Health checks each other service every 10 seconds (is the systemd unit active? is the websocket reachable?)
  - Logs service state transitions
  - Exposes a local-only HTTP endpoint on `127.0.0.1:9000/status` returning JSON with all service states
  - Drives the boot splash screen (a simple fullscreen image while services are starting)
  - Initiates clean shutdown on ignition-off signal from the UPS HAT

---

## 7. Configuration

All configuration lives in TOML files under `/opt/truckdash/config/`. No environment variables for runtime config. No hardcoded paths in source.

### 7.1 `truckdash.toml` (global)

```toml
[system]
hostname = "truckdash"
log_dir = "/var/log/truckdash"

[carplay]
carlinkit_vendor_id = "1314"
carlinkit_product_id = "1520"
audio_device = "hw:USB_DAC,0"
target_fps = 60

[camera]
reverse_gpio_pin = 17
video_device = "/dev/video0"
grace_period_seconds = 1
resolution = "1280x720"
framerate = 30

[compositor]
backend = "labwc"

[supervisor]
status_port = 9000
health_check_interval_seconds = 10
```

### 7.2 `obd2.toml`

```toml
[adapter]
device = "/dev/ttyUSB0"
baudrate = 115200
protocol = "auto"

[[pids]]
name = "rpm"
display = "RPM"
mode = "01"
pid = "0C"
rate_hz = 5
units = "rpm"

[[pids]]
name = "icp"
display = "ICP"
mode = "22"
pid = "1434"
rate_hz = 2
units = "psi"
scale = 0.145
# ...etc
```

### 7.3 `gauges.toml`

```toml
[overlay]
position = "top-right"
opacity = 0.85
background = "rgba(0,0,0,0.5)"

[[gauges]]
pid = "rpm"
type = "numeric"
size = "large"

[[gauges]]
pid = "icp"
type = "numeric"
size = "medium"
warn_above = 3500
```

---

## 8. Logging and observability

- All services log to `systemd-journald` via stdout/stderr
- The OBD2 service additionally writes CSV data to `/var/log/truckdash/obd2/`
- Log rotation via `systemd-journald`'s built-in retention (max 500MB, max 30 days)
- Supervisor exposes `/status` on `127.0.0.1:9000` for at-a-glance system health
- No remote logging in v1. No Datadog, no Prometheus, no Grafana.

---

## 9. Testing strategy

### 9.1 Per-service unit tests

- Python services use `pytest`
- TypeScript uses `vitest`
- Hardware interfaces are mocked at the library boundary (e.g., mock `python-OBD`'s `OBD()` class, do not mock USB)

### 9.2 Integration tests

A `/opt/truckdash/scripts/integration-test.sh` script that:

- Brings up all services on the bench
- Starts a mock OBD2 adapter (using `obd-sim` or equivalent)
- Verifies each service's health endpoint
- Simulates reverse GPIO trigger
- Verifies overlay shows correct mock data

### 9.3 Vehicle tests

Manual checklists per phase, executed in the driveway before road testing. Each phase's acceptance criteria become a checklist.

---

## 10. Security and safety

- No inbound network services exposed outside `127.0.0.1`
- SSH is the only remote access; keys only, no passwords
- CarPlay dongle is the *only* USB device that auto-mounts as mass storage allowed; all others denied by `udev`
- Display must never show content that obscures the driver's forward view (overlay opacity capped at 0.9)
- Backup camera behavior is safety-critical: if the camera service is uncertain of state, it MUST show the camera feed rather than hide it (fail-visible, not fail-silent)
- System must not require driver attention to recover from common faults; all recovery is automatic

---

## 11. Open questions

1. ~~Does the 2001 F-250 PCM support OBD-II Mode 22 reliably, or are some enhanced PIDs only available through Ford's proprietary MS-CAN? If MS-CAN, the OBDLink SX is insufficient and we need an OBDLink MX+.~~ **Resolved:** switched to OBDLink EX, which covers MS-CAN and Ford-specific PIDs natively. FORScan capture logs from 2026-04-07/08 confirm EOT, ICP, IPR, FUELPW, RPM, VREF, VPWR all read on this PCM via Mode 22; raw PID numbers + formulas still need a driveway session with the OBDLink before enabling in `obd2.toml`. TFT/TOT not observed in existing captures — verify separately.
2. ~~NVMe boot on Pi 5 — confirm the specific HAT and SSD combination before committing.~~ **Obsolete:** Pi 4B has no PCIe. Reopen if/when we upgrade to Pi 5.
3. ~~Will Pi 4B/4GB hold framerate through Phase 5 with two Electron shells (CarPlay + overlay), a Wayland compositor, and offline nav resident at the same time?~~ **Resolved during Phase 1 bring-up on 2026-04-24:** no. Even the single CarPlay Electron shell is unusable on the 4B under load — a `gl.readPixels` pipeline stall in react-carplay's WebGL2 fallback path makes mouse input ~30 s delayed. Root cause is the 4B's V3D 4.2 not supporting the Vulkan surface WebGPU needs, forcing the WebGL2 code path. Moved to Pi 5 8GB; Phase 1 will be re-verified there. See `docs/phase1-notes.md`.
4. Exact model of UPS HAT with supercap that survives engine cranking. Waveshare UPS HAT (C) is a candidate; needs validation.
5. Is head-unit replacement (for the aux input) in scope, or a pre-requisite assumed-done?

---

## 12. Glossary

- **PID** — Parameter ID, an OBD-II identifier for a specific engine parameter
- **Mode 22** — OBD-II "read enhanced parameter" service, used for manufacturer-specific PIDs
- **ICP** — Injection Control Pressure, the high-pressure oil feeding the 7.3L HEUI injectors
- **IPR** — Injection Pressure Regulator, the valve controlling ICP
- **FICM** — Fuel Injection Control Module, drives the 7.3L injectors
- **EBPV** — Exhaust Back Pressure Valve, the 7.3L's warm-up aid
- **EOT** — Engine Oil Temperature
- **Layer shell** — Wayland protocol for positioning surfaces in a Z-ordered stack above/below the normal window layer
