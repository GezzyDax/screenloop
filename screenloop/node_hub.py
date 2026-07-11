import asyncio
import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger("screenloop.node_hub")


class NodeHub:
    """Registry of live node websocket connections, safe to call from worker threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sockets: dict[int, Any] = {}
        self._scan_results: dict[int, dict[str, Any]] = {}

    def attach(self, node_id: int, websocket: Any, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop
            self._sockets[node_id] = websocket

    def detach(self, node_id: int, websocket: Any) -> None:
        with self._lock:
            if self._sockets.get(node_id) is websocket:
                self._sockets.pop(node_id, None)

    def is_connected(self, node_id: int) -> bool:
        with self._lock:
            return node_id in self._sockets

    def connected_ids(self) -> list[int]:
        with self._lock:
            return list(self._sockets)

    def send(self, node_id: int, message: dict[str, Any]) -> bool:
        with self._lock:
            websocket = self._sockets.get(node_id)
            loop = self._loop
        if websocket is None or loop is None:
            return False
        future = asyncio.run_coroutine_threadsafe(websocket.send_text(json.dumps(message)), loop)
        try:
            future.result(timeout=5)
            return True
        except Exception as exc:
            logger.warning("send to node %s failed: %s", node_id, exc)
            return False

    def store_scan_result(self, node_id: int, devices: list[dict[str, Any]]) -> None:
        with self._lock:
            self._scan_results[node_id] = {"at": time.time(), "devices": devices}

    def scan_result_since(self, node_id: int, since: float) -> list[dict[str, Any]] | None:
        with self._lock:
            result = self._scan_results.get(node_id)
        if result and result["at"] >= since:
            return list(result["devices"])
        return None


hub = NodeHub()
