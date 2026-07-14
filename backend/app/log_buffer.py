"""Thread-safe ring buffer for capturing log records.

Follows the thread-safety pattern of app/store.py (Lock + snapshotting).
The ring buffer automatically drops the oldest entry when full.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any


class RingBufferHandler(logging.Handler):
    """Keeps the last *capacity* log records in memory. Thread-safe."""

    def __init__(self, capacity: int = 200) -> None:
        super().__init__()
        self.capacity = capacity
        self._buffer: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        """Store a serializable dict (not the LogRecord itself) to avoid
        holding references to tracebacks, exc_info, etc."""
        entry = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        with self._lock:
            self._buffer.append(entry)

    def list_records(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return most recent records as serializable dicts, newest first."""
        with self._lock:
            items = list(self._buffer)  # snapshot under lock
        return [dict(r) for r in reversed(items)][:limit]


_handler: RingBufferHandler | None = None


def create_handler(capacity: int = 200) -> RingBufferHandler:
    """Called once from run.py to install the handler."""
    global _handler
    _handler = RingBufferHandler(capacity)
    return _handler


def get_handler() -> RingBufferHandler | None:
    return _handler


def list_logs(limit: int = 200) -> list[dict[str, Any]]:
    """Convenience used by routes.py (safe when handler not yet installed)."""
    if _handler is None:
        return []
    return _handler.list_records(limit=limit)
