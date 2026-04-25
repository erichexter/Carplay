# scripts/

Deployment and bring-up scripts for TruckDash. Run on the Pi as root.

## `phase0-setup.sh`

Idempotent bench bring-up. Satisfies the Phase 0 acceptance criteria in
`PRD.md` §5: hostname, user, groups, base packages, SSH hardening.

```sh
# First run (no authorized_keys yet — don't lock yourself out):
sudo ./scripts/phase0-setup.sh --skip-ssh-harden

# After copying your key in:
ssh-copy-id pi@<pi-ip>
sudo ./scripts/phase0-setup.sh
```

Re-runs are safe.

## `install.sh`

Copies the repo into `/opt/truckdash`, installs the udev rule, installs
and enables the systemd units. Run after Phase 0 is complete.

```sh
sudo ./scripts/install.sh
```
