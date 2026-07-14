#!/usr/bin/env python3
"""Depth-priority obstacle alarm service.

Runs a small HTTP API on the host while reading ROS2 /scan and Astra depth
images from Docker. The fused decision uses depth camera status first; if depth
is unavailable, it falls back to lidar. DANGER triggers rate-limited buzzer and
stop commands unless disabled by CLI flags.
"""

import argparse
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, request

from obstacle_alert.src.detector import ObstacleDetector
from obstacle_alert.src.docker_depth import DockerDepthStream
from obstacle_alert.src.docker_lidar import DockerLidarStream
from obstacle_alert.src.hardware import RosmasterActions
from obstacle_alert.src.state import ObstacleConfig, ObstacleStatus


class ObstacleAlarmService:
    def __init__(self, config: ObstacleConfig, args):
        self.config = config
        self.lidar_detector = ObstacleDetector(
            config,
            source="lidar",
            distance_key="front_min_m",
            none_is_clear=True,
        )
        self.depth_detector = ObstacleDetector(
            config,
            source="depth",
            distance_key="center_depth_m",
            none_is_clear=False,
        )
        self._lock = threading.Lock()
        self._fused_status = ObstacleStatus(timestamp=time.time())
        self._last_stream_error = None
        self._last_depth_error = None
        self._last_console_level = None
        self._last_console_ts = 0.0
        self._console_interval_sec = args.console_interval

        self.actions = RosmasterActions(
            beep_enabled=config.beep_enabled,
            stop_enabled=config.stop_enabled,
            beep_duration_ms=config.beep_duration_ms,
            beep_interval_sec=config.beep_interval_sec,
            stop_interval_sec=config.stop_interval_sec,
            debug=args.debug_hardware,
        )

        self.lidar_stream = DockerLidarStream(
            container=args.container,
            topic=args.topic,
            front_min_deg=config.front_min_deg,
            front_max_deg=config.front_max_deg,
            max_range_m=config.max_range_m,
            publish_interval_sec=args.sample_interval,
            start_lidar=not args.no_start_lidar,
            on_sample=self.on_lidar_sample,
            on_error=self.on_lidar_error,
        )
        self.depth_stream = None
        if not args.no_depth:
            self.depth_stream = DockerDepthStream(
                container=args.depth_container or args.container,
                topic=args.depth_topic,
                roi_x_min=args.depth_roi_x_min,
                roi_x_max=args.depth_roi_x_max,
                roi_y_min=args.depth_roi_y_min,
                roi_y_max=args.depth_roi_y_max,
                min_depth_m=args.depth_min,
                max_depth_m=args.depth_max,
                percentile=args.depth_percentile,
                publish_interval_sec=args.depth_sample_interval,
                start_camera=not args.no_start_depth,
                on_sample=self.on_depth_sample,
                on_error=self.on_depth_error,
            )

    def start(self):
        self.lidar_stream.start()
        if self.depth_stream is not None:
            try:
                self.depth_stream.start()
            except Exception as exc:
                self._last_depth_error = repr(exc)
                self.depth_stream = None

    def stop(self):
        if self.depth_stream is not None:
            self.depth_stream.stop()
        self.lidar_stream.stop()
        self.actions.close()

    def on_lidar_sample(self, sample: dict) -> None:
        self.lidar_detector.update_sample(sample)
        self._refresh_fused_status()

    def on_depth_sample(self, sample: dict) -> None:
        if sample.get("error"):
            self._last_depth_error = sample.get("error")
        self.depth_detector.update_sample(sample)
        if sample.get("error") and sample.get("center_depth_m") is None:
            self.depth_detector.set_error(sample.get("error"))
        self._refresh_fused_status()

    def _refresh_fused_status(self) -> None:
        depth = self.depth_detector.get_status()
        lidar = self.lidar_detector.get_status()

        # Depth has higher priority whenever it is fresh and has a usable
        # decision. If depth is stale/UNKNOWN, use lidar as fallback.
        if not depth.stale and depth.level != "UNKNOWN":
            fused = depth
        else:
            fused = lidar

        with self._lock:
            self._fused_status = fused

        self._print_obstacle_event(fused)
        if fused.level == "DANGER":
            self.actions.trigger_stop()
            self.actions.trigger_beep()

    def _print_obstacle_event(self, status) -> None:
        now = time.time()
        should_print = status.level in ("WARN", "DANGER")
        if not should_print:
            if self._last_console_level in ("WARN", "DANGER"):
                print(f"[OBSTACLE] CLEAR source={status.source}: {status.message}", flush=True)
            self._last_console_level = status.level
            return

        level_changed = status.level != self._last_console_level
        interval_reached = now - self._last_console_ts >= self._console_interval_sec
        if level_changed or interval_reached:
            distance = "unknown" if status.distance_m is None else f"{status.distance_m:.2f}m"
            print(
                f"[OBSTACLE] {status.level} source={status.source}: "
                f"distance={distance}, raw={status.raw_level}, message={status.message}",
                flush=True,
            )
            self._last_console_ts = now
        self._last_console_level = status.level

    def on_lidar_error(self, error: str) -> None:
        self._last_stream_error = error
        self.lidar_detector.set_error(error)
        self._refresh_fused_status()

    def on_depth_error(self, error: str) -> None:
        self._last_depth_error = error
        self.depth_detector.set_error(error)
        self._refresh_fused_status()

    def _sensor_payloads(self) -> dict:
        return {
            "depth": self.depth_detector.get_status().to_dict(self.config, {}),
            "lidar": self.lidar_detector.get_status().to_dict(self.config, {}),
        }

    def status_payload(self) -> dict:
        with self._lock:
            fused = self._fused_status
        payload = fused.to_dict(self.config, self.actions.actions_dict())
        payload["fusion_policy"] = "depth_first_lidar_fallback"
        payload["sensors"] = self._sensor_payloads()
        return payload

    def health_payload(self) -> dict:
        with self._lock:
            fused = self._fused_status
        lidar = self.lidar_detector.get_status()
        depth = self.depth_detector.get_status()
        return {
            "ok": not fused.stale and fused.level != "UNKNOWN",
            "service": "obstacle_alert",
            "fusion_policy": "depth_first_lidar_fallback",
            "level": fused.level,
            "source": fused.source,
            "lidar_alive": not lidar.stale,
            "depth_alive": self.depth_stream is not None and not depth.stale and depth.level != "UNKNOWN" and not depth.error,
            "last_lidar_age_sec": lidar.scan_age_sec,
            "last_depth_age_sec": depth.scan_age_sec,
            "lidar_container": lidar.docker_container or self.lidar_stream.container,
            "depth_container": depth.docker_container or (self.depth_stream.container if self.depth_stream else None),
            "last_lidar_error": self._last_stream_error,
            "last_depth_error": self._last_depth_error,
        }

    def update_config(self, payload: dict) -> dict:
        allowed = {
            "warn_distance_m": float,
            "danger_distance_m": float,
            "front_min_deg": float,
            "front_max_deg": float,
            "max_range_m": float,
            "stale_after_sec": float,
            "warn_confirm_count": int,
            "danger_confirm_count": int,
            "clear_confirm_count": int,
            "beep_enabled": bool,
            "stop_enabled": bool,
            "beep_duration_ms": int,
            "beep_interval_sec": float,
            "stop_interval_sec": float,
        }
        updates = {}
        for key, caster in allowed.items():
            if key in payload:
                value = payload[key]
                if caster is bool:
                    if isinstance(value, bool):
                        updates[key] = value
                    else:
                        raise ValueError(f"{key} must be a boolean")
                else:
                    updates[key] = caster(value)

        self.lidar_detector.update_config(**updates)
        self.depth_detector.update_config(**updates)
        self.actions.beep_enabled = self.config.beep_enabled
        self.actions.stop_enabled = self.config.stop_enabled
        self.actions.beep_duration_ms = self.config.beep_duration_ms
        self.actions.beep_interval_sec = self.config.beep_interval_sec
        self.actions.stop_interval_sec = self.config.stop_interval_sec
        return self.status_payload()


