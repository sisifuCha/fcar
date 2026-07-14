# 电脑端障碍物检测与处理架构

版本：v2

## 1. 架构调整结论

后续障碍物检测与处理逻辑调整为：

```text
小车端只负责：
  1. 采集并传输数据
  2. 提供视频流、雷达流、APP 控制通道
  3. 接收电脑端或 APP 发送的控制/报警指令

电脑端负责：
  1. 接收小车数据
  2. 执行障碍物检测、融合、判断
  3. 决定 WARN / DANGER / STOP / 后续避障策略
  4. 给小车发送控制命令或给 APP 显示报警
```

也就是说：**小车不再作为主要算法处理端**。小车端已有的 `obstacle_app.py`、`docker_lidar.py`、`docker_depth.py` 保留为硬件验证/备用方案，但不作为后续主路线。

## 2. 小车端数据通道

当前已确认或约定的小车端端口：

| 端口 | 来源 | 作用 | 电脑端用途 |
| --- | --- | --- | --- |
| `6000` | `app.py` / `rosmaster_main` TCP | 手机 APP 控制协议，小车接收控制命令 | 后续电脑端可复用或模拟 APP 给小车发控制命令 |
| `6500` | `app.py` Flask HTTP | Web 页面和 `/video_feed` 视频流 | 电脑端可读取 RGB 视频流用于显示或视觉识别 |
| `6602` | `mapping/car/sensor_relay.py` WebSocket | 雷达 `/scan`、里程计 `/odom` 数据转发 | 电脑端接收雷达数据，做障碍物距离检测 |

主启动方式：

```bash
python3 app.py
```

启动后：

```text
http://<CAR_IP>:6500/video_feed
```

提供视频流。

如果需要雷达 WebSocket 数据，需要启动或确认 `mapping/car/sensor_relay.py` 对应服务，默认端口按现有配置约定为 `6602`。

## 3. 电脑端主处理流程

推荐电脑端程序结构：

```text
PC obstacle client
  ├── 连接小车视频流：http://<CAR_IP>:6500/video_feed
  ├── 连接雷达 WebSocket：ws://<CAR_IP>:6602
  ├── 解析 @SCAN{json}# 数据
  ├── 计算前方障碍物距离 front_min_m
  ├── 可选读取视频帧做视觉识别
  ├── 输出 CLEAR / WARN / DANGER
  ├── APP/控制台显示报警
  └── 必要时通过 6000 端口给小车发送 STOP 指令
```

第一版电脑端检测只建议使用雷达：

```text
ws://<CAR_IP>:6602
  -> @SCAN{json}#
  -> 解析 ranges / angle_min / angle_increment
  -> 计算 -30° ~ +30° front_min_m
  -> CLEAR / WARN / DANGER
```

第二版再加入视频/深度/视觉模型。

## 4. 为什么改为电脑端处理

优点：

1. 电脑算力更强，后续更适合跑 YOLO、深度学习、多传感器融合。
2. 不再抢占小车端 `app.py` 的串口和摄像头资源。
3. 小车端保持稳定，职责简单：传数据和执行控制。
4. 电脑端调试更方便，可记录雷达、视频、检测结果。
5. 后续避障算法可以在电脑端快速迭代。

缺点和注意事项：

1. 依赖网络稳定性。
2. 紧急停车链路变成：小车 -> 电脑判断 -> 小车执行，有延迟。
3. 需要给控制命令设计可靠通道。
4. 如果电脑端程序断开，小车端不会自动具备检测保护，除非保留小车端 fallback。

因此建议：

```text
第一版电脑端处理为主；
小车端保留最小安全 fallback 作为后续可选项。
```

## 5. 第一版电脑端检测逻辑

### 5.1 输入

优先输入：

```text
ws://<CAR_IP>:6602
```

假设消息格式参考 `mapping/car/sensor_relay.py`：

```text
@SCAN{json}#
@ODOM{json}#
```

电脑端第一版只需要 `SCAN`。

### 5.2 前方扇区

推荐先使用：

```text
front sector = -30° ~ +30°
```

计算：

```text
front_min_m = 前方扇区有效 ranges 最小值
```

