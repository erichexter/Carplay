#!/usr/bin/env bash
# install.sh — deploy this repo's contents to /opt/truckdash and install
# the Phase 1 systemd unit + udev rule.
#
# Run from the repo root on the Pi after phase0-setup.sh has completed.
#
# Usage:
#   sudo ./scripts/install.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (sudo)" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX=/opt/truckdash

log() { printf '[install] %s\n' "$*"; }

if ! id -u truckdash >/dev/null 2>&1; then
    echo "user truckdash missing — run phase0-setup.sh first" >&2
    exit 1
fi

# ---------- sync code ----------
# rsync is tidier, but avoid requiring it. Use cp -a.
log "syncing repo -> $PREFIX"
install -d -o truckdash -g truckdash -m 0755 "$PREFIX"

for sub in carplay obd2 ui-overlay config scripts; do
    [[ -d "$REPO_ROOT/$sub" ]] || continue
    log "  $sub/"
    cp -a "$REPO_ROOT/$sub" "$PREFIX/"
done

chown -R truckdash:truckdash "$PREFIX"

# Restore exec bits — they may not survive a clone from a Windows dev box.
for f in \
    "$PREFIX/scripts/phase0-setup.sh" \
    "$PREFIX/scripts/install.sh" \
    "$PREFIX/carplay/launch.sh" \
    "$PREFIX/carplay/install-vendor.sh" \
    "$PREFIX/ui-overlay/launch.sh" \
    "$PREFIX/ui-overlay/install-overlay.sh"; do
    [[ -f "$f" ]] && chmod +x "$f"
done

# ---------- obd2 python venv ----------
if [[ -d "$PREFIX/obd2" ]]; then
    log "setting up obd2 python venv"
    sudo -u truckdash python3 -m venv "$PREFIX/obd2/.venv"
    sudo -u truckdash "$PREFIX/obd2/.venv/bin/pip" install --quiet --upgrade pip
    sudo -u truckdash "$PREFIX/obd2/.venv/bin/pip" install --quiet -e "$PREFIX/obd2"
fi

# ---------- udev ----------
log "installing udev rules"
install -m 0644 "$REPO_ROOT/udev/99-truckdash.rules" /etc/udev/rules.d/99-truckdash.rules
udevadm control --reload-rules
udevadm trigger

# ---------- systemd units ----------
log "installing systemd units"
for unit in \
    truckdash.target \
    truckdash-carplay.service \
    truckdash-obd2.service \
    truckdash-overlay.service; do
    src="$REPO_ROOT/systemd/$unit"
    [[ -f "$src" ]] || continue
    install -m 0644 "$src" "/etc/systemd/system/$unit"
done
systemctl daemon-reload

log "enabling units"
systemctl enable truckdash.target
for svc in truckdash-carplay truckdash-obd2 truckdash-overlay; do
    [[ -f "/etc/systemd/system/${svc}.service" ]] && systemctl enable "${svc}.service"
done

log "done. to start now:  sudo systemctl start truckdash.target"
log "to watch logs:        journalctl -u truckdash-carplay -u truckdash-obd2 -u truckdash-overlay -f"