def create_app(service: ObstacleAlarmService) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return jsonify({
            "service": "obstacle_alert",
            "status": "/api/obstacle/status",
            "health": "/api/obstacle/health",
            "config": "/api/obstacle/config",
        })

    @app.route("/api/obstacle/status", methods=["GET"])
    def obstacle_status():
        return jsonify(service.status_payload())

    @app.route("/api/obstacle/health", methods=["GET"])
    def obstacle_health():
        payload = service.health_payload()
        return jsonify(payload), 200 if payload["ok"] else 503

    @app.route("/api/obstacle/config", methods=["GET", "POST"])
    def obstacle_config():
        if request.method == "GET":
            return jsonify(service.status_payload()["config"])
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(service.update_config(payload))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    return app


def parse_args():
    parser = argparse.ArgumentParser(description="Depth-priority obstacle alarm HTTP service.")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host. Default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=6511, help="HTTP port. Default: 6511")
    parser.add_argument("--container", help="Docker container name for lidar. Default: auto-discover")
    parser.add_argument("--topic", default="/scan", help="LaserScan topic inside Docker. Default: /scan")
    parser.add_argument("--warn-distance", type=float, default=0.90, help="WARN threshold in meters.")
    parser.add_argument("--danger-distance", type=float, default=0.50, help="DANGER threshold in meters.")
    parser.add_argument("--front-min-deg", type=float, default=-30.0, help="Front sector min angle.")
    parser.add_argument("--front-max-deg", type=float, default=30.0, help="Front sector max angle.")
    parser.add_argument("--max-range", type=float, default=8.0, help="Ignore lidar ranges beyond this value.")
    parser.add_argument("--sample-interval", type=float, default=0.10, help="Seconds between emitted lidar samples.")
    parser.add_argument("--warn-confirm-count", type=int, default=2, help="Consecutive WARN samples before WARN.")
    parser.add_argument("--danger-confirm-count", type=int, default=2, help="Consecutive DANGER samples before DANGER.")
    parser.add_argument("--clear-confirm-count", type=int, default=5, help="Consecutive CLEAR samples to leave alarm states.")
    parser.add_argument("--no-beep", action="store_true", help="Disable buzzer action.")
    parser.add_argument("--no-stop", action="store_true", help="Disable stop protection action.")
    parser.add_argument("--no-start-lidar", action="store_true", help="Do not launch sllidar if /scan is absent.")
    parser.add_argument("--no-depth", action="store_true", help="Disable Astra depth fusion and use lidar only.")
    parser.add_argument("--depth-container", help="Docker container name for depth camera. Default: same as --container or auto-discover")
    parser.add_argument("--depth-topic", default="/camera/depth/image_raw", help="Depth Image topic inside Docker.")
    parser.add_argument("--depth-sample-interval", type=float, default=0.20, help="Seconds between depth samples.")
    parser.add_argument("--depth-roi-x-min", type=float, default=0.35, help="Depth ROI left ratio.")
    parser.add_argument("--depth-roi-x-max", type=float, default=0.65, help="Depth ROI right ratio.")
    parser.add_argument("--depth-roi-y-min", type=float, default=0.40, help="Depth ROI top ratio.")
    parser.add_argument("--depth-roi-y-max", type=float, default=0.75, help="Depth ROI bottom ratio.")
    parser.add_argument("--depth-min", type=float, default=0.15, help="Ignore depth below this value in meters.")
    parser.add_argument("--depth-max", type=float, default=6.0, help="Ignore depth beyond this value in meters.")
    parser.add_argument("--depth-percentile", type=float, default=20.0, help="Depth percentile used as distance.")
    parser.add_argument("--no-start-depth", action="store_true", help="Do not launch astra_camera if depth topic is absent.")
    parser.add_argument("--console-interval", type=float, default=1.0, help="Seconds between repeated WARN/DANGER console logs.")
    parser.add_argument("--debug-hardware", action="store_true", help="Enable Rosmaster debug output.")
    return parser.parse_args()


def main():
    args = parse_args()
    config = ObstacleConfig(
        warn_distance_m=args.warn_distance,
        danger_distance_m=args.danger_distance,
        front_min_deg=args.front_min_deg,
        front_max_deg=args.front_max_deg,
        max_range_m=args.max_range,
        warn_confirm_count=args.warn_confirm_count,
        danger_confirm_count=args.danger_confirm_count,
        clear_confirm_count=args.clear_confirm_count,
        beep_enabled=not args.no_beep,
        stop_enabled=not args.no_stop,
    )
    config.validate()
    service = ObstacleAlarmService(config, args)
    service.start()
    app = create_app(service)
    try:
        app.run(host=args.host, port=args.port, debug=False, threaded=True)
    finally:
        service.stop()


if __name__ == "__main__":
    main()
