#!/usr/bin/env bash
# launch.sh — entry point for truckdash-overlay.service.
#
# Runs the compiled Electron overlay on top of the CarPlay window. Assumes
# `npm install && npm run build` have been run (see install-overlay.sh).

set -euo pipefail

cd "$(dirname "$0")"

ELECTRON_BIN=node_modules/.bin/electron
[[ -x "$ELECTRON_BIN" ]] || { echo "electron not installed — run 'npm install' in $(pwd)"; exit 1; }
[[ -d dist ]]            || { echo "renderer not built — run 'npm run build'";             exit 1; }
[[ -d dist-electron ]]   || { echo "electron main not compiled — run 'npm run build'";     exit 1; }

exec "$ELECTRON_BIN" .
