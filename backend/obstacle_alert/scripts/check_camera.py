#!/usr/bin/env python3
"""Check Rosmaster camera devices without starting the main APP service."""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from camera_rosmaster import Rosmaster_Camera  # noqa: E402


DEVICE_MAP = {
    "depth": 0x50,
    "usb": 0x51,
    "wide": 0x52,
}


def parse_device(value):
    if value in DEVICE_MAP:
        return value, DEVICE_MAP[value]
    try:
        numeric = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"unknown device '{value}', use depth/usb/wide/all or a numeric id"
        ) from exc
    return value, numeric


def check_one(label, video_id, frames, width, height, debug=False):
    result = {
        "device": label,
        "video_id": video_id,
        "opened": False,
        "frame_ok": False,
        "width": None,
        "height": None,
        "frames_read": 0,
        "fps_estimate": None,
        "error": None,
    }

    camera = None
    start = None
    try:
        camera = Rosmaster_Camera(video_id=video_id, width=width, height=height, debug=debug)
        result["opened"] = bool(camera.isOpened())
        if not result["opened"]:
            result["error"] = "camera is not opened; it may be absent or already used by another process"
            return result

        start = time.time()
        for _ in range(max(1, frames)):
            ok, frame = camera.get_frame()
            if not ok:
                continue
            result["frame_ok"] = True
            result["frames_read"] += 1
            result["height"] = int(frame.shape[0])
            result["width"] = int(frame.shape[1])

        elapsed = max(time.time() - start, 1e-6)
        if result["frames_read"]:
            result["fps_estimate"] = round(result["frames_read"] / elapsed, 2)
        else:
            result["error"] = "camera opened but no valid frame was read"
    except Exception as exc:  # hardware check script should report, not crash obscurely
        result["error"] = repr(exc)
    finally:
        if camera is not None:
            try:
                camera.clear()
            except Exception:
                pass
            del camera
    return result


def main():
    parser = argparse.ArgumentParser(description="Check Rosmaster camera devices.")
    parser.add_argument(
        "--device",
        default="all",
        help="depth, usb, wide, all, or a numeric OpenCV camera id. Default: all",
    )
    parser.add_argument("--frames", type=int, default=10, help="Frames to read per device.")
    parser.add_argument("--width", type=int, default=640, help="Requested frame width.")
    parser.add_argument("--height", type=int, default=480, help="Requested frame height.")
    parser.add_argument("--debug", action="store_true", help="Enable camera debug prints.")
    args = parser.parse_args()

    if args.device == "all":
        devices = list(DEVICE_MAP.items())
    else:
        devices = [parse_device(args.device)]

    results = [
        check_one(label, video_id, args.frames, args.width, args.height, args.debug)
        for label, video_id in devices
    ]
    print(json.dumps({"ok": any(r["frame_ok"] for r in results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
