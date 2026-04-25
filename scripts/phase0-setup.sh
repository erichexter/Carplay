#!/usr/bin/env bash
# phase0-setup.sh — TruckDash Phase 0 bench setup.
#
# Runs on a fresh Raspberry Pi (4B 4GB primary target, Pi 5 8GB supported)
# booted into Raspberry Pi OS Bookworm 64-bit. Brings the machine up to the
# Phase 0 acceptance criteria in PRD §5:
#   - Bookworm aarch64
#   - SSH key auth only
#   - git, python3.11, node 20, systemd present
#   - hostname set to `truckdash`
#   - `truckdash` user with dialout/gpio/video/plugdev groups
#   - zram swap enabled (2 GB-ish) — matters on the 4GB Pi 4B when both
#     Electron shells and nav are resident; harmless on the Pi 5
#
# Idempotent: safe to re-run.
#
# Usage:
#   sudo ./phase0-setup.sh [--skip-ssh-harden]
#
# The --skip-ssh-harden flag leaves sshd_config untouched. Useful on the
# first run before you've copied an authorized_keys in, so you don't lock
# yourself out.

set -euo pipefail

SKIP_SSH_HARDEN=0
for arg in "$@"; do
    case "$arg" in
        --skip-ssh-harden) SKIP_SSH_HARDEN=1 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (sudo)" >&2
    exit 1
fi

log() { printf '[phase0] %s\n' "$*"; }
fail() { printf '[phase0] FAIL: %s\n' "$*" >&2; exit 1; }

# ---------- preflight ----------
if ! grep -q 'VERSION_CODENAME=bookworm' /etc/os-release; then
    fail "this script targets Raspberry Pi OS Bookworm only"
fi

ARCH="$(dpkg --print-architecture)"
if [[ "$ARCH" != "arm64" ]]; then
    fail "expected arm64 (aarch64) architecture, got: $ARCH"
fi

# ---------- hostname ----------
CURRENT_HOSTNAME="$(hostnamectl --static)"
if [[ "$CURRENT_HOSTNAME" != "truckdash" ]]; then
    log "setting hostname to truckdash (was: $CURRENT_HOSTNAME)"
    hostnamectl set-hostname truckdash
    # Keep /etc/hosts in sync so sudo doesn't whine.
    if grep -qE '^127\.0\.1\.1\s' /etc/hosts; then
        sed -i -E "s/^(127\.0\.1\.1\s+).*/\1truckdash/" /etc/hosts
    else
        printf '127.0.1.1\ttruckdash\n' >> /etc/hosts
    fi
else
    log "hostname already truckdash"
fi

# ---------- apt packages ----------
log "apt update"
apt-get update -y

log "installing base packages"
apt-get install -y \
    git \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    pkg-config \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    libusb-1.0-0-dev \
    libudev-dev \
    usbutils \
    gpsd \
    gpsd-clients \
    zram-tools

# Bookworm's python3 is 3.11.x — verify.
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
log "python version: $PY_VER"
case "$PY_VER" in
    3.11|3.12|3.13) ;;
    *) fail "python $PY_VER too old; need 3.11+" ;;
esac

# Node 20 — Bookworm ships 18, so pull from NodeSource.
NEED_NODE=1
if command -v node >/dev/null 2>&1; then
    NODE_MAJOR="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
    if [[ "$NODE_MAJOR" -ge 20 ]]; then
        log "node $(node -v) already present"
        NEED_NODE=0
    fi
fi

if [[ "$NEED_NODE" -eq 1 ]]; then
    log "installing Node.js 20 from NodeSource"
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    chmod 0644 /etc/apt/keyrings/nodesource.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main' \
        > /etc/apt/sources.list.d/nodesource.list
    apt-get update -y
    apt-get install -y nodejs
fi

# ---------- truckdash user ----------
if id -u truckdash >/dev/null 2>&1; then
    log "user truckdash already exists"
else
    log "creating user truckdash"
    useradd --create-home --shell /bin/bash truckdash
fi

for group in dialout gpio video plugdev input render; do
    if getent group "$group" >/dev/null 2>&1; then
        if id -nG truckdash | tr ' ' '\n' | grep -qx "$group"; then
            : # already a member
        else
            log "adding truckdash to $group"
            usermod -aG "$group" truckdash
        fi
    else
        log "group $group missing on this system — skipping"
    fi
done

