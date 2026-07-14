#!/usr/bin/env python3
"""Layer-2 integration test over real sockets using mock_car.

Starts mock 6602 (lidar, DANGER) + mock 6000 (control sink), runs a real
ObstacleService against 127.0.0.1, and verifies:
  - lidar WS connects and DANGER latches (vision disabled => trust lidar)
  - actuation dry-run by default (no frame sent)
  - after enabling actuation, a valid STOP frame reaches the mock 6000 sink

Run: conda run -n fcar python backend/scripts/integration_test.py
"""
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.obstacle.config import ObstacleConfig
from app.obstacle.service import ObstacleService

MOCK = BACKEND / "scripts" / "mock_car.py"
fails = []


def check(name, cond, detail=""):
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def main():
    procs = []
    # 6602 lidar in DANGER, and a 6000 control sink (stdout captured).
    procs.append(subprocess.Popen(
        [sys.executable, str(MOCK), "--only", "6602", "--state", "danger"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ))
    sink = subprocess.Popen(
        [sys.executable, str(MOCK), "--only", "6000"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    procs.append(sink)
    time.sleep(1.5)  # let servers bind

    # mock_car places the obstacle at lidar angle 0, so use forward=0 here
    # (independent of the real-car calibrated default of 76 deg).
    cfg = ObstacleConfig(car_ip="127.0.0.1", vision_enabled=False,
                         actuation_enabled=False, lidar_forward_deg=0.0)
    svc = ObstacleService(cfg)
    svc.start()
    try:
        # Wait for lidar to connect + DANGER to latch.
        deadline = time.time() + 8
        status = None
        while time.time() < deadline:
            status = svc.status_payload()
            if status["level"] == "DANGER" and status["sensors"]["lidar"]["alive"]:
                break
            time.sleep(0.2)
        check("lidar_alive", status["sensors"]["lidar"]["alive"], str(status["sensors"]["lidar"]))
        check("level_DANGER", status["level"] == "DANGER", status["level"])
        check("source_lidar", status["source"] == "lidar", status["source"])
        check("distance_present", status["distance_m"] is not None, str(status["distance_m"]))

        # Dry-run: nothing is transmitted (action is dry_run or rate_limited,
        # never "sent"); the mock 6000 sink should have received no frame yet.
        time.sleep(0.5)
        ctrl = svc.control.state_dict()
        check("dry_run_never_sent", ctrl["last_action"] in ("dry_run", "rate_limited"),
              str(ctrl["last_action"]))

        # Enable actuation -> real frames should hit the mock 6000 sink. The
        # 10Hz loop alternates sent/rate_limited, so poll for a "sent" moment.
        svc.update_config({"actuation_enabled": True})
        sent_seen = False
        deadline = time.time() + 2.5
        while time.time() < deadline:
            if svc.control.state_dict()["last_action"] == "sent":
                sent_seen = True
                break
            time.sleep(0.05)
        ctrl = svc.control.state_dict()
        check("actuation_sent", sent_seen, str(ctrl["last_action"]))
        check("last_frame_is_stop_or_beep",
              ctrl["last_frame"] in ("$011006000017#", "$01130601142F#"),
              str(ctrl["last_frame"]))
    finally:
        svc.stop()
        for p in procs:
            p.terminate()

    # Drain the sink output to confirm it received + checksum-verified a frame.
    try:
        out, _ = sink.communicate(timeout=3)
    except Exception:
        out = ""
    got_ok_frame = "checksum_ok=True" in (out or "")
    check("sink_received_valid_frame", got_ok_frame, (out or "").strip()[-200:])

    print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
