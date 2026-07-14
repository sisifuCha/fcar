# 阶段 1：硬件基础设施验证

本阶段目标是确认小车当前是否具备“障碍物检测 → 本地报警/停车 → APP 展示”的基础条件。这里不做算法闭环，只验证输入、输出和网络链路。

> 建议顺序：先验证摄像头和雷达，再验证蜂鸣器和停车接口。蜂鸣器、停车属于物理动作，执行前请确认小车处于安全状态。

## 1. 验证记录总表

| 项目 | 是否通过 | 实际结果记录 | 备注 |
| --- | --- | --- | --- |
| 摄像头 `/video_feed` | 待验证 |  | 访问 `http://<Jetson_IP>:6500/video_feed` |
| 深度摄像头 `/dev/camera_depth` | 待验证 |  | `video_id=0x50` |
| USB 摄像头 `/dev/camera_usb` | 待验证 |  | `video_id=0x51` |
| 广角摄像头 `/dev/camera_wide_angle` | 待验证 |  | `video_id=0x52` |
| ROS2 命令可用 | 待验证 |  | `ros2 topic list` |
| 雷达 `/scan` 存在 | 待验证 |  | 需要 ROS2/雷达启动 |
| 前方距离可随障碍物变化 | 待验证 |  | `-30° ~ +30°` 扇区 |
| 蜂鸣器可响 | 待验证 |  | `set_beep(60)` |
| 停车命令可发送 | 待验证 |  | `set_car_motion(0,0,0)` |
| APP/电脑可访问 Jetson | 待验证 |  | 6500 或后续 6511 |

## 2. 摄像头验证

### 2.1 验证主 APP 视频流

如果主服务未启动，可在项目根目录运行：

```bash
python3 app.py
```

然后在手机或电脑浏览器访问：

```text
http://<Jetson_IP>:6500/video_feed
```

预期：能看到实时 MJPEG 视频流。

注意：如果主服务正在占用摄像头，后面的单独摄像头脚本可能打开失败，这是正常现象，需要停止主服务后再测单独设备。

### 2.2 验证单个摄像头设备

脚本：

```bash
python3 obstacle_alert/scripts/check_camera.py --device all --frames 10
```

也可以指定单个设备：

```bash
python3 obstacle_alert/scripts/check_camera.py --device depth
python3 obstacle_alert/scripts/check_camera.py --device usb
python3 obstacle_alert/scripts/check_camera.py --device wide
python3 obstacle_alert/scripts/check_camera.py --device 0
```

输出关注：

- `opened: true/false`
- `frame_ok: true/false`
- `width` / `height`
- `fps_estimate`
- `error`

通过标准：至少一个摄像头设备可打开且能读取有效图像帧。

## 3. 雷达 / ROS2 `/scan` 验证

### 3.1 检查 ROS2 topic

```bash
ros2 topic list
```

预期：能看到 `/scan`。如果没有 `/scan`，需要先启动雷达相关服务或 Docker/ROS2 功能。

项目内已有参考：

- `server.py` 中 `/obstacle_avoidance` 会启动 ROS2 雷达避障。
- `auto_mapping/wall_distance_controller.py` 已有前方扇区距离计算逻辑。
- `mapping/car/sensor_relay.py` 已有 `/scan` 转 WebSocket 的实现。

### 3.2 读取前方扇区距离

```bash
python3 obstacle_alert/scripts/check_lidar.py --topic /scan --timeout 5
```

可选调整前方角度：

```bash
python3 obstacle_alert/scripts/check_lidar.py --front-min-deg -30 --front-max-deg 30
```

验证动作：

1. 前方 1m 以内无遮挡，运行脚本记录 `front_min_m`。
2. 在小车正前方 0.4m ~ 0.8m 放置障碍物，再运行脚本。
3. 对比两次 `front_min_m` 是否明显变小。

通过标准：`/scan` 有有效数据，且前方障碍物会让 `front_min_m` 明显下降。

## 4. 蜂鸣器验证

蜂鸣器是物理动作，默认脚本不会执行，必须显式加 `--execute`。

先做 dry-run：

```bash
python3 obstacle_alert/scripts/check_beep.py
```

确认后执行短促蜂鸣：

```bash
python3 obstacle_alert/scripts/check_beep.py --execute --duration 60
```

预期：蜂鸣器短响，随后脚本发送 `set_beep(0)` 关闭。

通过标准：蜂鸣器能响，且能关闭。

## 5. 停车接口验证

停车验证只发送停止命令，不会让小车自动运动。执行前仍建议：

- 小车轮子悬空，或放在安全区域。
- 附近无人、无遮挡危险。

先做 dry-run：

```bash
python3 obstacle_alert/scripts/check_motion_stop.py
```

确认后发送停车命令：

```bash
python3 obstacle_alert/scripts/check_motion_stop.py --execute --method both
```

可选只测试一种：

```bash
python3 obstacle_alert/scripts/check_motion_stop.py --execute --method motion
python3 obstacle_alert/scripts/check_motion_stop.py --execute --method run
```

通过标准：脚本无异常，串口命令发送成功；如果小车处于运动状态，应停止。

## 6. APP / 网络基础验证

### 6.1 获取 Jetson IP

```bash
hostname -I
```

### 6.2 验证主服务访问

```text
http://<Jetson_IP>:6500/
http://<Jetson_IP>:6500/video_feed
```

通过标准：手机或电脑与 Jetson 在同一网络下，可以访问主页面和视频流。

### 6.3 后续报警服务端口建议

后续独立障碍物服务建议使用：

```text
http://<Jetson_IP>:6511/api/obstacle/status
```

这样第一版不会影响现有 6500 主服务和 6000 手机 TCP 控制协议。

## 7. 阶段 1 结论填写

完成验证后填写：

```text
摄像头可用情况：
- depth: 
- usb: 
- wide: 
- 推荐使用：

雷达 /scan：
- 是否存在：
- front_min_m 是否稳定：
- 推荐是否使用雷达作为第一版：

蜂鸣器：
- 是否可用：

停车命令：
- set_car_motion(0,0,0) 是否可用：
- set_car_run(0,0) 是否可用：

APP/网络：
- 手机能否访问 6500：
- 后续 6511 是否可用：

第一版推荐路线：
- [ ] 雷达检测
- [ ] 视觉检测
- [ ] 雷达 + 视觉融合
```
