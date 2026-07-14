"""Configuration for the PC-side obstacle detection subsystem."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field


def _default_car_ip() -> str:
    # Measured real car IP on the 192.168.137.x hotspot. Override with CAR_IP.
    return os.environ.get("CAR_IP", "192.168.137.174").strip()


@dataclass
class ObstacleConfig:
    # ---- Car endpoints ----
    car_ip: str = field(default_factory=_default_car_ip)
    lidar_ws_port: int = 6602
    video_port: int = 6500
    control_port: int = 6000

    # ---- Distance thresholds (meters) ----
    warn_distance_m: float = 0.90
    danger_distance_m: float = 0.50

    # ---- Front sector (degrees, relative to robot forward) ----
    front_min_deg: float = -30.0
    front_max_deg: float = 30.0
    # The lidar angle (deg) that points to the robot's forward direction. The
    # lidar's 0 rad is NOT the robot front (mounted rotated ~+76 deg on this
    # car, measured with scripts/lidar_calib.py). The front sector is
    # [lidar_forward_deg+front_min_deg, +front_max_deg] with wrap-around.
    lidar_forward_deg: float = 76.0
    # Additive correction applied to lidar ranges; calibrate on the real car.
    lidar_offset_m: float = 0.0
    # Ignore lidar returns beyond this range (meters).
    max_range_m: float = 8.0

    # ---- Debounce (frames), from doc defaults ----
    warn_confirm_count: int = 2
    danger_confirm_count: int = 2
    clear_confirm_count: int = 5
    # A sensor whose last sample is older than this is treated as stale/UNKNOWN.
    # Raised to 8s because the car's sensor_relay pushes @SCAN in sparse bursts
    # (not a steady 10Hz); a tighter window makes lidar flap alive/stale.
    stale_after_sec: float = 8.0

    # ---- Vision (YOLO) ----
    vision_enabled: bool = True
    # Path/name of the YOLO weights. ultralytics auto-downloads from GitHub if
    # only a name is given; point this at a local .pt file to skip the download
    # (useful when GitHub is unreachable). Override with YOLO_MODEL.
    vision_model_path: str = field(
        default_factory=lambda: os.environ.get("YOLO_MODEL", "yolov8n.pt")
    )
    # COCO class names treated as obstacles. Empty => any detected class counts.
    vision_classes: list[str] = field(
        default_factory=lambda: [
            "person", "chair", "couch", "bench", "backpack", "suitcase",
            "bottle", "potted plant", "dog", "cat", "bicycle", "sports ball",
        ]
    )
    vision_conf: float = 0.35
    # Front-central band (ratio of frame width) a detection must overlap to count.
    vision_center_x_min: float = 0.30
    vision_center_x_max: float = 0.70
    # vision_only proximity proxy: bbox area as a fraction of the whole frame.
    vision_area_warn: float = 0.06
    vision_area_danger: float = 0.16

    # ---- Actuation (TCP 6000) ----
    beep_enabled: bool = True
    stop_enabled: bool = True
    # Master switch. True => DANGER really sends beep/STOP frames to the car on
    # startup (buzzer sounds). Set env ACTUATION=0 to fall back to dry-run.
    actuation_enabled: bool = field(
        default_factory=lambda: os.environ.get("ACTUATION", "1") not in ("0", "false", "False")
    )
    beep_duration_ms: int = 200
    beep_interval_sec: float = 1.0
    stop_interval_sec: float = 0.5

    def validate(self) -> None:
        if self.danger_distance_m <= 0:
            raise ValueError("danger_distance_m must be > 0")
        if self.warn_distance_m <= self.danger_distance_m:
            raise ValueError("warn_distance_m must be > danger_distance_m")
        if self.front_max_deg <= self.front_min_deg:
            raise ValueError("front_max_deg must be > front_min_deg")
        if self.stale_after_sec <= 0:
            raise ValueError("stale_after_sec must be > 0")
        for name in ("warn_confirm_count", "danger_confirm_count", "clear_confirm_count"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        if self.vision_area_danger <= self.vision_area_warn:
            raise ValueError("vision_area_danger must be > vision_area_warn")

    def to_dict(self) -> dict:
        return asdict(self)
