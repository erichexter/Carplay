from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path

from .adapter import Sample

log = logging.getLogger(__name__)


class CsvLogger:
    """Appends samples to {base_dir}/YYYY-MM-DD.csv, rolled at local midnight."""

    HEADER = ["ts", "pid", "display", "value", "unit"]

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._current_date: dt.date | None = None
        self._fh = None
        self._writer = None

    def _path_for(self, date: dt.date) -> Path:
        return self.base_dir / f"{date.isoformat()}.csv"

    def _rotate(self, date: dt.date) -> None:
        if self._fh is not None:
            self._fh.close()
        path = self._path_for(date)
        existed = path.exists() and path.stat().st_size > 0
        self._fh = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        if not existed:
            self._writer.writerow(self.HEADER)
        self._current_date = date
        log.info("csv rotated -> %s", path)

    def write(self, sample: Sample) -> None:
        today = dt.date.fromtimestamp(sample.ts)
        if self._current_date != today:
            self._rotate(today)
        assert self._writer is not None
        self._writer.writerow([
            f"{sample.ts:.3f}",
            sample.pid_name,
            sample.display,
            "" if sample.value is None else f"{sample.value:.3f}",
            sample.unit,
        ])
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            self._writer = None
