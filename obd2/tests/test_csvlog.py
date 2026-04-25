import datetime as dt

from truckdash_obd2.adapter import Sample
from truckdash_obd2.csvlog import CsvLogger


def _sample(ts: float, name: str = "rpm", value: float = 800.0) -> Sample:
    return Sample(pid_name=name, display=name.upper(), value=value, unit="rpm", ts=ts)


def test_writes_header_and_rows(tmp_path):
    logger = CsvLogger(tmp_path)
    t = dt.datetime(2026, 4, 21, 12, 0).timestamp()
    logger.write(_sample(t))
    logger.write(_sample(t + 1, value=810))
    logger.close()

    files = list(tmp_path.glob("*.csv"))
    assert len(files) == 1
    lines = files[0].read_text().splitlines()
    assert lines[0] == "ts,pid,display,value,unit"
    assert len(lines) == 3  # header + 2 rows


def test_rotates_across_midnight(tmp_path):
    logger = CsvLogger(tmp_path)
    day1 = dt.datetime(2026, 4, 21, 23, 59, 59).timestamp()
    day2 = dt.datetime(2026, 4, 22, 0, 0, 1).timestamp()
    logger.write(_sample(day1))
    logger.write(_sample(day2))
    logger.close()

    files = sorted(tmp_path.glob("*.csv"))
    assert [f.name for f in files] == ["2026-04-21.csv", "2026-04-22.csv"]


def test_reopen_preserves_existing_rows(tmp_path):
    t = dt.datetime(2026, 4, 21, 12, 0).timestamp()

    logger = CsvLogger(tmp_path)
    logger.write(_sample(t))
    logger.close()

    # Simulate daemon restart on the same day — must not duplicate header.
    logger2 = CsvLogger(tmp_path)
    logger2.write(_sample(t + 1))
    logger2.close()

    files = list(tmp_path.glob("*.csv"))
    assert len(files) == 1
    lines = files[0].read_text().splitlines()
    assert lines.count("ts,pid,display,value,unit") == 1
    assert len(lines) == 3
