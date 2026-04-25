from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .daemon import run_from_cli


def _cli() -> None:
    p = argparse.ArgumentParser(prog="truckdash-obd2")
    p.add_argument(
        "--config",
        type=Path,
        default=Path("/opt/truckdash/config/obd2.toml"),
        help="path to obd2.toml",
    )
    p.add_argument(
        "--log-dir",
        type=Path,
        default=Path("/var/log/truckdash/obd2"),
        help="directory for CSV samples",
    )
    p.add_argument(
        "--mock",
        action="store_true",
        help="use the synthetic adapter (no hardware required)",
    )
    args = p.parse_args()
    asyncio.run(run_from_cli(args.config, args.log_dir, mock=args.mock))


if __name__ == "__main__":
    _cli()
