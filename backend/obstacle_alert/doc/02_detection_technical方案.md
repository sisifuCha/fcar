# 障碍物检测技术方案（电脑端处理版）

版本：v2

> 重要调整：后续检测和处理逻辑全部放到电脑端执行。小车端只负责传输数据、提供视频/雷达/控制通道。旧的小车端检测服务保留为硬件验证和 fallback 原型，不再作为主架构。

## 1. 总体推荐

当前推荐架构：

```text
小车端：数据采集与转发
  ├── 6000：手机 APP / 控制 TCP 协议
  ├── 6500：app.py HTTP + /video_feed 视频流
  └── 6602：雷达 /scan 与 /odom WebSocket 数据转发

电脑端：检测、融合、报警、停车/避障决策
  ├── 连接 6602 获取雷达数据
  ├── 可选连接 6500 获取视频流
  ├── 计算障碍物距离
  ├── 输出 CLEAR / WARN / DANGER
  └── 后续通过 6000 给小车发送 STOP 或避障控制命令
```

第一版优先级：

```text
电脑端 6602 雷达距离检测 > 电脑端 6500 视频显示/视觉识别 > 新增/训练模型
```

## 2. 为什么改为电脑端处理

优点：

1. 电脑算力更强，后续更适合跑 YOLO、深度学习和复杂融合。
2. 小车端保持稳定，不抢 `app.py` 的摄像头和底盘串口。
3. 调试更方便，可以在电脑端记录雷达、视频、检测结果和控制决策。
4. 后续避障策略可以在电脑端快速迭代。
5. 小车端只需要运行已有服务，降低对车端代码的侵入。

注意：

1. 电脑端处理依赖网络稳定性。
2. 紧急停车链路会经过网络，有延迟。
3. 后续如果做安全保护，建议保留车端最小 fallback。

## 3. 小车端已有数据接口

| 端口 | 服务 | 数据/功能 | 电脑端使用方式 |
| --- | --- | --- | --- |
| `6000` | `app.py` / `rosmaster_main` TCP | 小车控制协议 | 后续电脑端发送 STOP 或控制指令 |
| `6500` | `app.py` Flask | `/video_feed` 视频流 | 电脑端显示/视觉检测 |
| `6602` | `mapping/car/sensor_relay.py` WebSocket | `/scan`、`/odom` | 电脑端雷达障碍物检测 |

小车端主服务：

```bash
python3 app.py
```

视频流：

```text
http://<CAR_IP>:6500/video_feed
```

雷达 WebSocket：

```text
ws://<CAR_IP>:6602
```

## 4. 第一版检测方案：电脑端雷达检测

### 4.1 输入

电脑端连接：

```text
ws://<CAR_IP>:6602
```

接收消息：

```text
@SCAN{json}#
@ODOM{json}#
```

第一版只使用 `SCAN`。

### 4.2 算法

计算前方扇区：

```text
-30° ~ +30°
```

得到：

```text
front_min_m
```

状态阈值：

```text
CLEAR:  front_min_m >= 0.90m 或无有效危险点
WARN:   0.50m <= front_min_m < 0.90m
DANGER: front_min_m < 0.50m
```

去抖策略：

```text
连续 2 帧 WARN 才进入 WARN
连续 2 帧 DANGER 才进入 DANGER
连续 5 帧 CLEAR 才恢复 CLEAR
```

### 4.3 输出

电脑端输出：

```json
{
  "level": "DANGER",
  "has_obstacle": true,
  "distance_m": 0.42,
  "source": "lidar_ws_6602",
  "message": "前方 0.42m 检测到障碍物",
  "timestamp": 1720000000.0
}
```

第一阶段先只在电脑控制台显示，不立即控车。

## 5. 第二阶段：电脑端发送 STOP

当第一版雷达检测稳定后，电脑端通过小车控制通道发送停止命令。

优先通道：

```text
<CAR_IP>:6000
```

需要确认 `rosmaster_main_ori.py` 中 APP 控车协议的 STOP 帧格式。

目标：

```text
DANGER 稳定出现
  -> 电脑端发送 STOP
  -> 小车停止
```

## 6. 第三阶段：视频和模型增强

电脑端可以读取：

```text
http://<CAR_IP>:6500/video_feed
```

用途：

1. 显示实时视频。
2. 电脑端运行 YOLO 识别人、箱子、椅子等类别。
3. 将 YOLO 检测框和雷达距离叠加显示。
4. 记录数据，后续训练专用模型。

是否需要新增模型：

```text
第一版不需要新增模型。
```

只有当需要识别特定类别，且通用模型效果不够时，再考虑采集数据训练模型。

## 7. 第四阶段：电脑端避障

后续避障不在小车端做主决策，而是在电脑端做：

```text
读取 SCAN
  -> 计算 front / left / right 扇区距离
  -> front DANGER 时 STOP
  -> 选择 left/right 更空的一侧
  -> 通过 6000 发送转向或移动指令
```

可扩展输出：

```json
{
  "level": "DANGER",
  "sectors": {
    "front": 0.38,
    "left": 1.2,
    "right": 0.9
  },
  "suggested_action": "turn_left"
}
```

## 8. 旧小车端检测代码定位

已写的小车端检测代码：

```text
obstacle_alert/obstacle_app.py
obstacle_alert/src/docker_lidar.py
obstacle_alert/src/docker_depth.py
obstacle_alert/src/detector.py
obstacle_alert/src/hardware.py
```

这些代码后续作为：

1. 硬件验证工具；
2. 车端 fallback 原型；
3. 电脑端算法参考；
4. 不作为主技术路线继续扩展。

## 9. 新增电脑端代码建议目录

后续建议新增：

```text
obstacle_alert/pc_client/
  __init__.py
  lidar_ws_client.py
  pc_obstacle_client.py
  app_control_client.py
  vision_stream_client.py
```

职责：

- `lidar_ws_client.py`：连接 6602，解析 `@SCAN{json}#`。
- `pc_obstacle_client.py`：计算障碍物状态。
- `app_control_client.py`：通过 6000 给小车发 STOP/控制命令。
- `vision_stream_client.py`：读取 6500 视频流，后续做视觉增强。

## 10. 当前最终结论

后续主线按这个实现：

```text
小车端 run app.py，负责 6000/6500；雷达通过 6602 发数据
电脑端连接 6602 做雷达障碍物检测
电脑端后续连接 6000 发送 STOP / 避障控制
电脑端可选读取 6500 视频做视觉增强
```

第一版先做：

```text
电脑端连接 6602 -> 解析 SCAN -> 输出 CLEAR/WARN/DANGER
```
