#!/usr/bin/env python3
"""Local car simulator for testing the PC-side obstacle subsystem without a car.

Starts up to three servers on localhost:
  6602  WebSocket  -> periodic @SCAN{json}# frames (toggle near/far obstacle)
  6500  HTTP MJPEG -> /video_feed, PIL-drawn frames (a box in the front sector)
  6000  TCP        -> control sink, prints and checksum-verifies received frames

Interactive stdin commands (when attached to a terminal):
  c  -> front sector CLEAR (~5.0 m)
  w  -> front sector WARN  (~0.70 m)
  d  -> front sector DANGER(~0.40 m)
  b  -> toggle drawing an obstacle box in the video
  q  -> quit

Usage:
  python backend/scripts/mock_car.py                 # all three servers
  python backend/scripts/mock_car.py --only 6000     # just the control sink
  python backend/scripts/mock_car.py --state danger  # initial lidar state
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Shared, mutable sim state.
STATE = {
    "front_distance": 5.0,   # meters placed in the front sector
    "draw_box": False,       # draw an obstacle box into the video
    "running": True,
}
_lock = threading.Lock()

NUM_POINTS = 360
ANGLE_MIN = -math.pi
ANGLE_INCREMENT = (2 * math.pi) / NUM_POINTS


def verify_checksum(frame: str) -> bool:
    """Validate a $CCTTLL..XX# control frame's checksum.

    Matches the car's rosmaster_main_ori.py parse_data(): sum of every byte from
    CC through the last payload byte, mod 256 (no 0x9E seed).
    """
    try:
        if not (frame.startswith("$") and frame.endswith("#")):
            return False
        body_hex = frame[1:-1]
        data = [int(body_hex[i:i + 2], 16) for i in range(0, len(body_hex), 2)]
        *fields, checksum = data
        return (sum(fields) % 256) == checksum
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 6602 WebSocket server (minimal, hand-rolled)
# --------------------------------------------------------------------------- #
def _ws_handshake(conn: socket.socket) -> bool:
    data = b""
    conn.settimeout(5)
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(1024)
        if not chunk:
            return False
        data += chunk
    key = None
    for line in data.decode("latin1").split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
    if not key:
        return False
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    resp = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    conn.sendall(resp.encode())
    return True


def _ws_send_text(conn: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray([0x81])  # FIN + text opcode
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    conn.sendall(bytes(header) + payload)  # server frames are not masked


def _build_scan() -> str:
    with _lock:
        front = STATE["front_distance"]
    ranges = [5.0] * NUM_POINTS
    # Front sector is index ~[150, 210] (angle around 0). Place the obstacle there.
    for i in range(NUM_POINTS):
        angle = ANGLE_MIN + i * ANGLE_INCREMENT
        if math.radians(-30) <= angle <= math.radians(30):
            ranges[i] = front
    scan = {
        "ranges": [round(r, 3) for r in ranges],
        "angle_min": ANGLE_MIN,
        "angle_max": math.pi,
        "angle_increment": ANGLE_INCREMENT,
        "range_min": 0.15,
        "range_max": 12.0,
        "t": time.time(),
    }
    return "@SCAN" + json.dumps(scan) + "#"


def _ws_client(conn: socket.socket, addr) -> None:
    try:
        if not _ws_handshake(conn):
            conn.close()
            return
        print(f"[mock 6602] client connected {addr}", flush=True)
        conn.settimeout(None)
        while STATE["running"]:
            _ws_send_text(conn, _build_scan())
            time.sleep(0.1)
    except Exception as exc:
        print(f"[mock 6602] client gone: {exc!r}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve_ws(host: str, port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    print(f"[mock 6602] websocket serving on {host}:{port}", flush=True)
    while STATE["running"]:
        try:
            conn, addr = srv.accept()
        except OSError:
            break
        threading.Thread(target=_ws_client, args=(conn, addr), daemon=True).start()


# --------------------------------------------------------------------------- #
# 6500 HTTP MJPEG server
# --------------------------------------------------------------------------- #
def _make_frame(idx: int) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 480), (24, 32, 40))
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 20, 620, 460), outline=(56, 189, 248), width=2)
    draw.text((30, 30), "MOCK CAR VIDEO (6500)", fill=(226, 232, 240))
    draw.text((30, 50), f"frame #{idx}", fill=(148, 163, 184))
    with _lock:
        box = STATE["draw_box"]
        front = STATE["front_distance"]
    draw.text((30, 70), f"front={front:.2f}m box={box}", fill=(125, 211, 252))
    if box:
        # A brown box in the front-central band (won't reliably trigger YOLO;
        # the vision path is validated against the real car).
        draw.rectangle((250, 200, 390, 400), fill=(120, 85, 60), outline=(200, 160, 120), width=3)
        draw.text((260, 205), "obstacle", fill=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request logging
        pass

    def do_GET(self):
        if self.path.startswith("/video_feed"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            idx = 0
            try:
                while STATE["running"]:
                    jpeg = _make_frame(idx)
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                    self.wfile.write(jpeg + b"\r\n")
                    idx += 1
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><img src='/video_feed' width='720'></body></html>")


def serve_mjpeg(host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), MJPEGHandler)
    print(f"[mock 6500] mjpeg serving on {host}:{port}/video_feed", flush=True)
    httpd.serve_forever()


# --------------------------------------------------------------------------- #
# 6000 TCP control sink
# --------------------------------------------------------------------------- #
def serve_control(host: str, port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    print(f"[mock 6000] control sink serving on {host}:{port}", flush=True)
    while STATE["running"]:
        try:
            conn, addr = srv.accept()
        except OSError:
            break

        def handle(c=conn):
            # Persistent client: keep reading complete $...# frames until the
            # peer disconnects (mirrors the real car's single long connection).
            try:
                c.settimeout(30)
                buf = ""
                while STATE["running"]:
                    data = c.recv(256)
                    if not data:
                        break
                    buf += data.decode("ascii", "ignore")
                    while "#" in buf:
                        idx = buf.index("#")
                        frame, buf = buf[:idx + 1], buf[idx + 1:]
                        start = frame.rfind("$")
                        if start < 0:
                            continue
                        frame = frame[start:]
                        ok = verify_checksum(frame)
                        print(f"[mock 6000] recv {frame!r} checksum_ok={ok}", flush=True)
            except Exception:
                pass
            finally:
                c.close()

        threading.Thread(target=handle, daemon=True).start()


# --------------------------------------------------------------------------- #
def _stdin_loop() -> None:
    mapping = {"c": 5.0, "w": 0.70, "d": 0.40}
    for line in sys.stdin:
        cmd = line.strip().lower()
        if cmd in mapping:
            with _lock:
                STATE["front_distance"] = mapping[cmd]
            print(f"[mock] front_distance -> {mapping[cmd]}m", flush=True)
        elif cmd == "b":
            with _lock:
                STATE["draw_box"] = not STATE["draw_box"]
            print(f"[mock] draw_box -> {STATE['draw_box']}", flush=True)
        elif cmd == "q":
            STATE["running"] = False
            print("[mock] quitting", flush=True)
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Local car simulator for obstacle testing.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--only", choices=("6000", "6500", "6602"), help="Run a single server.")
    parser.add_argument("--state", choices=("clear", "warn", "danger"), default="clear")
    parser.add_argument("--box", action="store_true", help="Start with an obstacle box drawn.")
    args = parser.parse_args()

    STATE["front_distance"] = {"clear": 5.0, "warn": 0.70, "danger": 0.40}[args.state]
    STATE["draw_box"] = args.box

    servers = {"6602": serve_ws, "6500": serve_mjpeg, "6000": serve_control}
    selected = {args.only: servers[args.only]} if args.only else servers

    for name, fn in selected.items():
        threading.Thread(target=fn, args=(args.host, int(name)), daemon=True).start()

    print(f"[mock] running {list(selected)} on {args.host}. Commands: c/w/d/b/q", flush=True)
    # Read interactive commands in a background thread (if attached to a tty) so
    # the servers stay alive even when stdin is closed/EOF (e.g. spawned as a
    # subprocess with stdin=DEVNULL). The main thread just keeps the process up.
    if sys.stdin and sys.stdin.isatty():
        threading.Thread(target=_stdin_loop, daemon=True).start()
    try:
        while STATE["running"]:
            time.sleep(0.5)
    except KeyboardInterrupt:
        STATE["running"] = False


if __name__ == "__main__":
    main()
