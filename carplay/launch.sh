#!/usr/bin/env bash
# launch.sh — entry point for truckdash-carplay.service.
#
# Reads config from /opt/truckdash/config/truckdash.toml and execs the
# built react-carplay Electron app from carplay/vendor/react-carplay.
#
# This script exists so that the systemd unit can be stable while the
# react-carplay build artefacts (binary name, path) may move as upstream
# changes. Keep the unit pointing here, adapt here when upstream shifts.

set -euo pipefail

log() { printf '[carplay] %s\n' "$*"; }
fail() { printf '[carplay] FAIL: %s\n' "$*" >&2; exit 1; }

CONFIG=/opt/truckdash/config/truckdash.toml
VENDOR_DIR="$(cd "$(dirname "$0")" && pwd)/vendor/react-carplay"

[[ -f "$CONFIG" ]] || fail "config missing: $CONFIG"
[[ -d "$VENDOR_DIR" ]] || fail "react-carplay not installed — run carplay/install-vendor.sh"

# --- minimal TOML reader for the [carplay] section ---
# Avoids a python dep in the hot launch path. Only reads the two keys we care
# about at launch time; the react-carplay app itself reads its own settings.
get_carplay_key() {
    local key="$1"
    awk -v key="$key" '
        /^\[.*\]/ { section = $0; next }
        section == "[carplay]" && $1 == key {
            # split on = and trim quotes + whitespace
            sub(/^[^=]*=[[:space:]]*/, "")
            gsub(/^"|"$/, "")
            print
            exit
        }
    ' "$CONFIG"
}

VID="$(get_carplay_key carlinkit_vendor_id)"
PID="$(get_carplay_key carlinkit_product_id)"
AUDIO="$(get_carplay_key audio_device)"

log "config: carlinkit=${VID}:${PID} audio=${AUDIO}"

# --- precheck: Carlinkit present? ---
# Not fatal — the dongle may be plugged in later. react-carplay handles hotplug.
# We just log for diagnostics.
if command -v lsusb >/dev/null 2>&1; then
    if lsusb -d "${VID}:${PID}" >/dev/null 2>&1; then
        log "carlinkit dongle detected"
    else
        log "carlinkit dongle NOT detected — will wait for hotplug"
    fi
fi

# --- locate the built binary ---
# react-carplay ships as an Electron app. After `npm run build` (or the
# distribution step) the launchable binary lives somewhere under the vendor
# tree. Probe a few common locations; adjust install-vendor.sh if you pin
# a specific packaging.
CANDIDATES=(
    "$VENDOR_DIR/dist/linux-arm64-unpacked/react-carplay"
    "$VENDOR_DIR/dist/linux-arm64-unpacked/electron"
    "$VENDOR_DIR/node_modules/.bin/electron"
)

BIN=""
for c in "${CANDIDATES[@]}"; do
    if [[ -x "$c" ]]; then
        BIN="$c"
        break
    fi
done

[[ -n "$BIN" ]] || fail "no executable found under $VENDOR_DIR/dist — rebuild with install-vendor.sh"

log "exec: $BIN"

# --ozone-platform=wayland is required on labwc/Bookworm. Electron 27
# still defaults Ozone to X11 even on Wayland sessions, and the env-var
# hint (ELECTRON_OZONE_PLATFORM_HINT) is advisory — the flag is binding.
# Without it Electron aborts with "Missing X server or $DISPLAY".
#
# Pi 4B GPU tuning:
#   --disable-features=Vulkan
#       Pi 4's V3D 4.2 has only partial Vulkan via v3dv. Dawn init
#       spams "fullDrawIndexUint32 required" and churns.
#   --enable-gpu-rasterization --ignore-gpu-blocklist
#       Chromium blocklists the V3D driver by default — force raster
#       onto the GPU anyway.
#   --enable-zero-copy
#       Avoid a round-trip through system memory for textures.
#
# The gbm SCANOUT errors in the journal are cosmetic — Chromium retries
# without SCANOUT and ends up composited in software. Accepting that on
# Pi 4B; Pi 5 upgrade path will fix the dma_buf scanout story.
ELECTRON_FLAGS=(
    --ozone-platform=wayland
    --ignore-gpu-blocklist
    --enable-gpu-rasterization
    # Pi 4B-only workarounds we removed on Pi 5:
    #   --disable-features=Vulkan / --use-gl=angle / --use-angle=gles
    #     Pi 4's V3D 4.2 had broken v3dv; Pi 5's V3D 7.1 has working
    #     Vulkan, so let WebGPU init natively.
    #   --enable-zero-copy
    #     Demands SCANOUT-eligible buffers — fine for fullscreen kiosk
    #     surfaces, breaks windowed (kiosk:false) compositing on labwc.
    # If we ever boot a Pi 4B again, restore the first three flags. The
    # zero-copy stays off so kiosk-toggling works on either Pi.
)

# For the dev-mode electron binary, point it at the app directory. For a
# packaged binary, it's self-contained.
case "$BIN" in
    */node_modules/.bin/electron)
        exec "$BIN" "${ELECTRON_FLAGS[@]}" "$VENDOR_DIR"
        ;;
    *)
        exec "$BIN" "${ELECTRON_FLAGS[@]}"
        ;;
esac
