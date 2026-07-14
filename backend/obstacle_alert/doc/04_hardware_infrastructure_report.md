# 硬件基础设施确认报告

生成时间：2026-07-14

本报告记录当前小车用于“障碍物检测 + APP 报警”的基础设施验证结果。重点确认：**激光雷达、深度相机、普通视频流、底盘串口、网络访问**。

## 1. 结论摘要

| 基础设施 | 当前结论 | 证据/说明 | 对障碍物报警方案的影响 |
| --- | --- | --- | --- |
| 主 APP HTTP 服务 | 可用 | `http://127.0.0.1:6500/` 返回 `200` | APP/浏览器访问基础存在 |
| 主 APP 视频流 | 可用 | `/video_feed` 返回 `200`，类型为 `multipart/x-mixed-replace` | 说明当前已有视频输出链路 |
| 普通 USB 摄像头 `/dev/video0` | 设备存在，但被主 APP 占用 | `fuser` 显示 `/dev/video0` 被 `python3 app.py` 占用 | 单独检测脚本打不开是占用导致，不代表硬件不存在 |
| 深度相机 Astra | 可用 | Docker ROS2 内 `astra_camera list_devices_node` 找到 1 个 Astra，序列号 `ACR38430016` | 后续可用深度图做距离辅助检测 |
| 深度图 topic | 可用 | 启动 `astra_camera astra.launch.xml` 后读到 `/camera/depth/image_raw`，`640x480`，`16UC1` | 可以作为障碍物距离输入之一 |
| 激光雷达设备 | 可用 | `/dev/rplidar -> ttyUSB0`，Docker 内也有 `/dev/rplidar` | 推荐作为第一版障碍物检测主传感器 |
| 激光雷达 ROS2 驱动 | 可用 | Docker 内 `sllidar_ros2` 可启动，雷达健康状态 OK | 可发布 `/scan` |
| `/scan` topic | 可用 | 临时启动 `sllidar_launch.py` 后出现 `/scan` | 可计算前方障碍物距离 |
| 前方距离计算 | 可用 | 临时读取 `/scan` 得到 `front_min_m ≈ 2.696m` | 可做 `CLEAR/WARN/DANGER` 状态判断 |
| 宿主机 ROS2 Python | 不可用 | `check_lidar.py` 报 `No module named 'rclpy'`；宿主机只有 ROS Noetic | ROS2 检测逻辑应在 Docker ROS2 容器内运行，或后续配置宿主机 ROS2 环境 |
| 底盘串口 | 存在 | `/dev/myserial -> ttyUSB1` | 可调用现有 `Rosmaster` 控制蜂鸣器/停车 |
| 蜂鸣器脚本 | dry-run 通过 | `check_beep.py` 默认不执行硬件动作，语法和 dry-run 正常 | 真实蜂鸣需另行确认后加 `--execute` |
| 停车脚本 | dry-run 通过 | `check_motion_stop.py` 默认不执行硬件动作，语法和 dry-run 正常 | 真实停车命令需另行确认后加 `--execute` |
| Jetson IP | 已确认 | `192.168.27.221`，Docker 网桥 `172.17.0.1` | APP 可优先访问 `http://192.168.27.221:6511/...` |

## 2. 摄像头与深度相机验证

### 2.1 普通视频流

验证命令：

```bash
curl --max-time 3 -s -o /dev/null -w 'root_http=%{http_code}\n' http://127.0.0.1:6500/
curl --max-time 3 -s -o /dev/null -w 'video_http=%{http_code}\nvideo_type=%{content_type}\n' http://127.0.0.1:6500/video_feed
```

结果：

```text
root_http=200
video_http=200
video_type=multipart/x-mixed-replace; boundary=frame
```

结论：主 APP 和视频流是可用的。

### 2.2 `/dev/video0` 被主 APP 占用

验证命令：

```bash
fuser -v /dev/video0 /dev/video1
ps -fp <PID>
```

结果显示：

```text
/dev/video0: python3
python3 /home/jetson/Rosmaster-App/rosmaster/app.py
```

结论：之前 `check_camera.py --device 0/1` 打不开摄像头，主要原因是摄像头正在被主 APP 使用。该结果不代表摄像头不可用。

### 2.3 Astra 深度相机设备确认

在 Docker ROS2 容器中验证：

```bash
ros2 run astra_camera list_devices_node
```

结果：

```text
Found 1 devices
Device connected: Astra
URI: 2bc5/060f@1/11
Serial number: ACR38430016
```

结论：深度相机 Astra 存在且能被 ROS2 驱动识别。

### 2.4 深度图 topic 验证

临时启动：

```bash
ros2 launch astra_camera astra.launch.xml
```

可见 topic：

```text
/camera/depth/camera_info
/camera/depth/image_raw
/camera/depth/points
/camera/ir/camera_info
/camera/ir/image_raw
```

读取一帧深度图结果：

```json
{
  "ok": true,
  "topic": "/camera/depth/image_raw",
  "width": 640,
  "height": 480,
  "encoding": "16UC1",
  "step": 1280,
  "data_len": 614400
}
```

结论：深度图可用，后续可以作为视觉距离检测或雷达补充。

## 3. 激光雷达验证

### 3.1 设备节点

验证结果：

```text
/dev/rplidar -> ttyUSB0
/dev/ttyUSB0
```

Docker 容器内也能看到：

```text
/dev/rplidar
```

