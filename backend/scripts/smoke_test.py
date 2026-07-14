#!/usr/bin/env python3
"""Layer-1 smoke test: control frames, front_min, debounce, vision fallback.

No sockets required. Run: conda run -n fcar python backend/scripts/smoke_test.py
"""
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.obstacle.config import ObstacleConfig
from app.obstacle.control import beep_frame, build_frame, stop_frame
from app.obstacle.detector import FusionDetector
from app.obstacle.lidar_ws import compute_front_min

fails = []


def check(name, got, exp):
    ok = got == exp
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f" != {exp!r}"))
    if not ok:
        fails.append(name)


# --- control frames vs doc/07-08 ---
check("STOP", stop_frame(), "$0110060000B5#")
check("forward30", build_frame(0x01, 0x10, [0x00, 0x1E]), "$011006001ED3#")
check("beep200", beep_frame(200), "$0113060114CD#")
check("beep_off", beep_frame(0), "$0113060000B8#")
check("beep_cont", beep_frame(1), "$01130601FFB8#")

# --- compute_front_min ---
cfg = ObstacleConfig(car_ip="127.0.0.1")
N, amin, inc = 360, -math.pi, 2 * math.pi / 360
ranges = [5.0] * N
for i in range(N):
    a = amin + i * inc
    if math.radians(-30) <= a <= math.radians(30):
        ranges[i] = 0.42
scan = {"ranges": ranges, "angle_min": amin, "angle_increment": inc, "range_min": 0.15, "range_max": 12.0}
check("front_min~0.42", round(compute_front_min(scan, cfg), 2), 0.42)
# All-far but valid => returns that distance (classifies CLEAR downstream).
check("front_min_far=5.0", compute_front_min(dict(scan, ranges=[5.0] * N), cfg), 5.0)
# No valid points in front (all 0 / invalid) => None so downstream treats as CLEAR.
check("front_min_invalid_None", compute_front_min(dict(scan, ranges=[0.0] * N), cfg), None)
cfg.lidar_offset_m = 0.1
check("front_min_offset", round(compute_front_min(scan, cfg), 2), 0.52)
cfg.lidar_offset_m = 0.0

# --- debounce state machine (vision down => trust lidar) ---
det = FusionDetector(cfg)
lid = lambda d: {"front_min_m": d, "timestamp": time.time()}
det.update(lid(0.40), None)
det.update(lid(0.40), None)
check("danger_latched_2f", det.get_status().level, "DANGER")
check("danger_source_lidar", det.get_status().source, "lidar")
for _ in range(4):
    det.update(lid(5.0), None)
check("still_danger_after_4clear", det.get_status().level, "DANGER")
det.update(lid(5.0), None)
check("clear_after_5", det.get_status().level, "CLEAR")

# --- vision_only fallback (lidar stale) ---
det2 = FusionDetector(cfg)
vis = lambda present, area: {"present": present, "label": "person", "area_ratio": area, "timestamp": time.time()}
stale = {"front_min_m": 0.4, "timestamp": time.time() - 10}
for _ in range(2):
    det2.update(stale, vis(True, 0.20))
st = det2.get_status()
check("vision_only_danger", st.level, "DANGER")
check("vision_only_source", st.source, "vision_only")
check("vision_only_label", st.label, "person")

# --- fusion: lidar danger but vision says nothing => WARN (not DANGER) ---
det3 = FusionDetector(cfg)
for _ in range(3):
    det3.update(lid(0.40), vis(False, 0.0))
check("fusion_lidar_danger_no_vision=WARN", det3.get_status().level, "WARN")

print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
