from __future__ import annotations

import asyncio
import logging
import signal
import time
from pathlib import Path

from .adapter import Adapter, MockAdapter, OBDAdapter
from .config import Config, PidConfig
from .csvlog import CsvLogger
from .publisher import Publisher

log = logging.getLogger(__name__)


class Daemon:
    """Round-robins configured PIDs at their rate_hz, publishes to WebSocket,
    writes CSV. Handles adapter reconnect per retry config without crashing."""

    def __init__(
        self,
        config: Config,
        log_dir: Path | str,
        adapter: Adapter | None = None,
        publisher: Publisher | None = None,
    ):
        self.config = config
        self.adapter = adapter or OBDAdapter(config.adapter)
        self.publisher = publisher or Publisher()
        self.csv = CsvLogger(log_dir)
        self._stop = asyncio.Event()
        self._next_due: dict[str, float] = {}

    async def run(self) -> None:
        await self.publisher.serve()
        now = time.time()
        for pid in self.config.pids:
            self._next_due[pid.name] = now

        retry = self.config.adapter.retry
        backoff = retry.adapter_missing

        while not self._stop.is_set():
            if not self.adapter.is_ready():
                await self.adapter.ensure_connected()
                if not self.adapter.is_ready():
                    # Adapter not present or ECU silent. Back off and retry.
                    log.info("adapter not ready; sleeping %ds", backoff)
                    await self._sleep_or_stop(backoff)
                    backoff = min(retry.backoff_max, max(backoff, retry.vehicle_off))
                    continue

            backoff = retry.adapter_missing  # reset after a successful cycle

            pid, due_in = self._next_pid()
            if pid is None:
                await self._sleep_or_stop(1.0)
                continue
            if due_in > 0:
                await self._sleep_or_stop(min(due_in, 1.0))
                continue

            try:
                sample = await self.adapter.query(pid)
            except Exception:
                log.exception("query failed for %s; continuing", pid.name)
                sample = None

            self._next_due[pid.name] = time.time() + 1.0 / pid.rate_hz

            if sample is None or sample.value is None:
                continue

            try:
                await self.publisher.broadcast(sample)
            except Exception:
                log.exception("publish failed; continuing")
            try:
                self.csv.write(sample)
            except Exception:
                log.exception("csv write failed; continuing")

    def _next_pid(self) -> tuple[PidConfig | None, float]:
        best: PidConfig | None = None
        best_due = float("inf")
        for pid in self.config.pids:
            due = self._next_due.get(pid.name, 0.0)
            if due < best_due:
                best_due = due
                best = pid
        now = time.time()
        return best, max(0.0, best_due - now)

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def stop(self) -> None:
        log.info("stopping")
        self._stop.set()
        try:
            self.adapter.close()
        except Exception:
            log.exception("adapter close failed")
        try:
            self.csv.close()
        except Exception:
            log.exception("csv close failed")
        await self.publisher.close()


async def run_from_cli(config_path: Path, log_dir: Path, mock: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from .config import load as load_config

    config = load_config(config_path)
    adapter = MockAdapter(config.adapter) if mock else OBDAdapter(config.adapter)
    daemon = Daemon(config, log_dir, adapter=adapter)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(daemon.stop()))
        except NotImplementedError:
            # Windows dev boxes don't support add_signal_handler; tests run
            # on Linux in the Pi image so this is harmless.
            pass

    await daemon.run()
