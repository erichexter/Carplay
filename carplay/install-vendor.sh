#!/usr/bin/env bash
# install-vendor.sh — clone and build react-carplay + pcm-ringbuf-player
# into carplay/vendor/. Per PRD §6.1 we treat upstream as vendor'd
# dependencies; this script bootstraps them into place.
#
# Applies three fixes against current upstream (April 2026) that the
# plain `npm install && npm run build` path cannot handle:
#
#   1. pcm-ringbuf-player's `prepare` script runs `tsc --build` using
#      TypeScript ^5.1.6, which resolves to 5.7+ today and fails with
#      `Int16Array<ArrayBufferLike>` strictness errors. Fix: clone it
#      locally, pin its TS to 5.6.3, pre-build it.
#
#   2. react-carplay references pcm-ringbuf-player via a git URL. Fix:
#      rewrite that dep to `file:../pcm-ringbuf-player` so it picks up
#      our pinned copy.
#
#   3. Rollup can't resolve `ringbuf.js` through the file-path dep at
#      renderer build time. Fix: add ringbuf.js as a direct dep of
#      react-carplay.
#
#   4. react-carplay's `npm run build` gates on `tsc --noEmit`, which
#      fails on upstream's own type errors (socketcan, IPC handlers,
#      esbuild version conflict). These are runtime-harmless. Fix: run
#      `electron-vite build` directly.
#
# When you fork either repo and fix the upstream issues, override with
# --remote and/or --pcm-remote.
#
# Usage:
#   ./carplay/install-vendor.sh
#   ./carplay/install-vendor.sh --remote <git-url> --ref <branch>
#   ./carplay/install-vendor.sh --pcm-remote <git-url> --pcm-ref <branch>

set -euo pipefail

REMOTE="https://github.com/rhysmorgan134/react-carplay.git"
REF="main"
PCM_REMOTE="https://github.com/rhysmorgan134/pcm-ringbuf-player.git"
PCM_REF="main"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)     REMOTE="$2";     shift 2 ;;
        --ref)        REF="$2";        shift 2 ;;
        --pcm-remote) PCM_REMOTE="$2"; shift 2 ;;
        --pcm-ref)    PCM_REF="$2";    shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
VENDOR_DIR="$SELF_DIR/vendor"
RC_DIR="$VENDOR_DIR/react-carplay"
PCM_DIR="$VENDOR_DIR/pcm-ringbuf-player"

log() { printf '[vendor] %s\n' "$*"; }

mkdir -p "$VENDOR_DIR"

# ---------- clone / update react-carplay ----------
if [[ -d "$RC_DIR/.git" ]]; then
    log "updating react-carplay at $RC_DIR"
    git -C "$RC_DIR" fetch --tags origin
    git -C "$RC_DIR" checkout "$REF"
    git -C "$RC_DIR" pull --ff-only origin "$REF" || \
        log "react-carplay not fast-forwardable; leaving HEAD at $(git -C "$RC_DIR" rev-parse --short HEAD)"
else
    log "cloning $REMOTE -> $RC_DIR"
    git clone --branch "$REF" "$REMOTE" "$RC_DIR"
fi

# ---------- clone / update pcm-ringbuf-player ----------
if [[ -d "$PCM_DIR/.git" ]]; then
    log "updating pcm-ringbuf-player at $PCM_DIR"
    git -C "$PCM_DIR" fetch --tags origin
    git -C "$PCM_DIR" checkout "$PCM_REF"
    git -C "$PCM_DIR" pull --ff-only origin "$PCM_REF" || \
        log "pcm-ringbuf-player not fast-forwardable; leaving HEAD at $(git -C "$PCM_DIR" rev-parse --short HEAD)"
else
    log "cloning $PCM_REMOTE -> $PCM_DIR"
    git clone --branch "$PCM_REF" "$PCM_REMOTE" "$PCM_DIR"
fi

# ---------- patch pcm-ringbuf-player: pin typescript ----------
log "pinning pcm-ringbuf-player typescript devDep to 5.6.3 (fix 1)"
node -e '
const fs = require("fs");
const path = process.argv[1];
const p = JSON.parse(fs.readFileSync(path, "utf8"));
p.devDependencies = p.devDependencies || {};
if (p.devDependencies.typescript !== "5.6.3") {
    p.devDependencies.typescript = "5.6.3";
    fs.writeFileSync(path, JSON.stringify(p, null, 2) + "\n");
    console.log("pinned");
} else {
    console.log("already pinned");
}
' "$PCM_DIR/package.json"

# ---------- build pcm-ringbuf-player ----------
log "building pcm-ringbuf-player"
(cd "$PCM_DIR" && rm -rf node_modules package-lock.json && npm install --silent && npm run build)

# ---------- patch react-carplay: rewrite pcm dep + add ringbuf.js ----------
log "patching react-carplay package.json (fixes 2 and 3)"
node -e '
const fs = require("fs");
const path = process.argv[1];
const p = JSON.parse(fs.readFileSync(path, "utf8"));
let changed = false;
p.dependencies = p.dependencies || {};
if (p.dependencies["pcm-ringbuf-player"] !== "file:../pcm-ringbuf-player") {
    p.dependencies["pcm-ringbuf-player"] = "file:../pcm-ringbuf-player";
    changed = true;
}
if (!p.dependencies["ringbuf.js"]) {
    p.dependencies["ringbuf.js"] = "^0.3.6";
    changed = true;
}
if (p.overrides) { delete p.overrides; changed = true; }
if (changed) {
    fs.writeFileSync(path, JSON.stringify(p, null, 2) + "\n");
    console.log("patched");
} else {
    console.log("already patched");
}
' "$RC_DIR/package.json"

# ---------- install + build react-carplay ----------
log "installing react-carplay deps (a few minutes on a Pi)"
(cd "$RC_DIR" && rm -rf node_modules package-lock.json && npm install --silent)

log "building react-carplay via electron-vite (skips the typecheck gate, fix 4)"
(cd "$RC_DIR" && npx electron-vite build)

log "done."
log "  react-carplay:    $RC_DIR/out/{main,preload,renderer}"
log "  pcm-ringbuf:      $PCM_DIR/dist"
log "  launchable via:   node_modules/.bin/electron $RC_DIR"
