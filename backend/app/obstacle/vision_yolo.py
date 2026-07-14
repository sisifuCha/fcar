"""Vision worker: read the car's MJPEG stream (6500) and run YOLO.

Reports whether a whitelisted obstacle class overlaps the front-central band,
its class label, and the largest such bbox's area ratio (used as a proximity
proxy when lidar is unavailable). Also keeps the latest annotated JPEG for the
/api/obstacle/video endpoint.

Degrades gracefully: if OpenCV / ultralytics / the model / the stream is
unavailable, the worker marks vision as not alive and the fusion layer falls
back to lidar-only without raising.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from .config import ObstacleConfig


class VisionWorker:
    def __init__(self, config: ObstacleConfig):
        self.config = config
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._model = None
        self._names: dict = {}
        self._latest: Optional[dict] = None
        self._latest_jpeg: Optional[bytes] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._model_loaded = False

    @property
    def stream_url(self) -> str:
        return f"http://{self.config.car_ip}:{self.config.video_port}/video_feed"

    def start(self) -> None:
        if not self.config.vision_enabled:
            self._last_error = "vision disabled"
            return
        if cv2 is None:
            self._last_error = "opencv not installed"
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vision-yolo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _load_model(self) -> bool:
        if self._model_loaded:
            return self._model is not None
        self._model_loaded = True
        try:
            from ultralytics import YOLO
            self._model = YOLO("yolov8n.pt")
            self._names = self._model.names
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"model load: {exc!r}"
            self._model = None
            return False

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            # Best-effort model load; retry each reconnect if it isn't ready
            # yet (e.g. torch still installing). Streaming works regardless —
            # without a model we passthrough raw frames so the live view is
            # always available; with it we annotate + detect.
            if self._model is None:
                self._model_loaded = False
                self._load_model()
            cap = None
            try:
                cap = cv2.VideoCapture(self.stream_url)
                if not cap.isOpened():
                    raise RuntimeError("cannot open video stream")
                with self._lock:
                    self._connected = True
                    self._last_error = None
                backoff = 1.0
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        raise RuntimeError("stream read failed")
                    self._process(frame)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._connected = False
                    self._last_error = repr(exc)
            finally:
                if cap is not None:
                    cap.release()
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

    def _process(self, frame) -> None:
        cfg = self.config
        h, w = frame.shape[:2]
        frame_area = float(max(1, w * h))
        band_lo = cfg.vision_center_x_min * w
        band_hi = cfg.vision_center_x_max * w
        whitelist = set(cfg.vision_classes)

        present = False
        best_label: Optional[str] = None
        best_area_ratio = 0.0
        annotated = frame

        # No model (e.g. torch/ultralytics not installed yet): passthrough the
        # raw frame so the live view still works; report no detection.
        if self._model is None:
            self._publish(frame, {
                "present": False, "label": None, "area_ratio": 0.0,
                "timestamp": time.time(), "frame_w": w, "frame_h": h,
                "model": False,
            })
            return

        try:
            results = self._model.predict(frame, conf=cfg.vision_conf, verbose=False)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"predict: {exc!r}"
            self._publish(frame, None)
            return

        if results:
            res = results[0]
            try:
                annotated = res.plot()
            except Exception:
                annotated = frame
            boxes = getattr(res, "boxes", None)
            if boxes is not None:
                for box in boxes:
                    cls_id = int(box.cls[0])
                    label = self._names.get(cls_id, str(cls_id))
                    if whitelist and label not in whitelist:
                        continue
                    x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                    cx = (x1 + x2) / 2.0
                    # Count when the box overlaps the front-central band.
                    if x2 < band_lo or x1 > band_hi:
                        continue
                    area_ratio = max(0.0, (x2 - x1) * (y2 - y1)) / frame_area
                    present = True
                    if area_ratio > best_area_ratio:
                        best_area_ratio = area_ratio
                        best_label = label
                    _ = cx  # reserved for future lateral steering logic

        sample = {
            "present": present,
            "label": best_label,
            "area_ratio": best_area_ratio,
            "timestamp": time.time(),
            "frame_w": w,
            "frame_h": h,
        }
        jpeg = None
        if cv2 is not None:
            try:
                ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ok:
                    jpeg = buf.tobytes()
            except Exception:
                jpeg = None
        with self._lock:
            self._latest = sample
            if jpeg is not None:
                self._latest_jpeg = jpeg

    def get_latest(self) -> Optional[dict]:
        with self._lock:
            return dict(self._latest) if self._latest else None

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def health(self) -> dict:
        with self._lock:
            latest = self._latest
            age = (time.time() - latest["timestamp"]) if latest else None
            alive = bool(
                self._connected
                and self._model is not None
                and latest is not None
                and age is not None
                and age <= self.config.stale_after_sec
            )
            return {
                "connected": self._connected,
                "alive": alive,
                "enabled": self.config.vision_enabled,
                "model_loaded": self._model is not None,
                "url": self.stream_url,
                "last_error": self._last_error,
                "age_sec": age,
                "present": latest["present"] if latest else None,
                "label": latest["label"] if latest else None,
                "area_ratio": latest["area_ratio"] if latest else None,
            }
