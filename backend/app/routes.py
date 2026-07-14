from flask import Blueprint, Response, jsonify, request

from . import store

api_bp = Blueprint("api", __name__)


@api_bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "fcar-backend"})


@api_bp.get("/vehicle/status")
def vehicle_status():
    return jsonify(store.get_vehicle())


@api_bp.patch("/vehicle/status")
def patch_vehicle_status():
    data = request.get_json(silent=True) or {}
    return jsonify(store.update_vehicle(data))


@api_bp.post("/vehicle/command")
def vehicle_command():
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    if not action:
        return jsonify({"error": "action is required"}), 400

    patch: dict = {}
    if action == "start":
        patch = {"mode": "driving", "speed_kmh": float(data.get("speed_kmh", 5))}
    elif action == "stop":
        patch = {"mode": "idle", "speed_kmh": 0.0}
    elif action == "emergency":
        patch = {"mode": "emergency", "speed_kmh": 0.0}
        store.add_alert("critical", "E_STOP", "收到紧急停车指令")
    elif action == "set_speed":
        patch = {"speed_kmh": float(data.get("speed_kmh", 0))}
    else:
        return jsonify({"error": f"unknown action: {action}"}), 400

    vehicle = store.update_vehicle(patch)
    return jsonify({"ok": True, "action": action, "vehicle": vehicle})


@api_bp.get("/alerts")
def get_alerts():
    limit = request.args.get("limit", default=50, type=int)
    unacked_only = request.args.get("unacked", "false").lower() in ("1", "true", "yes")
    return jsonify({"items": store.list_alerts(limit=limit, unacked_only=unacked_only)})


@api_bp.post("/alerts")
def create_alert():
    data = request.get_json(silent=True) or {}
    level = (data.get("level") or "warning").lower()
    code = data.get("code") or "CUSTOM"
    message = data.get("message") or ""
    if not message:
        return jsonify({"error": "message is required"}), 400
    if level not in ("info", "warning", "critical"):
        return jsonify({"error": "level must be info|warning|critical"}), 400
    return jsonify(store.add_alert(level, code, message)), 201


@api_bp.post("/alerts/<alert_id>/ack")
def acknowledge_alert(alert_id: str):
    alert = store.ack_alert(alert_id)
    if not alert:
        return jsonify({"error": "alert not found"}), 404
    return jsonify(alert)


@api_bp.get("/stream")
def stream_info():
    return jsonify(store.get_stream())


@api_bp.get("/stream/mjpeg")
def stream_mjpeg():
    """Placeholder MJPEG stream; swap for camera/FFmpeg later."""
    import time
    from io import BytesIO

    from PIL import Image, ImageDraw

    boundary = "frame"

    def generate():
        frame_idx = 0
        while True:
            img = Image.new("RGB", (640, 480), (20, 28, 36))
            draw = ImageDraw.Draw(img)
            draw.rectangle((40, 40, 600, 440), outline=(56, 189, 248), width=3)
            draw.text((60, 60), "FCar Live Preview", fill=(226, 232, 240))
            draw.text((60, 100), f"frame #{frame_idx}", fill=(148, 163, 184))
            vehicle = store.get_vehicle()
            draw.text(
                (60, 140),
                f"mode={vehicle['mode']}  speed={vehicle['speed_kmh']} km/h  bat={vehicle['battery']}%",
                fill=(125, 211, 252),
            )
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=70)
            jpeg = buf.getvalue()

            yield (
                f"--{boundary}\r\n"
                f"Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(jpeg)}\r\n\r\n"
            ).encode("utf-8") + jpeg + b"\r\n"
            frame_idx += 1
            time.sleep(0.1)

    return Response(
        generate(),
        mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
