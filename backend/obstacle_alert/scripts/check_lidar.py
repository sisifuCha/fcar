#!/usr/bin/env python3
"""Check ROS2 LaserScan availability and front-sector obstacle distance."""

import argparse
import json
import math
import sys
import time


def sector_min_range(scan, angle_min_deg, angle_max_deg, max_range=8.0):
    if not scan.ranges:
        return None

    lo = math.radians(min(angle_min_deg, angle_max_deg))
    hi = math.radians(max(angle_min_deg, angle_max_deg))
    best = None
    angle = scan.angle_min
    upper_range = min(scan.range_max, max_range)

    for distance in scan.ranges:
        if scan.range_min < distance < upper_range and lo <= angle <= hi:
            if best is None or distance < best:
                best = float(distance)
        angle += scan.angle_increment

    return best


def main():
    parser = argparse.ArgumentParser(description="Read one /scan message and report front minimum distance.")
    parser.add_argument("--topic", default="/scan", help="LaserScan topic name. Default: /scan")
    parser.add_argument("--timeout", type=float, default=5.0, help="Seconds to wait for one scan.")
    parser.add_argument("--front-min-deg", type=float, default=-30.0, help="Front sector min angle in degrees.")
    parser.add_argument("--front-max-deg", type=float, default=30.0, help="Front sector max angle in degrees.")
    parser.add_argument("--max-range", type=float, default=8.0, help="Ignore ranges beyond this value in meters.")
    args = parser.parse_args()

    try:
        import rclpy
        from rclpy.node import Node
        from sensor_msgs.msg import LaserScan
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": "ROS2 Python packages are not importable. Source the ROS2 environment first.",
            "detail": repr(exc),
        }, ensure_ascii=False, indent=2))
        return 2

    result = {
        "ok": False,
        "topic": args.topic,
        "front_min_m": None,
        "range_count": 0,
        "angle_min": None,
        "angle_max": None,
        "range_min": None,
        "range_max": None,
        "elapsed_sec": None,
        "error": None,
    }

    class ScanOnce(Node):
        def __init__(self):
            super().__init__("obstacle_alert_check_lidar")
            self.scan = None
            self.create_subscription(LaserScan, args.topic, self.on_scan, 10)

        def on_scan(self, msg):
            self.scan = msg

    rclpy.init(args=None)
    node = ScanOnce()
    start = time.time()
    try:
        while rclpy.ok() and time.time() - start < args.timeout and node.scan is None:
            rclpy.spin_once(node, timeout_sec=0.1)

        result["elapsed_sec"] = round(time.time() - start, 3)
        if node.scan is None:
            result["error"] = f"no LaserScan received from {args.topic} within {args.timeout}s"
        else:
            scan = node.scan
            result.update({
                "ok": True,
                "front_min_m": sector_min_range(scan, args.front_min_deg, args.front_max_deg, args.max_range),
                "range_count": len(scan.ranges),
                "angle_min": scan.angle_min,
                "angle_max": scan.angle_max,
                "range_min": scan.range_min,
                "range_max": scan.range_max,
            })
    except Exception as exc:
        result["error"] = repr(exc)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
