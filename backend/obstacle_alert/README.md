# Obstacle Alert

本目录用于隔离小车障碍物识别与 APP 报警相关内容，避免直接修改现有主服务 `app.py`、编译模块 `rosmaster_main` 或手机 APP TCP 控制链路。

## 当前主架构

后续主线已调整为：

```text
小车端只负责数据传输和控制通道：
  - 6000：小车控制 TCP 协议
  - 6500：app.py HTTP 与 /video_feed 视频流
  - 6602：雷达 /scan 与 /odom WebSocket 数据

电脑端负责所有检测和处理逻辑：
  - 连接 6602 获取雷达数据
  - 可选连接 6500 获取视频流
  - 计算 CLEAR / WARN / DANGER
  - 后续通过 6000 给小车发送 STOP / 避障指令
```

主架构文档：

```text
doc/06_pc_side_architecture.md
```

技术方案文档：

```text
doc/02_detection_technical方案.md
```

APP/报警接口文档：

```text
doc/03_app_alarm_interface.md
```

## 目录结构

```text
obstacle_alert/
  doc/
    01_hardware_check.md              # 硬件基础设施验证步骤
    02_detection_technical方案.md      # 电脑端检测技术路线
    03_app_alarm_interface.md          # APP/电脑端报警接口方案
    04_hardware_infrastructure_report.md
    05_lidar_alarm_api.md              # 小车端检测旧方案/备用说明
    06_pc_side_architecture.md         # 当前主架构：电脑端处理
  scripts/
    check_camera.py
    check_lidar.py
    check_beep.py
    check_motion_stop.py
    check_cmd.py
  src/
    小车端检测 fallback/参考实现
```

## 小车端启动

小车端运行主 APP：

```bash
python3 app.py
```

电脑端可使用：

```text
http://<CAR_IP>:6500/video_feed
ws://<CAR_IP>:6602
<CAR_IP>:6000
```

## 第一版电脑端目标

第一版要做：

```text
电脑端连接 ws://<CAR_IP>:6602
  -> 接收 @SCAN{json}#
  -> 计算前方 -30° ~ +30° 最近距离
  -> 输出 CLEAR / WARN / DANGER
```

后续再做：

```text
DANGER -> 通过 6000 发送 STOP
再后续 -> 根据左右扇区做避障
```

## 小车端旧检测服务说明

已有小车端检测服务：

```bash
python3 obstacle_alert/obstacle_app.py
```

现在只作为：

1. 硬件验证工具；
2. 断网 fallback 原型；
3. 电脑端算法参考；
4. 不作为后续主路线。

旧接口说明见：

```text
doc/05_lidar_alarm_api.md
```

## 安全说明

- `check_beep.py` 和 `check_motion_stop.py` 默认都是 dry-run，不会操作硬件。
- 只有显式添加 `--execute` 才会发送硬件命令。
- 后续电脑端发送 STOP 前，需要先确认 6000 控制协议帧格式。
