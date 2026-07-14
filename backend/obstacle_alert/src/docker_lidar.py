#!/usr/bin/env python3
"""Stream front lidar distance from a ROS2 Docker container."""

import json
import subprocess
import threading
import time
from typing import Callable, Optional


DEFAULT_SETUP_FILES = (
    "/opt/ros/foxy/setup.bash",
    "/root/icar_ros2_ws/software/library_ws/install/setup.bash",
    "/root/icar_ros2_ws/icar_ws/install/setup.bash",
    "/root/yahboomcar_ros2_ws/software/library_ws/install/setup.bash",
    "/root/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash",
)


class DockerLidarStream:
    """Runs ROS2 lidar reading inside Docker and emits JSON samples."""

    def __init__(
        self,
        container: Optional[str] = None,
        topic: str = "/scan",
        front_min_deg: float = -30.0,
        front_max_deg: float = 30.0,
        max_range_m: float = 8.0,
        publish_interval_sec: float = 0.1,
        start_lidar: bool = True,
        on_sample: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.container = container
        self.topic = topic
        self.front_min_deg = front_min_deg
        self.front_max_deg = front_max_deg
        self.max_range_m = max_range_m
        self.publish_interval_sec = publish_interval_sec
        self.start_lidar = start_lidar
        self.on_sample = on_sample
        self.on_error = on_error
        self.process: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @staticmethod
    def _run(cmd, timeout=8) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)

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
                cls._source_prefix() + " ros2 pkg list | grep -q '^sllidar_ros2$'",
            ], timeout=8)
            if check.returncode == 0:
                return name
        return names[0] if names else None

    @staticmethod
    def _source_prefix() -> str:
        parts = []
        for setup in DEFAULT_SETUP_FILES:
            parts.append(f'[ -f "{setup}" ] && source "{setup}";')
        return " ".join(parts)

    def _docker_script(self) -> str:
        source_prefix = self._source_prefix()
        start_lidar = "1" if self.start_lidar else "0"
        return f"""
set -e
{source_prefix}
LIDAR_PID=""
cleanup() {{
  if [ -n "$LIDAR_PID" ]; then
    kill "$LIDAR_PID" 2>/dev/null || true
    wait "$LIDAR_PID" 2>/dev/null || true
  fi
}}
trap cleanup EXIT INT TERM
if [ "{start_lidar}" = "1" ]; then
  if ! ros2 topic list 2>/dev/null | grep -qx "{self.topic}"; then
    ros2 launch sllidar_ros2 sllidar_launch.py >/tmp/obstacle_alert_sllidar.log 2>&1 &
    LIDAR_PID=$!
    sleep 3
  fi
fi
export OBSTACLE_TOPIC='{self.topic}'
export OBSTACLE_FRONT_MIN_DEG='{self.front_min_deg}'
export OBSTACLE_FRONT_MAX_DEG='{self.front_max_deg}'
export OBSTACLE_MAX_RANGE_M='{self.max_range_m}'
export OBSTACLE_INTERVAL_SEC='{self.publish_interval_sec}'
python3 - <<'PY'
import json
import math
import os
import time
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan

topic = os.environ.get('OBSTACLE_TOPIC', '/scan')
front_min_deg = float(os.environ.get('OBSTACLE_FRONT_MIN_DEG', '-30'))
front_max_deg = float(os.environ.get('OBSTACLE_FRONT_MAX_DEG', '30'))
max_range_m = float(os.environ.get('OBSTACLE_MAX_RANGE_M', '8.0'))
interval_sec = float(os.environ.get('OBSTACLE_INTERVAL_SEC', '0.1'))

lo = math.radians(min(front_min_deg, front_max_deg))
hi = math.radians(max(front_min_deg, front_max_deg))

class FrontDistanceNode(Node):
    def __init__(self):
        super().__init__('obstacle_alert_front_distance')
        self.last_emit = 0.0
        self.create_subscription(LaserScan, topic, self.on_scan, 10)

    def on_scan(self, scan):
        now = time.time()
        if now - self.last_emit < interval_sec:
            return
        self.last_emit = now
        best = None
        angle = scan.angle_min
        upper = min(scan.range_max, max_range_m)
        for distance in scan.ranges:
            if scan.range_min < distance < upper and lo <= angle <= hi:
                if best is None or distance < best:
                    best = float(distance)
            angle += scan.angle_increment
        payload = {{
            'timestamp': now,
            'topic': topic,
            'front_min_m': best,
            'range_count': len(scan.ranges),
            'angle_min': float(scan.angle_min),
            'angle_max': float(scan.angle_max),
            'range_min': float(scan.range_min),
            'range_max': float(scan.range_max),
        }}
        print(json.dumps(payload, ensure_ascii=False), flush=True)

rclpy.init()
node = FrontDistanceNode()
try:
    while rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0.2)
finally:
    node.destroy_node()
    rclpy.shutdown()
PY
"""

    def start(self) -> None:
        if self.container is None:
            self.container = self.discover_container()
        if not self.container:
            raise RuntimeError("No running Docker container found for ROS2 lidar")
        cmd = ["docker", "exec", self.container, "bash", "-lc", self._docker_script()]
        self.process = subprocess.Popen(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        self.thread = threading.Thread(target=self._read_loop, name="docker_lidar_stream", daemon=True)
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
                self.on_error(f"docker lidar stream exited with {self.process.returncode}: {stderr}")

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
