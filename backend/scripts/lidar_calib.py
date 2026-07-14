#!/usr/bin/env python3
"""Lidar forward-angle calibration helper.

The lidar's 0 rad is usually NOT the robot's forward direction (mounting
rotation). Put a single obstacle directly in front of the car, run this, and it
reports the lidar angle where the nearest return sits — that angle is your
`lidar_forward_deg`. Set it via:

  curl -X POST http://127.0.0.1:5000/api/obstacle/config \
       -H "Content-Type: application/json" -d "{\"lidar_forward_deg\": <ANGLE>}"

Usage:
  conda run -n fcar python backend/scripts/lidar_calib.py --ip 192.168.137.174
"""
import argparse
import json
import math
import time

import websocket


def collect_scan(ip: str, port: int, wait_s: float):
    url = f"ws://{ip}:{port}"
    ws = websocket.create_connection(url, timeout=8)
    end = time.time() + wait_s
    last = None
    try:
        while time.time() < end:
            try:
                m = ws.recv()
            except Exception:
                break
            if isinstance(m, bytes):
                m = m.decode("utf-8", "ignore")
            if m.startswith("@SCAN"):
                last = json.loads(m[len("@SCAN"):-1])
    finally:
        ws.close()
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.137.174")
    ap.add_argument("--port", type=int, default=6602)
    ap.add_argument("--wait", type=float, default=6.0, help="seconds to collect")
    args = ap.parse_args()

    print(f"connecting ws://{args.ip}:{args.port} ... put ONE obstacle directly in front of the car")
    scan = collect_scan(args.ip, args.port, args.wait)
    if not scan:
        print("NO @SCAN received. Is sensor_relay running and /scan publishing?")
        return 1

    r = scan["ranges"]
    amin = float(scan["angle_min"])
    inc = float(scan["angle_increment"])
    rmin = float(scan.get("range_min", 0.15))
    rmax = float(scan.get("range_max", 12.0))

    pts = []
    for i, x in enumerate(r):
        if isinstance(x, (int, float)) and math.isfinite(x) and rmin < x < rmax and x > 0:
            pts.append((math.degrees(amin + i * inc), float(x)))
    if not pts:
        print("scan received but no valid points; move the obstacle closer")
        return 1

    nearest = min(pts, key=lambda p: p[1])
    # Average the angle of the few nearest points for a stable estimate.
    near_sorted = sorted(pts, key=lambda p: p[1])[:8]
    avg_angle = sum(p[0] for p in near_sorted) / len(near_sorted)

    print(f"\n{len(pts)} valid points; nearest={nearest[1]:.2f} m at {nearest[0]:.1f} deg")
    print(f"averaged nearest-cluster angle = {avg_angle:.1f} deg")
    print("\n== nearest range per 30-deg bucket ==")
    buckets: dict[int, list[float]] = {}
    for deg, rng in pts:
        b = int(math.floor((deg + 180) / 30)) * 30 - 180
        buckets.setdefault(b, []).append(rng)
    for b in sorted(buckets):
        print(f"  [{b:4d}..{b+30:4d}) deg : n={len(buckets[b]):3d}  min={min(buckets[b]):.2f} m")

    print(f"\n>>> If that obstacle is directly ahead, set lidar_forward_deg = {round(avg_angle)}")
    print(f">>> curl -X POST http://127.0.0.1:5000/api/obstacle/config "
          f"-H \"Content-Type: application/json\" -d \"{{\\\"lidar_forward_deg\\\": {round(avg_angle)}}}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