有效值规则：

```text
range_min < r < min(range_max, 8.0)
```

### 5.3 状态判断

默认阈值：

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

### 5.4 输出

电脑端输出统一状态：

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

## 6. 控制命令策略

### 6.1 第一阶段：只报警不控车

先让电脑端：

```text
接收雷达数据
显示 CLEAR/WARN/DANGER
控制台打印报警
```

不立即发送小车控制命令。

### 6.2 第二阶段：DANGER 发 STOP

当检测稳定后，电脑端通过小车已有控制通道发停车命令。

优先考虑复用：

```text
TCP 6000 APP 控制协议
```

需要确认 STOP 帧格式。参考 `rosmaster_main_ori.py` 中 `parse_data()` 对命令 `10`、停止动作的处理逻辑。

如果不想直接拼 TCP 协议，第二种方案是在小车端单独增加一个极小 HTTP/Socket 控制服务，但这会改变小车端代码，需另行确认。

### 6.3 后续避障

后续可以从 `@SCAN` 同时计算：

```text
front_min_m
left_min_m
right_min_m
```

策略：

```text
DANGER:
  1. STOP
  2. 比较 left/right 空旷度
  3. 选择更空的一侧转向
  4. 再继续前进
```

这部分全部在电脑端做决策。

## 7. 视频/视觉模型路线

电脑端可以读取：

```text
http://<CAR_IP>:6500/video_feed
```

后续用途：

1. 显示实时画面。
2. 用 OpenCV/YOLO 识别障碍物类别。
3. 在电脑端 UI 上叠加检测框和雷达距离。
4. 用于数据采集和模型训练。

第一版不建议依赖视频做安全判断，原因：

- 单目视频估距不稳定。
- 视频延迟高于雷达 WebSocket。
- 当前目标首先是“距离危险报警”。

推荐顺序：

```text
第一版：6602 雷达距离检测
第二版：6500 视频显示/录制
第三版：电脑端 YOLO 分类识别
第四版：雷达 + YOLO + 控制策略融合
```

## 8. 小车端保留内容

当前已写的小车端内容保留在：

```text
obstacle_alert/obstacle_app.py
obstacle_alert/src/docker_lidar.py
obstacle_alert/src/docker_depth.py
obstacle_alert/src/detector.py
```

这些不再作为主路线，但仍有价值：

1. 作为硬件验证工具。
2. 作为断网时的小车端 fallback 原型。
3. 作为电脑端算法的参考实现。

后续主线新增内容建议放在：

```text
obstacle_alert/pc_client/
  pc_obstacle_client.py
  lidar_ws_client.py
  app_control_client.py
  vision_stream_client.py
```

## 9. 第一版实施计划

### Step 1：确认小车端数据服务

小车端运行：

```bash
python3 app.py
```

确认：

```text
http://<CAR_IP>:6500/video_feed
```

雷达数据服务确认：

```text
ws://<CAR_IP>:6602
```

### Step 2：电脑端连接 6602

电脑端写 WebSocket 客户端：

```text
连接 ws://<CAR_IP>:6602
接收 @SCAN{json}#
解析 ranges
计算 front_min_m
```

### Step 3：电脑端输出报警

控制台显示：

```text
CLEAR front=2.3m
WARN front=0.7m
DANGER front=0.4m
```

### Step 4：确认 TCP 6000 控制协议

分析或实测 APP 停车帧格式，确认电脑端如何发送 STOP。

### Step 5：电脑端发送 STOP

当 DANGER 稳定后：

```text
向 <CAR_IP>:6000 发送 STOP 控制帧
```

### Step 6：扩展避障

增加左右扇区，设计绕障策略。

## 10. 当前推荐结论

后续主架构采用：

```text
小车端：app.py 提供 6000 控制、6500 视频；sensor_relay 提供 6602 雷达/里程计数据
电脑端：全部检测、融合、报警、停车/避障决策
```

第一版优先做：

```text
电脑端连接 6602 -> 雷达前方距离检测 -> 控制台/APP 报警
```

随后再接：

```text
电脑端通过 6000 给小车发送 STOP
```