结论：激光雷达硬件设备节点存在。

### 3.2 ROS2 包与驱动

Docker 容器内可用包包括：

```text
sllidar_ros2
ydlidar_ros2_driver
laser_geometry
icar_laser / yahboomcar_laser
```

短暂启动雷达：

```bash
ros2 launch sllidar_ros2 sllidar_launch.py
```

关键日志：

```text
SLLidar running on ROS2 package SLLidar.ROS2 SDK Version:1.0.1
SLLidar S/N: BDE0ECF0C3E09ED2A0EA98F32E384110
Firmware Ver: 1.29
Hardware Rev: 7
SLLidar health status : OK.
current scan mode: Sensitivity, sample rate: 8 Khz, max_distance: 12.0 m, scan frequency:10.0 Hz
```

结论：雷达驱动可以启动，雷达健康状态正常。

### 3.3 `/scan` 数据

临时启动雷达后 topic 列表出现：

```text
/scan
```

读取一帧并计算前方 `-30° ~ +30°` 扇区最小距离：

```json
{
  "ok": true,
  "front_min_m": 2.696,
  "range_count": 1080,
  "angle_min": -3.1241390705108643,
  "angle_max": 3.1415927410125732,
  "range_min": 0.15000000596046448,
  "range_max": 12.0
}
```

结论：`/scan` 可用，并且可以计算前方距离。第一版障碍物检测推荐基于激光雷达 `/scan`。

## 4. ROS 环境说明

宿主机情况：

- `/opt/ros/noetic` 存在。
- `rostopic` 存在，但 ROS master 当前未运行。
- 宿主机执行 `check_lidar.py` 时缺少 ROS2 Python 包：`No module named 'rclpy'`。

Docker 情况：

- 运行中的 ROS2 Foxy 容器存在。
- 容器内可启动 `sllidar_ros2` 和 `astra_camera`。
- `/scan`、`/camera/depth/image_raw` 均在容器内验证可用。

工程影响：

- 后续雷达/深度相机检测节点应优先设计为在 Docker ROS2 环境内运行。
- 如果要在宿主机直接运行 `obstacle_alert/scripts/check_lidar.py`，需要配置 ROS2 Python 环境或改为通过 Docker 执行。

## 5. 底盘、蜂鸣器与停车接口

### 5.1 底盘串口

设备：

```text
/dev/myserial -> ttyUSB1
```

结论：底盘串口设备存在。

### 5.2 蜂鸣器

已验证脚本 dry-run：

```bash
python3 obstacle_alert/scripts/check_beep.py
```

结果：

```json
{
  "ok": true,
  "executed": false,
  "message": "dry-run only; add --execute to call set_beep(duration) then set_beep(0)"
}
```

结论：脚本安全逻辑正常。尚未执行真实蜂鸣，避免打扰或影响同学使用。

真实验证命令，需明确确认后再执行：

```bash
python3 obstacle_alert/scripts/check_beep.py --execute --duration 60
```

### 5.3 停车接口

已验证脚本 dry-run：

```bash
python3 obstacle_alert/scripts/check_motion_stop.py
```

结果：

```json
{
  "ok": true,
  "executed": false,
  "message": "dry-run only; add --execute to send stop command(s). The script never starts movement."
}
```

结论：脚本安全逻辑正常。尚未执行真实停车命令。

真实验证命令，需确保小车安全后再执行：

```bash
python3 obstacle_alert/scripts/check_motion_stop.py --execute --method both
```

## 6. 第一版检测路线建议

基于当前验证结果，推荐第一版：

```text
Docker ROS2 容器内启动 sllidar_ros2
  -> 订阅 /scan
  -> 计算前方 -30° ~ +30° 最小距离 front_min_m
  -> 判断 CLEAR / WARN / DANGER
  -> 宿主机或 APP 通过 HTTP 读取状态
  -> 后续再接蜂鸣器和停车保护
```

深度相机作为第二优先级：

```text
Astra /camera/depth/image_raw
  -> 读取中心区域深度
  -> 辅助判断低矮/近距离障碍物
  -> 与 /scan 融合
```

普通 RGB 摄像头作为展示/视觉增强：

```text
/video_feed 或 /dev/video0
  -> 后续画框、识别类别、APP 展示
```

## 7. 当前还未完成的验证

| 项目 | 原因 | 后续动作 |
| --- | --- | --- |
| 普通摄像头单独 OpenCV 读取 | `/dev/video0` 被主 APP 占用 | 等同学不用或停止 `app.py` 后再测 |
| 蜂鸣器真实响声 | 避免打扰/硬件动作 | 用户确认后执行 `--execute` |
| 真实停车命令 | 需要确认小车处于安全状态 | 用户确认后执行 `--execute` |
| 放置障碍物距离变化测试 | 需要人工摆放障碍物 | 启动雷达后分别记录远/近 `front_min_m` |

## 8. 最终判断

当前小车基础设施满足第一版障碍物检测方案：

1. 激光雷达可用，且 `/scan` 能发布数据。
2. 深度相机 Astra 可用，能发布深度图。
3. 主 APP 和视频流可用。
4. 底盘串口存在。
5. APP 网络访问地址可用。

因此，后续技术方案应以 **激光雷达 `/scan` 为主、深度相机为辅、RGB/YOLO 为增强**。第一版无需新增模型，也不应先把视频传到电脑做唯一判断。
