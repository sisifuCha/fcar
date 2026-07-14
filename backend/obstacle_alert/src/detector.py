#!/usr/bin/env python3
"""Obstacle status state machine for lidar samples."""

import threading
from typing import Optional

from .state import ObstacleConfig, ObstacleStatus, classify_distance, message_for, now_ts


class ObstacleDetector:
    def __init__(
        self,
        config: ObstacleConfig,
        source: str = "lidar",
        distance_key: str = "front_min_m",
        none_is_clear: bool = True,
    ):
        self.config = config
        self.source = source
        self.distance_key = distance_key
        self.none_is_clear = none_is_clear
        self._lock = threading.Lock()
        self._status = ObstacleStatus(timestamp=now_ts())
        self._last_sample: Optional[dict] = None
        self._warn_count = 0
        self._danger_count = 0
        self._clear_count = 0

    def update_sample(self, sample: dict) -> ObstacleStatus:
        with self._lock:
            self._last_sample = sample
            distance = sample.get(self.distance_key)
            if distance is None and not self.none_is_clear:
                raw_level = "UNKNOWN"
            else:
                raw_level = classify_distance(distance, self.config)

            if raw_level == "DANGER":
                self._danger_count += 1
                self._warn_count = 0
                self._clear_count = 0
            elif raw_level == "WARN":
                self._warn_count += 1
                self._danger_count = 0
                self._clear_count = 0
            elif raw_level == "CLEAR":
                self._clear_count += 1
                self._warn_count = 0
                self._danger_count = 0
            else:
                self._warn_count = 0
                self._danger_count = 0
                self._clear_count = 0

            current_level = self._status.level
            if raw_level == "DANGER":
                if self._danger_count >= self.config.danger_confirm_count:
                    current_level = "DANGER"
            elif raw_level == "WARN":
                if current_level != "DANGER" and self._warn_count >= self.config.warn_confirm_count:
                    current_level = "WARN"
            elif raw_level == "CLEAR":
                if current_level in ("WARN", "DANGER"):
                    if self._clear_count >= self.config.clear_confirm_count:
                        current_level = "CLEAR"
                else:
                    current_level = "CLEAR"
            else:
                current_level = "UNKNOWN"

            timestamp = sample.get("timestamp") or now_ts()
            display_distance = distance
            if current_level in ("WARN", "DANGER") and raw_level == "CLEAR":
                display_distance = self._status.distance_m
            self._status = ObstacleStatus(
                level=current_level,
                raw_level=raw_level,
                has_obstacle=current_level in ("WARN", "DANGER"),
                distance_m=display_distance,
                source=self.source,
                message=message_for(current_level, display_distance),
                timestamp=timestamp,
                stale=False,
                scan_age_sec=max(0.0, now_ts() - timestamp),
                range_count=int(sample.get("range_count") or 0),
                docker_container=sample.get("docker_container"),
                error=None,
            )
            return self._status

    def set_error(self, error: str) -> None:
        with self._lock:
            self._status.error = error
            if self._status.level == "UNKNOWN":
                self._status.message = error

    def get_status(self) -> ObstacleStatus:
        with self._lock:
            status = self._status
            age = now_ts() - status.timestamp if status.timestamp else None
            if age is not None and age > self.config.stale_after_sec:
                return ObstacleStatus(
                    level="UNKNOWN",
                    raw_level=status.raw_level,
                    has_obstacle=False,
                    distance_m=status.distance_m,
                    source=self.source,
                    message=f"{self.source} 数据超时，障碍物检测暂不可用",
                    timestamp=status.timestamp,
                    stale=True,
                    scan_age_sec=age,
                    range_count=status.range_count,
                    docker_container=status.docker_container,
                    error=status.error,
                )
            return status

    def update_config(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
            self.config.validate()
            self._warn_count = 0
            self._danger_count = 0
            self._clear_count = 0
