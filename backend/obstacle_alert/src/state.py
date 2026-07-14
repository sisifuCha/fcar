#!/usr/bin/env python3
"""Shared state and thresholds for the first lidar obstacle alarm service."""

from dataclasses import asdict, dataclass
from typing import Optional
import time


LEVEL_ORDER = {
    "UNKNOWN": -1,
    "CLEAR": 0,
    "WARN": 1,
    "DANGER": 2,
}


@dataclass
class ObstacleConfig:
    warn_distance_m: float = 0.90
    danger_distance_m: float = 0.50
    front_min_deg: float = -30.0
    front_max_deg: float = 30.0
    max_range_m: float = 8.0
    stale_after_sec: float = 1.5
    warn_confirm_count: int = 2
    danger_confirm_count: int = 2
    clear_confirm_count: int = 5
    beep_enabled: bool = True
    stop_enabled: bool = True
    beep_duration_ms: int = 80
    beep_interval_sec: float = 1.0
    stop_interval_sec: float = 0.5

    def validate(self) -> None:
        if self.danger_distance_m <= 0:
            raise ValueError("danger_distance_m must be > 0")
        if self.warn_distance_m <= self.danger_distance_m:
            raise ValueError("warn_distance_m must be > danger_distance_m")
        if self.stale_after_sec <= 0:
            raise ValueError("stale_after_sec must be > 0")
        if self.warn_confirm_count < 1:
            raise ValueError("warn_confirm_count must be >= 1")
        if self.danger_confirm_count < 1:
            raise ValueError("danger_confirm_count must be >= 1")
        if self.clear_confirm_count < 1:
            raise ValueError("clear_confirm_count must be >= 1")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ObstacleStatus:
    level: str = "UNKNOWN"
    raw_level: str = "UNKNOWN"
    has_obstacle: bool = False
    distance_m: Optional[float] = None
    source: str = "lidar"
    message: str = "雷达检测服务未就绪"
    timestamp: float = 0.0
    stale: bool = True
    scan_age_sec: Optional[float] = None
    range_count: int = 0
    docker_container: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self, config: ObstacleConfig, actions: dict) -> dict:
        data = asdict(self)
        data["config"] = config.to_dict()
        data["actions"] = actions
        return data


def classify_distance(distance_m: Optional[float], config: ObstacleConfig) -> str:
    # A live LaserScan with no valid point in the front sector means there is
    # no obstacle within max_range_m, so treat it as CLEAR. UNKNOWN is reserved
    # for service startup, stale data, or stream errors.
    if distance_m is None:
        return "CLEAR"
    if distance_m < config.danger_distance_m:
        return "DANGER"
    if distance_m < config.warn_distance_m:
        return "WARN"
    return "CLEAR"


def message_for(level: str, distance_m: Optional[float]) -> str:
    if level == "DANGER":
        if distance_m is None:
            return "前方检测到危险障碍物，已触发报警/停车保护"
        return f"前方 {distance_m:.2f}m 有障碍物，已触发报警/停车保护"
    if level == "WARN":
        if distance_m is None:
            return "前方检测到障碍物，请注意"
        return f"前方 {distance_m:.2f}m 检测到障碍物，请注意"
    if level == "CLEAR":
        if distance_m is None:
            return "前方未检测到危险障碍物"
        return f"前方 {distance_m:.2f}m 内未达到报警阈值"
    return "雷达检测服务未就绪"


def now_ts() -> float:
    return time.time()
