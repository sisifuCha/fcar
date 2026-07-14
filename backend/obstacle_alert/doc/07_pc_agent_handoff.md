# PC 端 Agent 对接最小接口文档

用途：给电脑端检测/控制 Agent 对接小车使用。当前架构是：**小车只提供数据和执行控制；电脑端负责检测、报警、停车/避障决策。**

## 1. 小车端服务

小车端先运行：

```bash
python3 app.py
```

小车 IP 示例：

```text
192.168.27.221
```

电脑端需要对接以下端口：

| 端口 | 协议 | 服务 | 作用 |
| --- | --- | --- | --- |
| `6000` | TCP | `app.py` / `rosmaster_main` | 小车控制命令，电脑端后续发送 STOP/运动指令 |
| `6500` | HTTP MJPEG | `app.py` | 视频流 `/video_feed` |
| `6602` | WebSocket | `mapping/car/sensor_relay.py` | 雷达 `/scan`、里程计 `/odom` 数据 |

> 注意：6000 控制端口通常只适合一个控制端连接。电脑端控制时，不建议同时用手机 APP 控车。

---

## 2. 视频数据：6500

### URL

```text
http://<CAR_IP>:6500/video_feed
```

示例：

```text
http://192.168.27.221:6500/video_feed
```

### 数据格式

MJPEG HTTP 流：

```text
Content-Type: multipart/x-mixed-replace; boundary=frame
```

### 电脑端用途

- 显示实时画面；
- 后续做 YOLO/视觉检测；
- 第一版障碍物安全判断不依赖视频，优先用 6602 雷达。

---

## 3. 雷达/里程计数据：6602

### URL

```text
ws://<CAR_IP>:6602
```

示例：

```text
ws://192.168.27.221:6602
```

### 帧格式

WebSocket 文本帧，用 `@` 开头，`#` 结尾：

```text
@SCAN{json}#
@ODOM{json}#
```

### `@SCAN` 示例

```text
@SCAN{"ranges":[...],"angle_min":-3.14,"angle_max":3.14,"angle_increment":0.017,"range_min":0.15,"range_max":12.0,"t":1710000000.0}#
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ranges` | float[] | 雷达距离，单位米；无效点可能是 `0` |
| `angle_min` | float | 起始角，弧度 |
| `angle_max` | float | 结束角，弧度 |
| `angle_increment` | float | 每个点的角度增量，弧度 |
| `range_min` | float | 雷达最小有效距离 |
| `range_max` | float | 雷达最大有效距离 |
| `t` | float | Unix 时间戳 |

### `@ODOM` 示例

```text
@ODOM{"x":0.1,"y":0.2,"theta":0.0,"vx":0,"vy":0,"t":1710000000.0}#
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `x`, `y` | float | 里程计位置，米 |
| `theta` | float | 航向角，弧度 |
| `vx`, `vy` | float | 线速度 |
| `t` | float | Unix 时间戳 |

### 第一版雷达检测算法

电脑端解析 `@SCAN` 后：

```text
front sector = -30° ~ +30°
front_min_m = 前方扇区内有效 ranges 的最小值
```

有效点：

```text
range_min < r < min(range_max, 8.0)
```

状态阈值：

```text
CLEAR:  front_min_m >= 0.90m 或没有有效近距离点
WARN:   0.50m <= front_min_m < 0.90m
DANGER: front_min_m < 0.50m
```

建议去抖：

```text
连续 2 帧 WARN 才进入 WARN
连续 2 帧 DANGER 才进入 DANGER
连续 5 帧 CLEAR 才恢复 CLEAR
```

---

## 4. 小车控制：6000

### 连接

```text
TCP <CAR_IP>:6000
```

示例：

```python
import socket
s = socket.socket()
s.connect(("192.168.27.221", 6000))
s.send(b"$0110060000B5#")  # STOP 示例
s.close()
```

### 帧格式

```text
$ + car_type + cmd + len + payload + checksum + #
```

所有字段都是大写十六进制字符串。

```text
$ CCTTLL PAYLOAD XX #
```

| 字段 | 长度 | 说明 |
| --- | --- | --- |
| `$` | 1 char | 起始符 |
| `CC` | 1 byte | 小车类型，常用 `01` |
| `TT` | 1 byte | 命令字 |
| `LL` | 1 byte | 长度字段；按现有协议为 `payload_hex_len + 2` |
| `PAYLOAD` | N bytes | 命令数据 |
| `XX` | 1 byte | 校验和 |
| `#` | 1 char | 结束符 |

