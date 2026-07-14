"""PC-side obstacle detection subsystem.

Connects to the car over the network (no car-side code changes):
  - 6602 WebSocket  -> lidar @SCAN distance (authority when available)
  - 6500 MJPEG      -> RGB video, YOLO confirmation + class label
  - 6000 TCP        -> STOP / beep control frames (rate-limited, dry-run by default)

Fuses lidar distance with vision confirmation, applies a debounced state
machine (CLEAR/WARN/DANGER), and gracefully degrades to vision-only when the
lidar relay (6602) is down, or lidar-only when video is unavailable.
"""

from .config import ObstacleConfig
from .service import ObstacleService

__all__ = ["ObstacleConfig", "ObstacleService"]
