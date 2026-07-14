#!/usr/bin/env python3
"""Validate the 6000 control protocol against the real car.

Sends a battery query (expects a response if framing is correct) and a 1.5s
CONTINUOUS beep on a single persistent connection (clearly audible if the frame
is understood). Distinguishes "wrong protocol" from "backend send pattern" bugs.

Run: conda run -n fcar python backend/scripts/control_probe.py --ip 192.168.137.174
"""
import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.obstacle.control import beep_frame, build_frame, stop_frame  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.137.174")
    ap.add_argument("--port", type=int, default=6000)
    args = ap.parse_args()
    addr = (args.ip, args.port)

    print(f"connecting {addr} (single persistent connection)")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(addr)

    # 1) battery query (cmd 02) -> the car may or may not reply; correct checksum
    batt = build_frame(0x01, 0x02, [0x00])
    print(f"battery query {batt}")
    s.sendall(batt.encode())
    try:
        resp = s.recv(256)
        print(f"battery query response: {resp!r}  (len={len(resp)})")
    except Exception as e:
        print(f"battery query: NO RESPONSE ({e!r})")

    # 2) continuous beep for 1.5s on the SAME connection (should be audible)
    cont = beep_frame(1)
    print(f"sending CONTINUOUS beep ({cont}) for 1.5s ... LISTEN NOW")
    s.sendall(cont.encode())
    time.sleep(1.5)
    off = beep_frame(0)
    print(f"beep OFF ({off})")
    s.sendall(off.encode())
    time.sleep(0.2)

    # 3) a couple of timed 200ms beeps
    b200 = beep_frame(200)
    for i in range(2):
        print(f"beep 200ms #{i+1} {b200}")
        s.sendall(b200.encode())
        time.sleep(0.8)

    _ = stop_frame  # available if you want to test motion stop

    s.close()
    print("done. Did you hear anything?")


if __name__ == "__main__":
    main()