### 校验和

源码校验逻辑等价于：

```python
checksum = (0x9E + sum([car_type, cmd, length] + payload_bytes)) & 0xFF
```

### 组帧函数

```python
def build_frame(car_type, cmd, payload):
    length = len(payload) * 2 + 2
    body = [car_type, cmd, length] + payload
    checksum = (0x9E + sum(body)) & 0xFF
    return "$" + "".join(f"{b:02X}" for b in body) + f"{checksum:02X}#"
```

---

## 5. 运动控制命令 `cmd=0x10`

### Payload

```text
payload = [num_x, num_y]
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `num_x` | signed int8 | 横向控制，源码中 `speed_y = -num_x / 100.0` |
| `num_y` | signed int8 | 前后控制，源码中 `speed_x = num_y / 100.0` |

signed int8 编码：

```python
def s8(v):
    return v & 0xFF
```

### STOP 帧

停止：

```python
build_frame(0x01, 0x10, [0x00, 0x00])
```

结果：

```text
$0110060000B5#
```

电脑端检测到 `DANGER` 后，第一版建议只发送这个 STOP 帧。

### 前进示例

前进强度 `30`：

```python
build_frame(0x01, 0x10, [0x00, 0x1E])
```

结果：

```text
$011006001ED3#
```

> 注意：运动方向和速度建议先低速实测。第一版对接 Agent 只需要 STOP。

---

## 6. 可选状态查询帧

已有测试脚本中验证过的查询帧：

| 功能 | 帧 |
| --- | --- |
| 电池电压 | `$01020400A5#` |
| IMU | `$01020300A4#` |
| 编码器 | `$01020500A6#` |

示例：

```python
s.send(b"$01020400A5#")
resp = s.recv(256)
```

---

## 7. PC Agent 第一版任务

电脑端 Agent 第一版只需要实现：

```text
1. 连接 ws://<CAR_IP>:6602
2. 解析 @SCAN{json}#
3. 计算 front_min_m
4. 输出 CLEAR / WARN / DANGER
5. DANGER 时发送 TCP 6000 STOP 帧：$0110060000B5#
```

建议第一版先只打印，不控车：

```text
DANGER front=0.42m -> would_send_stop=True
```

确认稳定后再真正发送 STOP。

---

## 8. 最小 Python 伪代码

```python
import asyncio, json, math, socket, websockets

CAR_IP = "192.168.27.221"

STOP_FRAME = b"$0110060000B5#"


def front_min(scan, deg_min=-30, deg_max=30):
    lo = math.radians(deg_min)
    hi = math.radians(deg_max)
    angle = scan["angle_min"]
    best = None
    max_range = min(scan.get("range_max", 8.0), 8.0)
    range_min = scan.get("range_min", 0.0)
    for r in scan["ranges"]:
        if range_min < r < max_range and lo <= angle <= hi:
            best = r if best is None else min(best, r)
        angle += scan["angle_increment"]
    return best


def send_stop():
    s = socket.socket()
    s.settimeout(1)
    s.connect((CAR_IP, 6000))
    s.send(STOP_FRAME)
    s.close()


async def main():
    uri = f"ws://{CAR_IP}:6602"
    async with websockets.connect(uri) as ws:
        async for msg in ws:
            if not (msg.startswith("@SCAN") and msg.endswith("#")):
                continue
            scan = json.loads(msg[len("@SCAN"):-1])
            d = front_min(scan)
            if d is not None and d < 0.5:
                print("DANGER", d)
                # send_stop()  # 稳定后再打开
            elif d is not None and d < 0.9:
                print("WARN", d)
            else:
                print("CLEAR", d)

asyncio.run(main())
```
