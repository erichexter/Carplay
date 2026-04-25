from __future__ import annotations

import json
import logging

import websockets

from .adapter import Sample

log = logging.getLogger(__name__)


class Publisher:
    """Local-only WebSocket publisher. Fan-out JSON samples to connected clients.
    Bind is 127.0.0.1 per PRD §10 (no inbound network surface)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._clients: set = set()
        self._server = None

    async def serve(self) -> None:
        self._server = await websockets.serve(self._handler, self.host, self.port)
        log.info("publisher listening on ws://%s:%d", self.host, self.port)

    @property
    def bound_port(self) -> int:
        # Useful in tests when port=0 is passed.
        if self._server is None:
            return self.port
        for sock in self._server.sockets:
            return sock.getsockname()[1]
        return self.port

    async def _handler(self, ws):
        self._clients.add(ws)
        log.info("client connected (%d total)", len(self._clients))
        try:
            await ws.wait_closed()
        finally:
            self._clients.discard(ws)
            log.info("client disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, sample: Sample) -> None:
        if not self._clients:
            return
        payload = json.dumps({
            "pid": sample.pid_name,
            "display": sample.display,
            "value": sample.value,
            "unit": sample.unit,
            "ts": sample.ts,
        })
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send(payload)
            except websockets.ConnectionClosed:
                dead.append(ws)
            except Exception:
                log.exception("broadcast to a client failed")
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
