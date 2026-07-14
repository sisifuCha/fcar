"""Fusion + debounced state machine for obstacle detection.

Ported from obstacle_alert/src/{state,detector}.py and adapted to the PC-side
fusion policy: lidar distance is the authority; vision confirms whether a real
obstacle is present and supplies a class label. When lidar is unavailable, a
vision-only proximity proxy (bbox area ratio) drives the decision.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Optional

from .config import ObstacleConfig

LEVEL_ORDER = {"UNKNOWN": -1, "CLEAR": 0, "WARN": 1, "DANGER": 2}


def now_ts() -> float:
    return time.time()


@dataclass
class FusedStatus:
    level: str = "UNKNOWN"
    raw_level: str = "UNKNOWN"
    has_obstacle: bool = False
    distance_m: Optional[float] = None
    source: str = "none"  # lidar | fusion | vision_only | none
    label: Optional[str] = None
    message: str = "障碍物检测未就绪"
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _message_for(level: str, distance_m: Optional[float], label: Optional[str], source: str) -> str:
    who = f"：{label}" if label else ""
    if source == "vision_only":
        if level == "DANGER":
            return f"前方检测到障碍物{who}（视觉，无雷达测距），已触发停车/蜂鸣保护"
        if level == "WARN":
            return f"前方出现障碍物{who}（视觉，无雷达测距），请注意"
        if level == "CLEAR":
            return "前方视野内未检测到障碍物（视觉，无雷达测距）"
        return "等待视频/雷达数据"
    dist = "未知" if distance_m is None else f"{distance_m:.2f}m"
    if level == "DANGER":
        return f"前方 {dist} 有障碍物{who}，已触发停车/蜂鸣保护"
    if level == "WARN":
        return f"前方 {dist} 检测到障碍物{who}，请注意"
    if level == "CLEAR":
        return f"前方 {dist} 内未达到报警阈值"
    return "障碍物检测未就绪"


class FusionDetector:
    """Consumes the latest lidar + vision samples and produces a debounced level."""

    def __init__(self, config: ObstacleConfig):
        self.config = config
        self._lock = threading.Lock()
        self._status = FusedStatus(timestamp=now_ts())
        self._warn_count = 0
        self._danger_count = 0
        self._clear_count = 0

    def _classify(self, lidar: Optional[dict], vision: Optional[dict]) -> tuple[str, Optional[float], str, Optional[str]]:
        """Return (raw_level, distance_m, source, label) before debouncing."""
        cfg = self.config
        lidar_fresh = bool(lidar) and (now_ts() - lidar.get("timestamp", 0)) <= cfg.stale_after_sec
        vision_fresh = bool(vision) and (now_ts() - vision.get("timestamp", 0)) <= cfg.stale_after_sec
        # Vision only participates in the decision when the YOLO model is
        # actually running. In passthrough mode (no model, e.g. torch not yet
        # installed) the frames still stream for display but must NOT veto the
        # lidar — otherwise present=False would downgrade a real DANGER.
        vis_ok = bool(vision_fresh and vision.get("model", True))

        vis_present = bool(vis_ok and vision.get("present"))
        vis_label = vision.get("label") if vis_ok else None
        vis_area = float(vision.get("area_ratio", 0.0)) if vis_ok else 0.0

        front = lidar.get("front_min_m") if lidar_fresh else None

        # ---- Lidar authority (distance available) ----
        if lidar_fresh and front is not None:
            source = "fusion" if vis_ok else "lidar"
            if front < cfg.danger_distance_m:
                # Distance is dangerous; require vision confirmation only when
                # vision is available. If vision is down, trust the lidar.
                if (not vis_ok) or vis_present:
                    return "DANGER", front, source, vis_label
                return "WARN", front, source, vis_label
            if front < cfg.warn_distance_m:
                return "WARN", front, source, vis_label
            return "CLEAR", front, source, vis_label

        # ---- Lidar fresh but no return in front sector => nothing near => CLEAR ----
        if lidar_fresh and front is None:
            return "CLEAR", None, ("fusion" if vis_ok else "lidar"), vis_label

        # ---- Vision-only fallback (lidar down, model running) ----
        if vis_ok:
            if vis_present and vis_area >= cfg.vision_area_danger:
                return "DANGER", None, "vision_only", vis_label
            if vis_present and vis_area >= cfg.vision_area_warn:
                return "WARN", None, "vision_only", vis_label
            return "CLEAR", None, "vision_only", vis_label

        # ---- Nothing fresh ----
        return "UNKNOWN", None, "none", None

    def update(self, lidar: Optional[dict], vision: Optional[dict]) -> FusedStatus:
        with self._lock:
            cfg = self.config
            raw_level, distance, source, label = self._classify(lidar, vision)

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
                self._warn_count = self._danger_count = self._clear_count = 0

            current = self._status.level
            if raw_level == "DANGER":
                if self._danger_count >= cfg.danger_confirm_count:
                    current = "DANGER"
            elif raw_level == "WARN":
                if current != "DANGER" and self._warn_count >= cfg.warn_confirm_count:
                    current = "WARN"
            elif raw_level == "CLEAR":
                if current in ("WARN", "DANGER"):
                    if self._clear_count >= cfg.clear_confirm_count:
                        current = "CLEAR"
                else:
                    current = "CLEAR"
            else:
                current = "UNKNOWN"

            # Hold the last known distance/label while latched in an alarm state
            # but the current raw sample cleared (mirrors reference behavior).
            display_distance = distance
            display_label = label
            if current in ("WARN", "DANGER") and raw_level == "CLEAR":
                display_distance = self._status.distance_m
                display_label = self._status.label or label

            self._status = FusedStatus(
                level=current,
                raw_level=raw_level,
                has_obstacle=current in ("WARN", "DANGER"),
                distance_m=display_distance,
                source=source,
                label=display_label,
                message=_message_for(current, display_distance, display_label, source),
                timestamp=now_ts(),
            )
            return self._status

    def get_status(self) -> FusedStatus:
        with self._lock:
            return self._status

    def reset_counts(self) -> None:
        with self._lock:
            self._warn_count = self._danger_count = self._clear_count = 0
