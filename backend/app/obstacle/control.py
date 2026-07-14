"""PC-side control client: send STOP / beep frames to the car over TCP 6000.

Frame format and checksum come from doc/07 §4-5 and doc/08 §3-6:

    $ + CC(car_type) + TT(cmd) + LL(len) + PAYLOAD + XX(checksum) + #

    length   = len(payload) * 2 + 2
    checksum = (0x9E + sum([car_type, cmd, length] + payload)) & 0xFF

Rate-limiting mirrors obstacle_alert/src/hardware.py (last_stop_ts / last_beep_ts
+ min interval), but the actuator is TCP frames instead of a serial Rosmaster.
When actuation_enabled is False the client only records would-be sends.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Optional

from .config import ObstacleConfig

CAR_TYPE = 0x01
CMD_MOTION = 0x10
CMD_BEEP = 0x13


def build_frame(car_type: int, cmd: int, payload: list[int]) -> str:
    length = len(payload) * 2 + 2
    body = [car_type, cmd, length] + payload
    checksum = (0x9E + sum(body)) & 0xFF
    return "$" + "".join(f"{b:02X}" for b in body) + f"{checksum:02X}#"


def stop_frame() -> str:
    # build_frame(0x01, 0x10, [0x00, 0x00]) -> $0110060000B5#
    return build_frame(CAR_TYPE, CMD_MOTION, [0x00, 0x00])


def beep_frame(duration_ms: int) -> str:
    """Map a duration in ms to a beep frame (doc/08 §6).

    duration_ms <= 0 -> off; == 1 -> continuous; else delay = round(ms/10).
    """
    if duration_ms <= 0:
        return build_frame(CAR_TYPE, CMD_BEEP, [0x00, 0x00])
    if duration_ms == 1:
        return build_frame(CAR_TYPE, CMD_BEEP, [0x01, 0xFF])  # continuous
    delay = max(1, min(254, round(duration_ms / 10)))
    return build_frame(CAR_TYPE, CMD_BEEP, [0x01, delay])


class ControlClient:
    """Rate-limited TCP 6000 actuator. Thread-safe."""

    def __init__(self, config: ObstacleConfig):
        self.config = config
        self._lock = threading.Lock()
        self._last_stop_ts: Optional[float] = None
        self._last_beep_ts: Optional[float] = None
        self._last_frame: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_action: Optional[str] = None  # sent | dry_run | rate_limited | error

    # ---- low-level send ----
    def _send_frame(self, frame: str) -> bool:
        cfg = self.config
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((cfg.car_ip, cfg.control_port))
            s.sendall(frame.encode("ascii"))
            s.close()
            self._last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 - report, don't crash the loop
            self._last_error = repr(exc)
            return False

    def _dispatch(self, frame: str, dry_run_note: str) -> bool:
        """Send or dry-run a frame. Caller holds no lock; we take it."""
        with self._lock:
            self._last_frame = frame
            if not self.config.actuation_enabled:
                self._last_action = "dry_run"
                print(f"[OBSTACLE] {dry_run_note} (dry-run) frame={frame}", flush=True)
                return False
        ok = self._send_frame(frame)
        with self._lock:
            self._last_action = "sent" if ok else "error"
        if ok:
            print(f"[OBSTACLE] sent {dry_run_note} frame={frame}", flush=True)
        else:
            print(f"[OBSTACLE] FAILED {dry_run_note} frame={frame} err={self._last_error}", flush=True)
        return ok

    # ---- rate-limited high-level actions ----
    def trigger_stop(self) -> bool:
        cfg = self.config
        if not cfg.stop_enabled:
            return False
        now = time.time()
        with self._lock:
            if self._last_stop_ts is not None and now - self._last_stop_ts < cfg.stop_interval_sec:
                self._last_action = "rate_limited"
                return False
            self._last_stop_ts = now
        return self._dispatch(stop_frame(), "STOP")

    def trigger_beep(self) -> bool:
        cfg = self.config
        if not cfg.beep_enabled:
            return False
        now = time.time()
        with self._lock:
            if self._last_beep_ts is not None and now - self._last_beep_ts < cfg.beep_interval_sec:
                self._last_action = "rate_limited"
                return False
            self._last_beep_ts = now
        return self._dispatch(beep_frame(cfg.beep_duration_ms), "BEEP")

    # ---- manual (unthrottled) actions for test buttons ----
    def send_beep_now(self, duration_ms: int) -> bool:
        return self._dispatch(beep_frame(duration_ms), f"BEEP({duration_ms}ms manual)")

    def send_stop_now(self) -> bool:
        return self._dispatch(stop_frame(), "STOP(manual)")

    def state_dict(self) -> dict:
        with self._lock:
            return {
                "actuation_enabled": self.config.actuation_enabled,
                "beep_enabled": self.config.beep_enabled,
                "stop_enabled": self.config.stop_enabled,
                "last_frame": self._last_frame,
                "last_action": self._last_action,
                "last_stop_ts": self._last_stop_ts,
                "last_beep_ts": self._last_beep_ts,
                "last_error": self._last_error,
            }
