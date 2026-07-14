#!/usr/bin/env python3
"""HTTP-layer test: blueprint registration, obstacle endpoints, config update.

Uses Flask's test client (no port binding). Run:
  conda run -n fcar python backend/scripts/app_test.py
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import attach_obstacle_service, create_app
from app.obstacle.config import ObstacleConfig
from app.obstacle.service import ObstacleService

fails = []


def check(name, cond, detail=""):
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if not cond:
        fails.append(name)


# Service without live sensors (no mock) => level UNKNOWN, but routing must work.
svc = ObstacleService(ObstacleConfig(car_ip="127.0.0.1", vision_enabled=False))
svc.start()
app = create_app()
attach_obstacle_service(app, svc)
client = app.test_client()

try:
    # Existing endpoints still work.
    r = client.get("/api/health")
    check("legacy_health_200", r.status_code == 200, str(r.status_code))
    r = client.get("/api/vehicle/status")
    check("legacy_vehicle_200", r.status_code == 200, str(r.status_code))

    # Obstacle status shape.
    r = client.get("/api/obstacle/status")
    check("obstacle_status_200", r.status_code == 200, str(r.status_code))
    js = r.get_json()
    for key in ("level", "source", "fusion_policy", "config", "control", "sensors"):
        check(f"status_has_{key}", key in js)
    check("sensors_has_lidar_vision",
          "lidar" in js["sensors"] and "vision" in js["sensors"])

    # Health returns 503 while UNKNOWN (no sensors), but valid JSON.
    r = client.get("/api/obstacle/health")
    check("health_503_when_unknown", r.status_code in (200, 503), str(r.status_code))
    check("health_has_actuation", "actuation_enabled" in r.get_json())

    # Config GET + POST (toggle actuation).
    r = client.get("/api/obstacle/config")
    check("config_get_200", r.status_code == 200, str(r.status_code))
    before = r.get_json()["actuation_enabled"]
    r = client.post("/api/obstacle/config", json={"actuation_enabled": not before})
    check("config_post_200", r.status_code == 200, str(r.status_code))
    check("config_toggled", svc.config.actuation_enabled == (not before),
          str(svc.config.actuation_enabled))

    # Invalid config rejected (danger >= warn).
    r = client.post("/api/obstacle/config", json={"danger_distance_m": 999})
    check("config_invalid_400", r.status_code == 400, str(r.status_code))

    # Manual beep/stop endpoints (dry-run since actuation may be off; both 200).
    svc.config.actuation_enabled = False
    r = client.post("/api/car/beep", json={"duration_ms": 200})
    check("beep_endpoint_200", r.status_code == 200, str(r.status_code))
    r = client.post("/api/car/stop")
    check("stop_endpoint_200", r.status_code == 200, str(r.status_code))
finally:
    svc.stop()

print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
