#!/usr/bin/env python3
"""Hardware actions for buzzer and stop protection."""

import time
from typing import Optional


class RosmasterActions:
    """Rate-limited hardware actions.

    The Rosmaster instance is created lazily so the HTTP service can still run
    in status-only mode when the serial device is unavailable.
    """

    def __init__(
        self,
        beep_enabled: bool = True,
        stop_enabled: bool = True,
        beep_duration_ms: int = 80,
        beep_interval_sec: float = 1.0,
        stop_interval_sec: float = 0.5,
        debug: bool = False,
    ):
        self.beep_enabled = beep_enabled
        self.stop_enabled = stop_enabled
        self.beep_duration_ms = beep_duration_ms
        self.beep_interval_sec = beep_interval_sec
        self.stop_interval_sec = stop_interval_sec
        self.debug = debug
        self._bot = None
        self._backend: Optional[str] = None
        self._last_beep_ts: Optional[float] = None
        self._last_stop_ts: Optional[float] = None
        self._last_error: Optional[str] = None

    def _load_rosmaster(self):
        try:
            from Rosmaster_Lib import Rosmaster
            return Rosmaster, "Rosmaster_Lib"
        except Exception:
            from control import Rosmaster
            return Rosmaster, "control.py"

    def _ensure_bot(self):
        if self._bot is None:
            Rosmaster, backend = self._load_rosmaster()
            self._bot = Rosmaster(debug=self.debug)
            self._backend = backend
        return self._bot

    def actions_dict(self) -> dict:
        return {
            "beep_enabled": self.beep_enabled,
            "stop_enabled": self.stop_enabled,
            "beep_duration_ms": self.beep_duration_ms,
            "beep_interval_sec": self.beep_interval_sec,
            "stop_interval_sec": self.stop_interval_sec,
            "last_beep_ts": self._last_beep_ts,
            "last_stop_ts": self._last_stop_ts,
            "backend": self._backend,
            "last_error": self._last_error,
        }

    def trigger_beep(self) -> bool:
        if not self.beep_enabled:
            return False
        now = time.time()
        if self._last_beep_ts is not None and now - self._last_beep_ts < self.beep_interval_sec:
            return False
        try:
            bot = self._ensure_bot()
            bot.set_beep(self.beep_duration_ms)
            self._last_beep_ts = now
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = repr(exc)
            return False

    def trigger_stop(self) -> bool:
        if not self.stop_enabled:
            return False
        now = time.time()
        if self._last_stop_ts is not None and now - self._last_stop_ts < self.stop_interval_sec:
            return False
        try:
            bot = self._ensure_bot()
            bot.set_car_motion(0, 0, 0)
            bot.set_car_run(0, 0)
            self._last_stop_ts = now
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = repr(exc)
            return False

    def close(self) -> None:
        if self._bot is not None:
            try:
                self._bot.set_beep(0)
            except Exception:
                pass
            try:
                del self._bot
            except Exception:
                pass
            self._bot = None
