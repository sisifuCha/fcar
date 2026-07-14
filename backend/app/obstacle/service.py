"""ObstacleService: orchestrates lidar + vision + control and runs fusion.

Owns the three background workers, a fusion loop that ticks the debounced state
machine, and triggers STOP + beep on DANGER (rate-limited, dry-run by default).
Exposes thread-safe status/health/config for the HTTP layer. Mirrors the shape
of obstacle_alert/obstacle_app.py's ObstacleAlarmService.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from .config import ObstacleConfig
from .control import ControlClient
from .detector import FusionDetector
from .lidar_ws import LidarWSClient
from .vision_yolo import VisionWorker


class ObstacleService:
    def __init__(self, config: Optional[ObstacleConfig] = None):
        self.config = config or ObstacleConfig()
        self.config.validate()
        self.detector = FusionDetector(self.config)
        self.lidar = LidarWSClient(self.config)
        self.vision = VisionWorker(self.config)
        self.control = ControlClient(self.config)

        self._stop = threading.Event()
        self._fusion_thread: Optional[threading.Thread] = None
        self._tick_hz = 10.0
        self._last_console_level: Optional[str] = None
        self._last_console_ts = 0.0

    # ---- lifecycle ----
    def start(self) -> None:
        self.lidar.start()
        self.vision.start()
        self._stop.clear()
        self._fusion_thread = threading.Thread(target=self._fusion_loop, name="fusion", daemon=True)
        self._fusion_thread.start()
        print(
            f"[OBSTACLE] service started car_ip={self.config.car_ip} "
            f"actuation_enabled={self.config.actuation_enabled}",
            flush=True,
        )

    def stop(self) -> None:
        self._stop.set()
        self.lidar.stop()
        self.vision.stop()

    def _fusion_loop(self) -> None:
        period = 1.0 / self._tick_hz
        while not self._stop.is_set():
            lidar = self.lidar.get_latest()
            vision = self.vision.get_latest()
            status = self.detector.update(lidar, vision)
            self._maybe_console(status)
            if status.level == "DANGER":
                self.control.trigger_stop()
                self.control.trigger_beep()
            time.sleep(period)

    def _maybe_console(self, status) -> None:
        now = time.time()
        if status.level in ("WARN", "DANGER"):
            changed = status.level != self._last_console_level
            if changed or (now - self._last_console_ts) >= 1.0:
                dist = "unknown" if status.distance_m is None else f"{status.distance_m:.2f}m"
                print(
                    f"[OBSTACLE] {status.level} source={status.source} "
                    f"dist={dist} label={status.label} :: {status.message}",
                    flush=True,
                )
                self._last_console_ts = now
        elif self._last_console_level in ("WARN", "DANGER"):
            print(f"[OBSTACLE] CLEAR source={status.source}", flush=True)
        self._last_console_level = status.level

    # ---- payloads ----
    def status_payload(self) -> dict:
        status = self.detector.get_status()
        payload = status.to_dict()
        payload["fusion_policy"] = "lidar_authority_vision_confirm"
        payload["config"] = self.config.to_dict()
        payload["control"] = self.control.state_dict()
        payload["sensors"] = {
            "lidar": self.lidar.health(),
            "vision": self.vision.health(),
        }
        return payload

    def health_payload(self) -> dict:
        status = self.detector.get_status()
        lidar_h = self.lidar.health()
        vision_h = self.vision.health()
        ok = status.level != "UNKNOWN" and (lidar_h["alive"] or vision_h["alive"])
        return {
            "ok": ok,
            "service": "obstacle",
            "fusion_policy": "lidar_authority_vision_confirm",
            "level": status.level,
            "source": status.source,
            "lidar_alive": lidar_h["alive"],
            "vision_alive": vision_h["alive"],
            "lidar_connected": lidar_h["connected"],
            "vision_connected": vision_h["connected"],
            "actuation_enabled": self.config.actuation_enabled,
            "car_ip": self.config.car_ip,
            "last_lidar_error": lidar_h["last_error"],
            "last_vision_error": vision_h["last_error"],
        }

    def update_config(self, payload: dict) -> dict:
        allowed = {
            "car_ip": str,
            "warn_distance_m": float,
            "danger_distance_m": float,
            "front_min_deg": float,
            "front_max_deg": float,
            "lidar_offset_m": float,
            "max_range_m": float,
            "warn_confirm_count": int,
            "danger_confirm_count": int,
            "clear_confirm_count": int,
            "stale_after_sec": float,
            "vision_enabled": bool,
            "vision_conf": float,
            "vision_center_x_min": float,
            "vision_center_x_max": float,
            "vision_area_warn": float,
            "vision_area_danger": float,
            "beep_enabled": bool,
            "stop_enabled": bool,
            "actuation_enabled": bool,
            "beep_duration_ms": int,
            "beep_interval_sec": float,
            "stop_interval_sec": float,
        }
        updates: dict = {}
        for key, caster in allowed.items():
            if key not in payload:
                continue
            value = payload[key]
            if caster is bool:
                if not isinstance(value, bool):
                    raise ValueError(f"{key} must be a boolean")
                updates[key] = value
            else:
                updates[key] = caster(value)
        if "vision_classes" in payload:
            classes = payload["vision_classes"]
            if not isinstance(classes, list) or not all(isinstance(c, str) for c in classes):
                raise ValueError("vision_classes must be a list of strings")
            updates["vision_classes"] = classes

        # Apply then validate; roll back on failure.
        snapshot = self.config.to_dict()
        for key, value in updates.items():
            setattr(self.config, key, value)
        try:
            self.config.validate()
        except ValueError:
            for key, value in snapshot.items():
                setattr(self.config, key, value)
            raise
        self.detector.reset_counts()
        return self.status_payload()
