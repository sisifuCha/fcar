"""Lidar WebSocket client (car port 6602).

Background thread that connects to ws://<car_ip>:6602, parses @SCAN{json}#
frames, and computes the nearest valid range in the configurable front sector.
Auto-reconnects with backoff so the car relay can come online at any time.

Message format (doc/07 §3):
    @SCAN{"ranges":[...],"angle_min":-3.14,"angle_increment":0.017,
          "range_min":0.15,"range_max":12.0,"t":...}#
    @ODOM{...}#   (ignored for v1)
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Callable, Optional

try:
    import websocket  # from websocket-client
except Exception:  # pragma: no cover - dependency missing until env is built
    websocket = None

from .config import ObstacleConfig


def compute_front_min(scan: dict, config: ObstacleConfig) -> Optional[float]:
    """Nearest valid range within [front_min_deg, front_max_deg], offset-corrected.

    Returns None when no valid point falls in the front sector (i.e. nothing
    near) so the state machine can treat it as CLEAR rather than DANGER.
    """
    ranges = scan.get("ranges") or []
    if not ranges:
        return None
    angle = float(scan.get("angle_min", 0.0))
    inc = float(scan.get("angle_increment", 0.0))
    range_min = float(scan.get("range_min", 0.0))
    range_max = min(float(scan.get("range_max", config.max_range_m)), config.max_range_m)
    lo = math.radians(config.front_min_deg)
    hi = math.radians(config.front_max_deg)

    best: Optional[float] = None
    for r in ranges:
        a = angle
        angle += inc
        if r is None:
            continue
        try:
            rv = float(r)
        except (TypeError, ValueError):
            continue
        # Drop invalid points: 0 / NaN / inf / out of range.
        if not math.isfinite(rv) or rv <= 0:
            continue
        if not (range_min < rv < range_max):
            continue
        if not (lo <= a <= hi):
            continue
        if best is None or rv < best:
            best = rv

    if best is None:
        return None
    corrected = best + config.lidar_offset_m
    return max(0.0, corrected)


class LidarWSClient:
    """Connects to 6602, keeps the latest front-distance sample. Thread-safe."""

    def __init__(self, config: ObstacleConfig, on_sample: Optional[Callable[[dict], None]] = None):
        self.config = config
        self._on_sample = on_sample
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ws: Optional["websocket.WebSocket"] = None
        self._latest: Optional[dict] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._last_odom: Optional[dict] = None

    @property
    def url(self) -> str:
        return f"ws://{self.config.car_ip}:{self.config.lidar_ws_port}"

    def start(self) -> None:
        if websocket is None:
            self._last_error = "websocket-client not installed"
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lidar-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._ws = websocket.create_connection(self.url, timeout=5)
                with self._lock:
                    self._connected = True
                    self._last_error = None
                backoff = 1.0
                while not self._stop.is_set():
                    msg = self._ws.recv()
                    if not msg:
                        continue
                    if isinstance(msg, bytes):
                        msg = msg.decode("utf-8", "ignore")
                    self._handle(msg)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._connected = False
                    self._last_error = repr(exc)
            finally:
                try:
                    if self._ws is not None:
                        self._ws.close()
                except Exception:
                    pass
                self._ws = None
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    def _handle(self, msg: str) -> None:
        msg = msg.strip()
        if not msg.endswith("#"):
            return
        if msg.startswith("@SCAN"):
            try:
                scan = json.loads(msg[len("@SCAN"):-1])
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._last_error = f"scan parse: {exc!r}"
                return
            front = compute_front_min(scan, self.config)
            sample = {
                "front_min_m": front,
                "range_count": len(scan.get("ranges") or []),
                "timestamp": time.time(),
                "scan_t": scan.get("t"),
            }
            with self._lock:
                self._latest = sample
            if self._on_sample:
                self._on_sample(sample)
        elif msg.startswith("@ODOM"):
            try:
                with self._lock:
                    self._last_odom = json.loads(msg[len("@ODOM"):-1])
            except Exception:
                pass

    def get_latest(self) -> Optional[dict]:
        with self._lock:
            return dict(self._latest) if self._latest else None

    def health(self) -> dict:
        with self._lock:
            latest = self._latest
            age = (time.time() - latest["timestamp"]) if latest else None
            alive = bool(
                self._connected
                and latest is not None
                and age is not None
                and age <= self.config.stale_after_sec
            )
            return {
                "connected": self._connected,
                "alive": alive,
                "url": self.url,
                "last_error": self._last_error,
                "age_sec": age,
                "front_min_m": latest["front_min_m"] if latest else None,
                "odom": self._last_odom,
            }
