"""Trajectory tracker: polls car IMU, integrates velocity to displacement.

Polls http://{car_ip}:5001/status at 10 Hz, extracts vx/vy/yaw from the
sensors dict, rotates into world frame, and integrates via trapezoidal rule.
Thread-safe — follows the pattern of app/obstacle/service.py.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any, Optional

import requests


class TrajectoryTracker:
    """Background thread polls the car's /status endpoint, accumulates position."""

    def __init__(self, car_ip: str = "192.168.137.174", car_port: int = 5001) -> None:
        self._car_url = f"http://{car_ip}:{car_port}/status"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Integration state
        self._x = 0.0
        self._y = 0.0
        self._prev_vx: Optional[float] = None
        self._prev_vy: Optional[float] = None
        self._prev_t: Optional[float] = None
        self._total_distance = 0.0

        # Path history — store every Nth sample to limit size
        self._points: deque[dict[str, Any]] = deque(maxlen=2000)
        self._sample_decimation = 5  # store 1 out of every 5 samples
        self._tick_count = 0

        # Health
        self._last_error: Optional[str] = None
        self._last_sample_time: Optional[float] = None
        self._sample_count = 0

    # ---- lifecycle ----
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="trajectory", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        """Main loop: poll the car at 10 Hz."""
        interval = 0.1
        while not self._stop.is_set():
            loop_start = time.time()
            try:
                resp = requests.get(self._car_url, timeout=1.0)
                resp.raise_for_status()
                data = resp.json()
                self._process(data)
                self._last_error = None
            except Exception as exc:
                self._last_error = repr(exc)
            elapsed = time.time() - loop_start
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def _process(self, data: dict) -> None:
        sensors = data.get("sensors", {})
        vx = float(sensors.get("vx", 0.0))
        vy = float(sensors.get("vy", 0.0))
        yaw = float(sensors.get("yaw", 0.0))
        now = time.time()

        with self._lock:
            self._last_sample_time = now
            self._sample_count += 1

            if self._prev_t is not None:
                dt = now - self._prev_t
                if dt > 0 and dt < 2.0:  # guard against huge gaps / first sample
                    # Trapezoidal integration: average of previous and current velocity
                    vx_avg = (self._prev_vx + vx) / 2.0  # type: ignore[operator]
                    vy_avg = (self._prev_vy + vy) / 2.0  # type: ignore[operator]

                    # Rotate body-frame velocity to world frame via yaw
                    cos_y = math.cos(yaw)
                    sin_y = math.sin(yaw)
                    vx_w = vx_avg * cos_y - vy_avg * sin_y
                    vy_w = vx_avg * sin_y + vy_avg * cos_y

                    dx = vx_w * dt
                    dy = vy_w * dt
                    self._x += dx
                    self._y += dy
                    self._total_distance += math.hypot(dx, dy)

            self._prev_vx = vx
            self._prev_vy = vy
            self._prev_t = now

            # Store decimated path point
            self._tick_count += 1
            if self._tick_count % self._sample_decimation == 0:
                self._points.append({
                    "x": round(self._x, 3),
                    "y": round(self._y, 3),
                    "t": round(now, 3),
                })

    # ---- snapshot ----
    def snapshot(self, limit: int = 500) -> dict[str, Any]:
        """Return thread-safe snapshot for the HTTP layer."""
        with self._lock:
            items = list(self._points)
            # Return most recent points up to limit
            if len(items) > limit:
                items = items[-limit:]
            return {
                "points": [dict(p) for p in items],
                "current_x": round(self._x, 3),
                "current_y": round(self._y, 3),
                "total_distance": round(self._total_distance, 3),
                "sample_count": self._sample_count,
                "last_error": self._last_error,
                "last_sample_time": self._last_sample_time,
            }


# Module-level singleton (follows the pattern from app/__init__.py)
_tracker: Optional[TrajectoryTracker] = None


def start_tracker(car_ip: str = "192.168.137.174", car_port: int = 5001) -> TrajectoryTracker:
    """Start the trajectory tracker. Called once from run.py."""
    global _tracker
    if _tracker is not None:
        _tracker.stop()
    _tracker = TrajectoryTracker(car_ip=car_ip, car_port=car_port)
    _tracker.start()
    return _tracker


def get_tracker() -> Optional[TrajectoryTracker]:
    return _tracker
