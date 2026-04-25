from pathlib import Path

from truckdash_obd2.config import load

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config" / "obd2.toml"


def test_loads_shipped_config():
    cfg = load(REPO_CONFIG)
    assert cfg.adapter.device == "/dev/obdlink"
    assert cfg.adapter.baudrate == 115200
    # Phase 2 acceptance: at least 6 PIDs configured.
    assert len(cfg.pids) >= 6, f"expected >=6 PIDs, got {len(cfg.pids)}"
    names = {p.name for p in cfg.pids}
    # Required from PRD §5 Phase 2 acceptance: RPM and coolant at minimum.
    assert "rpm" in names
    assert "coolant_temp" in names
    # Every PID must have a positive rate or the scheduler will spin.
    for p in cfg.pids:
        assert p.rate_hz > 0, f"{p.name} has non-positive rate"


def test_retry_defaults_present():
    cfg = load(REPO_CONFIG)
    assert cfg.adapter.retry.adapter_missing > 0
    assert cfg.adapter.retry.vehicle_off > 0
