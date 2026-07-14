"""HTTP routes for the obstacle subsystem, registered under /api."""

from __future__ import annotations

import time

from flask import Blueprint, Response, current_app, jsonify, request

obstacle_bp = Blueprint("obstacle", __name__)


def _service():
    """Fetch the singleton ObstacleService attached to the app, or None."""
    return current_app.config.get("OBSTACLE_SERVICE")


def _require_service():
    svc = _service()
    if svc is None:
        return None, (jsonify({"error": "obstacle service not running"}), 503)
    return svc, None


@obstacle_bp.get("/obstacle/status")
def obstacle_status():
    svc, err = _require_service()
    if err:
        return err
    return jsonify(svc.status_payload())


@obstacle_bp.get("/obstacle/health")
def obstacle_health():
    svc, err = _require_service()
    if err:
        return err
    payload = svc.health_payload()
    return jsonify(payload), (200 if payload["ok"] else 503)


@obstacle_bp.route("/obstacle/config", methods=["GET", "POST"])
def obstacle_config():
    svc, err = _require_service()
    if err:
        return err
    if request.method == "GET":
        return jsonify(svc.config.to_dict())
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(svc.update_config(payload))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@obstacle_bp.get("/obstacle/video")
def obstacle_video():
    """Annotated MJPEG stream (YOLO boxes). Falls back to a placeholder frame."""
    svc, err = _require_service()
    if err:
        return err
    boundary = "frame"

    def generate():
        while True:
            jpeg = svc.vision.get_jpeg()
            if jpeg is None:
                time.sleep(0.2)
                continue
            yield (
                f"--{boundary}\r\n"
                f"Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(jpeg)}\r\n\r\n"
            ).encode("utf-8") + jpeg + b"\r\n"
            time.sleep(0.05)

    return Response(
        generate(),
        mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@obstacle_bp.post("/car/beep")
def car_beep():
    svc, err = _require_service()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    duration_ms = int(data.get("duration_ms", 200))
    sent = svc.control.send_beep_now(duration_ms)
    return jsonify({"ok": True, "sent": sent, "control": svc.control.state_dict()})


@obstacle_bp.post("/car/stop")
def car_stop():
    svc, err = _require_service()
    if err:
        return err
    sent = svc.control.send_stop_now()
    return jsonify({"ok": True, "sent": sent, "control": svc.control.state_dict()})
