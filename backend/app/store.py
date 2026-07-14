"""In-memory store for prototype APIs. Replace with DB / ROS bridge later."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

_lock = Lock()

_vehicle: dict[str, Any] = {
    "id": "fcar-01",
    "name": "FCar",
    "online": True,
    "battery": 86,
    "speed_kmh": 0.0,
    "mode": "idle",  # idle | driving | parking | emergency
    "position": {"lat": 31.2304, "lng": 121.4737, "heading": 90.0},
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

_stream: dict[str, Any] = {
    "enabled": True,
    "protocol": "mjpeg",
    "url": "/api/stream/mjpeg",
    "resolution": {"width": 640, "height": 480},
    "fps": 10,
}

_alerts: list[dict[str, Any]] = [
    {
        "id": str(uuid4()),
        "level": "info",
        "code": "BOOT",
        "message": "系统已启动，等待任务",
        "acked": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_vehicle() -> dict[str, Any]:
    with _lock:
        return deepcopy(_vehicle)


def update_vehicle(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        for key, value in patch.items():
            if key == "position" and isinstance(value, dict):
                _vehicle["position"].update(value)
            elif key in _vehicle and key not in ("id", "updated_at"):
                _vehicle[key] = value
        _vehicle["updated_at"] = _now()
        return deepcopy(_vehicle)


def get_stream() -> dict[str, Any]:
    with _lock:
        return deepcopy(_stream)


def list_alerts(limit: int = 50, unacked_only: bool = False) -> list[dict[str, Any]]:
    with _lock:
        items = [a for a in _alerts if not unacked_only or not a["acked"]]
        return deepcopy(items[-limit:][::-1])


def add_alert(level: str, code: str, message: str) -> dict[str, Any]:
    alert = {
        "id": str(uuid4()),
        "level": level,
        "code": code,
        "message": message,
        "acked": False,
        "created_at": _now(),
    }
    with _lock:
        _alerts.append(alert)
        return deepcopy(alert)


def ack_alert(alert_id: str) -> dict[str, Any] | None:
    with _lock:
        for alert in _alerts:
            if alert["id"] == alert_id:
                alert["acked"] = True
                return deepcopy(alert)
    return None
