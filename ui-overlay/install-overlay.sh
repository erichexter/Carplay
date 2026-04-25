#!/usr/bin/env bash
# install-overlay.sh — install deps and build the overlay. Run once after
# scripts/install.sh has synced this directory to /opt/truckdash/ui-overlay/.
#
# Usage:
#   sudo -u truckdash /opt/truckdash/ui-overlay/install-overlay.sh

set -euo pipefail

cd "$(dirname "$0")"

echo "[overlay] npm install"
npm install

echo "[overlay] build"
npm run build

echo "[overlay] done. start with: sudo systemctl start truckdash-overlay.service"
