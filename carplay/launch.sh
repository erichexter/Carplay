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
# GPU rasterization + zero-copy + ignore-blocklist help on any Pi: V3D
# is blocklisted by default and software raster eats CPU. Keep these on
# both Pi 4B and Pi 5.
#
# Pi 5 (V3D 7.1) has working Vulkan, so we let WebGPU initialize natively.
# On the Pi 4B (V3D 4.2 / v3dv) this loop-spammed Dawn with
# "fullDrawIndexUint32 required" — if we ever boot a Pi 4B again, add
# `--disable-features=Vulkan --use-gl=angle --use-angle=gles` back.
ELECTRON_FLAGS=(
    --ozone-platform=wayland
    --ignore-gpu-blocklist
    --enable-gpu-rasterization
    --enable-zero-copy
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
