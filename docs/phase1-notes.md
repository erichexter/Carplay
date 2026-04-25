# Phase 1 — CarPlay core, bring-up notes

Written 2026-04-24 after getting wireless CarPlay rendering on a Pi 4B 4GB,
before migrating to the Pi 5 8GB (ordered, arriving 2026-04-25).

## What works

- Carlinkit CPC200-CCPA (1314:1520) detected, udev rule grants `plugdev` the
  device, `/dev/carlinkit` symlinks to the active bus/device path.
- react-carplay (rhysmorgan134, HEAD of `main`) builds on Bookworm aarch64
  after the four patches `carplay/install-vendor.sh` applies.
- `truckdash-carplay.service` runs under `truckdash`, autologin wires up a
  Wayland seat at `/run/user/1001/wayland-0`, Electron renders the CarPlay
  UI fullscreen on HDMI via labwc.
- Phone pairs, video streams. Input via mouse works (no touchscreen yet).

## Pi 4B conclusion: ruled out

The 4B can render the CarPlay UI but input is ~30 s delayed under video
load. Root cause is architectural, not tuning:

- react-carplay's render worker has three paths: WebGPU → WebGL2 → WebGL.
- WebGPU needs Vulkan. Pi 4B's V3D 4.2 has only partial Vulkan via v3dv
  and Dawn init fails with `fullDrawIndexUint32 feature required`.
- Fallback is the WebGL2 path, which does `gl.readPixels()` on every
  decoded frame to copy video texture back to CPU. This pipelines-stalls
  the entire GL context (seen in logs as `GL_CLOSE_PATH_NV ... GPU stall
  due to ReadPixels`), which backs up Chromium's input thread.
- No Electron flag fixes this — the ReadPixels call is in the app. Pi 5's
  V3D 7.1 has working Vulkan → WebGPU path initializes → ReadPixels stall
  is bypassed entirely. Expectation on Pi 5: this specific problem goes
  away without code changes.

## Gotchas for future-me

**Replug-to-bootstrap WebUSB.** react-carplay's renderer only ever calls
`navigator.usb.getDevices()` / `findDevice()`, never `requestDevice()`.
On first launch with an empty user-data-dir the permission list is empty
and the UI is stuck on "Searching For Dongle". Unplugging and replugging
the CCPA after the service is up fires `onconnect`, Electron's
`setDevicePermissionHandler` (vendorId 4884) auto-grants, and
`getDevices()` starts returning the device on subsequent launches. If we
ever wipe `/home/truckdash/.config/react-carplay/`, replug will be
needed again.

**Ozone platform hint is advisory, not binding.** Electron 27 defaults
Ozone to X11 even on Wayland. `ELECTRON_OZONE_PLATFORM_HINT=wayland` in
the systemd unit is not enough; `--ozone-platform=wayland` on the CLI
is. `carplay/launch.sh` passes the flag.

**Audio config in `truckdash.toml` is currently wrong.** `hw:USB_DAC,0`
is a placeholder — there is no USB DAC yet. Available devices are
`bcm2835 Headphones`, `vc4-hdmi-0`, `vc4-hdmi-1`. Phase 1 renders video
without audio; set this before we expect sound through the truck.

**GPU log spam is cosmetic.** With the current flag set the GPU process
crashloops ~every 4 s on Pi 4B due to V3D gbm SCANOUT failures, but
the renderer still gets enough context to composite. Expect this to
stop on the Pi 5.

## Flags we landed on (`carplay/launch.sh`)

```
--ozone-platform=wayland       # required on labwc
--disable-features=Vulkan      # Pi 4B v3dv is incomplete; silences Dawn loop
--use-gl=angle --use-angle=gles # ANGLE→GLES keeps GPU compositing, lowered
                                # renderer CPU from 250% → ~70%
--ignore-gpu-blocklist
--enable-gpu-rasterization
--enable-zero-copy
```

On Pi 5, re-evaluate whether `--disable-features=Vulkan` can be dropped
(it would unlock WebGPU and skip the ReadPixels stall entirely — the
whole reason we're moving hardware).

## Post-Pi-5 re-test checklist

1. Reflash / restore to truckdash HW, run `scripts/phase0-setup.sh`.
2. Clone + `carplay/install-vendor.sh`, `scripts/install.sh`.
3. Start `truckdash-carplay.service`, replug CCPA once to bootstrap USB
   permission (see above).
4. Drop `--disable-features=Vulkan` from `launch.sh` and confirm:
   - renderer CPU stays low under streaming video
   - mouse input latency is conversational (<100 ms)
   - no `GPU stall due to ReadPixels` in the journal
5. If all three pass, Phase 1 is done on Pi 5. If any fail, revert the
   flag and re-open.
