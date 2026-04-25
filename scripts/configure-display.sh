#!/usr/bin/env bash
# configure-display.sh — detect the active panel size and write the per-
# screen configs that depend on it: labwc windowRules (CarPlay anchor +
# overlay anchor) and react-carplay's BrowserWindow size.
#
# Run once after install.sh, and re-run any time you swap the display.
# Pass WIDTHxHEIGHT explicitly to override detection (useful for testing
# a layout for a smaller screen before unplugging the dev panel).
#
# Usage:
#   sudo ./scripts/configure-display.sh
#   sudo ./scripts/configure-display.sh 1280x800

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (sudo)" >&2
    exit 1
fi

log() { printf '[configure-display] %s\n' "$*"; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ---------- detect resolution ----------
# /sys/class/drm/*/modes' first line is the kernel's preferred mode for
# the connected panel. wlr-randr would be more accurate (reports the
# *current* mode after labwc may have downgraded), but it requires
# WAYLAND_DISPLAY and isn't installed by default on Bookworm.
detect_resolution() {
    local f mode
    for f in /sys/class/drm/card*-HDMI*/modes /sys/class/drm/card*-DSI*/modes; do
        [[ -s "$f" ]] || continue
        mode=$(head -1 "$f")
        [[ -n "$mode" ]] && { echo "$mode"; return; }
    done
    return 1
}

RES="${1:-}"
if [[ -z "$RES" ]]; then
    RES=$(detect_resolution || true)
fi
if [[ -z "$RES" || ! "$RES" =~ ^[0-9]+x[0-9]+$ ]]; then
    echo "could not detect resolution; pass it explicitly:  $0 1920x1080" >&2
    exit 2
fi

SCREEN_W="${RES%x*}"
SCREEN_H="${RES#*x}"

# ---------- compute the split ----------
# Overlay strip is 25% of screen width, clamped to [320, 800] and rounded
# down to a 16-pixel boundary so the gauge layout never lands on awkward
# fractional values. CarPlay takes the rest. Same formula as in
# ui-overlay/electron/main.ts so labwc and Electron agree about the
# initial geometry; if you change one, change the other.
OVERLAY_W=$(( SCREEN_W / 4 ))
(( OVERLAY_W < 320 )) && OVERLAY_W=320
(( OVERLAY_W > 800 )) && OVERLAY_W=800
OVERLAY_W=$(( OVERLAY_W / 16 * 16 ))
CARPLAY_W=$(( SCREEN_W - OVERLAY_W ))
OVERLAY_X="$CARPLAY_W"

log "panel=${SCREEN_W}x${SCREEN_H} carplay=${CARPLAY_W}x${SCREEN_H} at 0,0  overlay=${OVERLAY_W}x${SCREEN_H} at ${OVERLAY_X},0"

# ---------- write labwc rc.xml ----------
# The base rc.xml in /etc/xdg/labwc has the rest of the user's preferences
# (theme, keybinds). Seed our copy from there if missing, then surgically
# replace any pre-existing TruckDash rules with computed ones.
LABWC_DIR=/home/truckdash/.config/labwc
LABWC_RC="$LABWC_DIR/rc.xml"
install -d -o truckdash -g truckdash -m 0755 "$LABWC_DIR"
if [[ ! -f "$LABWC_RC" ]]; then
    if [[ -f /etc/xdg/labwc/rc.xml ]]; then
        install -o truckdash -g truckdash -m 0644 \
            /etc/xdg/labwc/rc.xml "$LABWC_RC"
    else
        # No system default — synthesize a minimal stub.
        cat > "$LABWC_RC" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <windowRules>
  </windowRules>
</openbox_config>
XML
        chown truckdash:truckdash "$LABWC_RC"
    fi
fi

python3 - "$LABWC_RC" "$CARPLAY_W" "$SCREEN_H" "$OVERLAY_W" "$OVERLAY_X" <<'PYEOF'
import sys, re
path, cw, sh, ow, ox = sys.argv[1:]
cw, sh, ow, ox = int(cw), int(sh), int(ow), int(ox)
src = open(path).read()

rules = (
    f'    <windowRule identifier="truckdash-carplay">\n'
    f'      <action name="MoveTo" x="0" y="0"/>\n'
    f'      <action name="ResizeTo" width="{cw}" height="{sh}"/>\n'
    f'    </windowRule>\n'
    f'    <windowRule title="TruckDash CarPlay">\n'
    f'      <action name="MoveTo" x="0" y="0"/>\n'
    f'      <action name="ResizeTo" width="{cw}" height="{sh}"/>\n'
    f'    </windowRule>\n'
    f'    <windowRule title="TruckDash overlay">\n'
    f'      <action name="MoveTo" x="{ox}" y="0"/>\n'
    f'      <action name="ResizeTo" width="{ow}" height="{sh}"/>\n'
    f'    </windowRule>\n'
)

# Strip prior TruckDash rules (re-runs should be idempotent).
src = re.sub(
    r'\s*<windowRule\s+(?:identifier="truckdash-carplay"|title="TruckDash[^"]*").*?</windowRule>',
    '',
    src,
    flags=re.DOTALL,
)
# Inject before </windowRules>; create the block if absent.
if '</windowRules>' in src:
    src = src.replace('</windowRules>', rules + '  </windowRules>')
else:
    src = src.replace('</openbox_config>', f'  <windowRules>\n{rules}  </windowRules>\n</openbox_config>')

open(path, 'w').write(src)
PYEOF
chown truckdash:truckdash "$LABWC_RC"
log "wrote $LABWC_RC"

# ---------- write react-carplay config.json ----------
# Update only width/height so other settings the user may have toggled
# (kiosk, fps, mediaDelay, ...) survive.
RC_CONFIG=/home/truckdash/.config/react-carplay/config.json
install -d -o truckdash -g truckdash -m 0755 "$(dirname "$RC_CONFIG")"
if [[ ! -f "$RC_CONFIG" ]] && [[ -f "$REPO_ROOT/config/react-carplay-config.json" ]]; then
    install -o truckdash -g truckdash -m 0644 \
        "$REPO_ROOT/config/react-carplay-config.json" "$RC_CONFIG"
fi
if [[ -f "$RC_CONFIG" ]]; then
    python3 - "$RC_CONFIG" "$CARPLAY_W" "$SCREEN_H" <<'PYEOF'
import json, sys
p, w, h = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
c = json.load(open(p))
c["width"], c["height"] = w, h
json.dump(c, open(p, "w"))
PYEOF
    chown truckdash:truckdash "$RC_CONFIG"
    log "updated $RC_CONFIG (width=$CARPLAY_W height=$SCREEN_H)"
fi

# ---------- reload + restart ----------
if pgrep -x labwc >/dev/null; then
    pkill -HUP -x labwc || true
    log "SIGHUP'd labwc to reload windowRules"
fi
for svc in truckdash-carplay truckdash-overlay; do
    if systemctl is-active --quiet "$svc"; then
        systemctl restart "$svc"
        log "restarted $svc"
    fi
done

log "done."