# ---------- filesystem layout ----------
log "creating /opt/truckdash and /var/log/truckdash"
install -d -o truckdash -g truckdash -m 0755 /opt/truckdash
install -d -o truckdash -g truckdash -m 0755 /var/log/truckdash
install -d -o truckdash -g truckdash -m 0755 /var/log/truckdash/obd2

# Logs symlink inside /opt/truckdash per PRD §4.4.
if [[ -e /opt/truckdash/logs && ! -L /opt/truckdash/logs ]]; then
    log "WARNING: /opt/truckdash/logs exists and is not a symlink — leaving alone"
elif [[ ! -L /opt/truckdash/logs ]]; then
    ln -s /var/log/truckdash /opt/truckdash/logs
fi

# ---------- zram swap ----------
# On the 4GB Pi 4B two Electron shells (carplay + overlay) plus a Wayland
# compositor plus navit can press against the 4GB ceiling. zram gives us
# a compressed in-RAM swap that's much faster than SD-card swap and wears
# nothing. Harmless on the Pi 5 8GB — it just won't get used.
ZRAM_CONF=/etc/default/zramswap
if [[ -f "$ZRAM_CONF" ]]; then
    if ! grep -qE '^\s*PERCENT\s*=' "$ZRAM_CONF"; then
        log "zramswap: appending PERCENT=50"
        printf '\n# truckdash phase0\nPERCENT=50\n' >> "$ZRAM_CONF"
    elif ! grep -qE '^\s*PERCENT\s*=\s*50' "$ZRAM_CONF"; then
        log "zramswap: updating PERCENT to 50"
        sed -i -E 's/^\s*PERCENT\s*=.*/PERCENT=50/' "$ZRAM_CONF"
    else
        log "zramswap: PERCENT=50 already set"
    fi
    systemctl enable --now zramswap.service >/dev/null 2>&1 || true
else
    log "zramswap config missing — zram-tools didn't install cleanly, skipping"
fi

# ---------- SSH hardening ----------
if [[ "$SKIP_SSH_HARDEN" -eq 1 ]]; then
    log "skipping SSH hardening (--skip-ssh-harden)"
else
    HAS_KEY=0
    for home in /home/*/; do
        if [[ -s "${home}.ssh/authorized_keys" ]]; then
            HAS_KEY=1
            break
        fi
    done
    if [[ -s /root/.ssh/authorized_keys ]]; then
        HAS_KEY=1
    fi

    if [[ "$HAS_KEY" -eq 0 ]]; then
        log "no authorized_keys found anywhere — refusing to disable password auth"
        log "copy your key in with ssh-copy-id first, then re-run this script"
    else
        log "hardening sshd_config: PasswordAuthentication no"
        SSHD=/etc/ssh/sshd_config
        # Comment out any existing setting, then append our canonical one.
        sed -i -E 's/^\s*PasswordAuthentication\s+.*/# &/' "$SSHD"
        sed -i -E 's/^\s*ChallengeResponseAuthentication\s+.*/# &/' "$SSHD"
        sed -i -E 's/^\s*PermitRootLogin\s+.*/# &/' "$SSHD"
        {
            echo ""
            echo "# --- truckdash phase0 ---"
            echo "PasswordAuthentication no"
            echo "ChallengeResponseAuthentication no"
            echo "PermitRootLogin prohibit-password"
        } >> "$SSHD"
        systemctl reload ssh || systemctl reload sshd || true
    fi
fi

# ---------- sanity report ----------
log "----- phase 0 summary -----"
log "os:       $(source /etc/os-release; echo "$PRETTY_NAME")"
log "arch:     $(dpkg --print-architecture)"
if [[ -r /sys/firmware/devicetree/base/model ]]; then
    # The DT model string is NUL-terminated — tr strips the trailing NUL.
    log "model:    $(tr -d '\0' </sys/firmware/devicetree/base/model)"
fi
log "ram:      $(awk '/MemTotal/ {printf "%.1f GB\n", $2/1024/1024}' /proc/meminfo)"
log "swap:     $(awk '/SwapTotal/ {printf "%.1f GB\n", $2/1024/1024}' /proc/meminfo) (zram included if enabled)"
log "hostname: $(hostnamectl --static)"
log "python:   $(python3 --version 2>&1)"
log "node:     $(node --version 2>&1)"
log "git:      $(git --version 2>&1)"
log "systemd:  $(systemctl --version | head -n1)"
log "user:     $(id truckdash)"
log "done."
