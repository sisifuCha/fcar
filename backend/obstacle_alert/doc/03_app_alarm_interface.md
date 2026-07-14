# APP/电脑端报警接口方案

版本：v2

## 1. 架构调整

后续障碍物检测和报警状态生成放在电脑端，不再默认由小车端生成。

```text
小车端：
  6000 控制 TCP
  6500 视频流
  6602 雷达/里程计 WebSocket

电脑端：
  接收 6602 雷达数据
  计算 CLEAR / WARN / DANGER
  显示报警
  后续通过 6000 给小车发送 STOP
```

## 2. 小车端接口

### 2.1 控制端口 6000

作用：小车控制协议。

用途：后续电脑端向小车发送停车或避障控制命令。

注意：需要确认 APP 控制协议的 STOP 帧格式。

### 2.2 视频端口 6500

视频流：

```text
http://<CAR_IP>:6500/video_feed
```

用途：电脑端显示视频，后续做 YOLO/视觉识别。

### 2.3 雷达 WebSocket 端口 6602

雷达流：

```text
ws://<CAR_IP>:6602
```

消息格式参考：

```text
@SCAN{json}#
@ODOM{json}#
```

第一版只使用 `SCAN`。

## 3. 电脑端报警状态格式

电脑端内部统一生成：

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

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `level` | string | `CLEAR`、`WARN`、`DANGER`、`UNKNOWN` |
| `has_obstacle` | bool | 是否需要报警 |
| `distance_m` | number/null | 前方障碍物距离 |
| `source` | string | `lidar_ws_6602`、`vision_6500`、`fusion` |
| `message` | string | 展示文案 |
| `timestamp` | number | 电脑端生成状态时间 |

## 4. 第一版 APP/电脑显示方式

第一版先在电脑端控制台显示：

```text
CLEAR front=2.30m
WARN front=0.76m
DANGER front=0.42m
```

如果需要给 APP 显示，有两种路线：

### 路线 A：电脑端提供 HTTP API

电脑端启动一个小服务：

```text
GET http://<PC_IP>:<PORT>/api/obstacle/status
```

APP 访问电脑端接口显示报警。

优点：不改小车端。

### 路线 B：电脑端直接通知 APP 或小车

电脑端检测到 DANGER 后：

1. 通过 6000 给小车发 STOP；
2. APP 自己从电脑端或小车端获取状态。

## 5. 状态显示建议

| level | 显示行为 |
| --- | --- |
| CLEAR | 绿色/隐藏报警 |
| WARN | 黄色提示：“前方 X 米有障碍物” |
| DANGER | 红色报警：“前方 X 米危险，请停车” |
| UNKNOWN | 灰色提示：“雷达数据未连接” |

## 6. 后续控制动作

第一阶段：

```text
只显示报警，不控车
```

第二阶段：

```text
DANGER -> 电脑端通过 6000 发送 STOP
```

第三阶段：

```text
DANGER -> STOP -> 判断左右空间 -> 发送转向/避障命令
```

## 7. 不再推荐的小车端 6511 接口

之前的小车端 `obstacle_app.py` 提供：

```text
http://<CAR_IP>:6511/api/obstacle/status
```

这个接口保留为调试/备用，但不作为后续主架构。后续主架构由电脑端生成检测状态。
