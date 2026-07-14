#!/usr/bin/env python3
"""Stream front depth distance from an Astra ROS2 Docker container."""

import json
import subprocess
import threading
from typing import Callable, Optional

from .docker_lidar import DEFAULT_SETUP_FILES


class DockerDepthStream:
    """Runs ROS2 Astra depth reading inside Docker and emits JSON samples."""

    def __init__(
        self,
        container: Optional[str] = None,
        topic: str = "/camera/depth/image_raw",
        roi_x_min: float = 0.35,
        roi_x_max: float = 0.65,
        roi_y_min: float = 0.40,
        roi_y_max: float = 0.75,
        min_depth_m: float = 0.15,
        max_depth_m: float = 6.0,
        percentile: float = 20.0,
        publish_interval_sec: float = 0.20,
        start_camera: bool = True,
        on_sample: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.container = container
        self.topic = topic
        self.roi_x_min = roi_x_min
        self.roi_x_max = roi_x_max
        self.roi_y_min = roi_y_min
        self.roi_y_max = roi_y_max
        self.min_depth_m = min_depth_m
        self.max_depth_m = max_depth_m
        self.percentile = percentile
        self.publish_interval_sec = publish_interval_sec
        self.start_camera = start_camera
        self.on_sample = on_sample
        self.on_error = on_error
        self.process: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @staticmethod
    def _run(cmd, timeout=8) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)

    @staticmethod
    def _source_prefix() -> str:
        parts = []
        for setup in DEFAULT_SETUP_FILES:
            parts.append(f'[ -f "{setup}" ] && source "{setup}";')
        return " ".join(parts)

    @classmethod
    def discover_container(cls) -> Optional[str]:
        proc = cls._run(["docker", "ps", "--format", "{{.Names}}"], timeout=5)
        if proc.returncode != 0:
            return None
        names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        for name in names:
            check = cls._run([
                "docker",
                "exec",
                name,
                "bash",
                "-lc",
                cls._source_prefix() + " ros2 pkg list | grep -q '^astra_camera$'",
            ], timeout=8)
            if check.returncode == 0:
                return name
        return names[0] if names else None

    def _docker_script(self) -> str:
        source_prefix = self._source_prefix()
        start_camera = "1" if self.start_camera else "0"
        return f"""
set -e
{source_prefix}
CAMERA_PID=""
cleanup() {{
  if [ -n "$CAMERA_PID" ]; then
    kill "$CAMERA_PID" 2>/dev/null || true
    wait "$CAMERA_PID" 2>/dev/null || true
  fi
}}
trap cleanup EXIT INT TERM
if [ "{start_camera}" = "1" ]; then
  # Start our own Astra publisher. A stale ROS graph can still list the topic
  # after the previous camera node has died, so topic existence alone is not a
  # reliable readiness check.
  ros2 launch astra_camera astra.launch.xml >/tmp/obstacle_alert_astra.log 2>&1 &
  CAMERA_PID=$!
  sleep 4
fi
export OBSTACLE_DEPTH_TOPIC='{self.topic}'
export OBSTACLE_ROI_X_MIN='{self.roi_x_min}'
export OBSTACLE_ROI_X_MAX='{self.roi_x_max}'
export OBSTACLE_ROI_Y_MIN='{self.roi_y_min}'
export OBSTACLE_ROI_Y_MAX='{self.roi_y_max}'
export OBSTACLE_MIN_DEPTH_M='{self.min_depth_m}'
export OBSTACLE_MAX_DEPTH_M='{self.max_depth_m}'
export OBSTACLE_DEPTH_PERCENTILE='{self.percentile}'
export OBSTACLE_DEPTH_INTERVAL_SEC='{self.publish_interval_sec}'
python3 - <<'PY'
import json
import os
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

topic = os.environ.get('OBSTACLE_DEPTH_TOPIC', '/camera/depth/image_raw')
roi_x_min = float(os.environ.get('OBSTACLE_ROI_X_MIN', '0.35'))
roi_x_max = float(os.environ.get('OBSTACLE_ROI_X_MAX', '0.65'))
roi_y_min = float(os.environ.get('OBSTACLE_ROI_Y_MIN', '0.40'))
roi_y_max = float(os.environ.get('OBSTACLE_ROI_Y_MAX', '0.75'))
min_depth_m = float(os.environ.get('OBSTACLE_MIN_DEPTH_M', '0.15'))
max_depth_m = float(os.environ.get('OBSTACLE_MAX_DEPTH_M', '6.0'))
percentile = float(os.environ.get('OBSTACLE_DEPTH_PERCENTILE', '20.0'))
interval_sec = float(os.environ.get('OBSTACLE_DEPTH_INTERVAL_SEC', '0.20'))

class DepthDistanceNode(Node):
    def __init__(self):
        super().__init__('obstacle_alert_depth_distance')
        self.last_emit = 0.0
        self.create_subscription(Image, topic, self.on_depth, qos_profile_sensor_data)

    def on_depth(self, msg):
        now = time.time()
        if now - self.last_emit < interval_sec:
            return
        self.last_emit = now
        depth_m = None
        valid_count = 0
        try:
            if msg.encoding not in ('16UC1', 'mono16'):
                raise ValueError('unsupported depth encoding: %s' % msg.encoding)
            width = int(msg.width)
            height = int(msg.height)
            x0 = max(0, min(width - 1, int(width * roi_x_min)))
            x1 = max(x0 + 1, min(width, int(width * roi_x_max)))
            y0 = max(0, min(height - 1, int(height * roi_y_min)))
            y1 = max(y0 + 1, min(height, int(height * roi_y_max)))
            pixels = memoryview(msg.data).cast('H')
            values = []
            for y in range(y0, y1):
                row = y * width
                for x in range(x0, x1):
                    raw = pixels[row + x]
                    if raw == 0:
                        continue
                    meters = raw / 1000.0
                    if min_depth_m <= meters <= max_depth_m:
                        values.append(meters)
            valid_count = len(values)
            if values:
                values.sort()
                idx = int((len(values) - 1) * max(0.0, min(100.0, percentile)) / 100.0)
                depth_m = float(values[idx])
            error = None
        except Exception as exc:
            error = repr(exc)
        payload = {{
            'timestamp': now,
            'topic': topic,
            'center_depth_m': depth_m,
            'valid_count': valid_count,
            'width': int(msg.width),
            'height': int(msg.height),
            'encoding': msg.encoding,
            'roi': [roi_x_min, roi_x_max, roi_y_min, roi_y_max],
            'percentile': percentile,
            'error': error,
        }}
        print(json.dumps(payload, ensure_ascii=False), flush=True)

rclpy.init()
node = DepthDistanceNode()
try:
    start_wait = time.time()
    while rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0.2)
        if node.last_emit == 0.0 and time.time() - start_wait > 6.0:
            payload = {{
                'timestamp': time.time(),
                'topic': topic,
                'center_depth_m': None,
                'valid_count': 0,
                'width': 0,
                'height': 0,
                'encoding': '',
                'roi': [roi_x_min, roi_x_max, roi_y_min, roi_y_max],
                'percentile': percentile,
                'error': 'no depth image received within 6s; Astra may be busy or not publishing',
            }}
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            start_wait = time.time()
finally:
    node.destroy_node()
    rclpy.shutdown()
PY
"""

    def start(self) -> None:
        if self.container is None:
            self.container = self.discover_container()
        if not self.container:
            raise RuntimeError("No running Docker container found for ROS2 depth camera")
        cmd = ["docker", "exec", self.container, "bash", "-lc", self._docker_script()]
        self.process = subprocess.Popen(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        self.thread = threading.Thread(target=self._read_loop, name="docker_depth_stream", daemon=True)
        self.thread.start()

    def _read_loop(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if self._stop_event.is_set():
                break
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line)
                sample["docker_container"] = self.container
                if self.on_sample:
                    self.on_sample(sample)
            except json.JSONDecodeError:
                if self.on_error:
                    self.on_error(line)
        if not self._stop_event.is_set() and self.process.poll() is not None:
            stderr = ""
            if self.process.stderr is not None:
                try:
                    stderr = self.process.stderr.read()[-2000:]
                except Exception:
                    stderr = ""
            if self.on_error:
                self.on_error(f"docker depth stream exited with {self.process.returncode}: {stderr}")

    def stop(self) -> None:
        self._stop_event.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.thread is not None:
            self.thread.join(timeout=2)
