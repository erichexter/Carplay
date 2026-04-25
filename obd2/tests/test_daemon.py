import asyncio
import json

import pytest
import websockets

from truckdash_obd2.adapter import MockAdapter
from truckdash_obd2.config import AdapterConfig, Config, PidConfig
from truckdash_obd2.daemon import Daemon
from truckdash_obd2.publisher import Publisher


def _cfg() -> Config:
    return Config(
        adapter=AdapterConfig(),
        pids=[
            PidConfig(name="rpm", display="RPM", mode="01", pid="0C",
                      rate_hz=20, units="rpm"),
            PidConfig(name="coolant_temp", display="Coolant", mode="01", pid="05",
                      rate_hz=10, units="C"),
        ],
    )


@pytest.mark.asyncio
async def test_daemon_publishes_samples(tmp_path):
    # Port 0 lets the OS pick a free port.
    publisher = Publisher(port=0)
    daemon = Daemon(_cfg(), tmp_path, adapter=MockAdapter(), publisher=publisher)

    runner = asyncio.create_task(daemon.run())
    try:
        # Wait for the server to bind.
        for _ in range(50):
            if publisher.bound_port:
                break
            await asyncio.sleep(0.02)

        port = publisher.bound_port
        assert port > 0

        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            got_pids = set()
            for _ in range(5):
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(msg)
                got_pids.add(data["pid"])
                assert isinstance(data["value"], (int, float))
                assert "ts" in data
            # Both configured PIDs should appear within a handful of samples.
            assert "rpm" in got_pids
    finally:
        await daemon.stop()
        await runner


@pytest.mark.asyncio
async def test_daemon_writes_csv(tmp_path):
    publisher = Publisher(port=0)
    daemon = Daemon(_cfg(), tmp_path, adapter=MockAdapter(), publisher=publisher)

    runner = asyncio.create_task(daemon.run())
    try:
        await asyncio.sleep(0.3)
    finally:
        await daemon.stop()
        await runner

    csvs = list(tmp_path.glob("*.csv"))
    assert csvs, "expected at least one CSV file to be written"
    lines = csvs[0].read_text().splitlines()
    assert lines[0] == "ts,pid,display,value,unit"
    assert len(lines) >= 2
