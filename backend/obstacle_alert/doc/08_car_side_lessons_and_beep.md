# 小车侧检测尝试记录与蜂鸣器控制接口

用途：给后续 PC 端/前端 Agent 了解之前小车侧检测逻辑、踩坑点，以及如何单独控制蜂鸣器。

## 1. 之前小车侧检测逻辑

之前在小车端实现过一个原型：

```text
obstacle_alert/obstacle_app.py
```

逻辑是：

```text
Docker ROS2 容器内读取 /scan
  -> 计算前方 -30° ~ +30° 最近距离 front_min_m
  -> CLEAR / WARN / DANGER 状态机
  -> DANGER 时蜂鸣器报警
  -> 可选发送停车命令
  -> 通过 6511 HTTP 接口输出状态
```

默认阈值：

```text
WARN:   front_min_m < 0.90m
DANGER: front_min_m < 0.50m
```

为了减少抖动，后来加了去抖：

```text
连续 2 帧 WARN 才进入 WARN
连续 2 帧 DANGER 才进入 DANGER
连续 5 帧 CLEAR 才恢复 CLEAR
```

后来又尝试加入 Astra 深度相机：

```text
/camera/depth/image_raw
  -> 计算中心 ROI 深度 center_depth_m
  -> 深度优先，雷达兜底
```

但该路线现在不作为主架构，保留为 fallback/参考。

## 2. 小车侧踩过的坑

### 2.1 雷达单独判断会抖

现场箱子静止时，雷达前方距离会跳：

```text
0.47m -> DANGER
3.88m -> CLEAR
unknown -> CLEAR
0.49m -> DANGER
```

原因可能是：

- 箱子边缘/材质导致某些扫描帧丢点；
- 激光雷达只是一条扫描平面；
- 前方扇区使用最小值，单点噪声影响明显；
- 障碍物位置接近阈值时会来回跳。

处理方式：

```text
加去抖 + 状态滞回
```

但最终仍建议 PC 端做融合和决策。

### 2.2 app.py 占用摄像头和底盘串口

`app.py` 是小车主服务：

```text
6500: /video_feed
6000: 控制 TCP
```

它会占用：

```text
/dev/video0
/dev/myserial -> /dev/ttyUSB1
```

所以如果另一个进程也直接创建 `Rosmaster()`，可能和 `app.py` 抢串口，导致蜂鸣器/停车命令不稳定。

推荐做法：

```text
不要让多个进程直接抢 /dev/myserial。
电脑端通过 6000 TCP 协议让 app.py 代为执行蜂鸣/停车。
```

### 2.3 蜂鸣器不是系统音量

蜂鸣器不是 Linux 音箱，不受系统音量控制。

它是小车底板硬件命令：

```python
Rosmaster.set_beep(on_time)
```

所以要么：

1. 直接串口调用 `Rosmaster.set_beep()`；
2. 更推荐：通过 `app.py` 的 6000 TCP 控制协议发蜂鸣器命令。

### 2.4 Astra 深度相机可能 Resource busy

尝试深度融合时遇到：

```text
Could not open "2bc5/060f@1/11": Resource busy!
```

说明 Astra 被已有节点占用或旧进程残留。

因此主架构改为 PC 端处理，小车端只发数据。

## 3. 控制协议基础

小车控制端口：

```text
TCP <CAR_IP>:6000
```

帧格式：

```text
$ + car_type + cmd + len + payload + checksum + #
```

常用小车类型：

```text
car_type = 0x01
```

校验和：

```python
checksum = (0x9E + sum([car_type, cmd, length] + payload_bytes)) & 0xFF
```

组帧函数：

```python
def build_frame(car_type, cmd, payload):
    length = len(payload) * 2 + 2
    body = [car_type, cmd, length] + payload
    checksum = (0x9E + sum(body)) & 0xFF
    return "$" + "".join(f"{b:02X}" for b in body) + f"{checksum:02X}#"
```

## 4. 单独控制蜂鸣器命令

蜂鸣器命令：

```text
cmd = 0x13
payload = [state, delay]
```

源码逻辑：

```python
num_state = payload[0]
num_delay = payload[1]

if num_state > 0:
    if num_delay == 255:
        delay_ms = 1      # 一直响
    else:
        delay_ms = num_delay * 10
else:
    delay_ms = 0          # 关闭

set_beep(delay_ms)
```

### 4.1 短响 60ms

```python
build_frame(0x01, 0x13, [0x01, 0x06])
```

结果：

```text
$0113060106BF#
```

### 4.2 短响 200ms

```python
build_frame(0x01, 0x13, [0x01, 0x14])
```

结果：

```text
$0113060114CD#
```

### 4.3 一直响

```python
build_frame(0x01, 0x13, [0x01, 0xFF])
```

结果：

```text
$01130601FFB8#
```

### 4.4 关闭蜂鸣器

```python
build_frame(0x01, 0x13, [0x00, 0x00])
```

结果：

```text
$0113060000B8#
```

## 5. Python 发送蜂鸣器命令示例

```python
import socket

CAR_IP = "192.168.27.221"
CAR_PORT = 6000


def send_frame(frame: str):
    s = socket.socket()
    s.settimeout(1)
    s.connect((CAR_IP, CAR_PORT))
    s.send(frame.encode("ascii"))
    s.close()


# 蜂鸣 200ms
send_frame("$0113060114CD#")

# 关闭蜂鸣器
send_frame("$0113060000B8#")
```

## 6. 前端如何封装蜂鸣器

浏览器前端不能直接稳定访问原始 TCP 6000。

推荐：

```text
前端 -> PC 后端 HTTP
PC 后端 -> 小车 TCP 6000
```

PC 后端可以提供：

```http
POST /api/car/beep
Content-Type: application/json

{
  "duration_ms": 200
}
```

PC 后端逻辑：

```python
def beep(duration_ms):
    if duration_ms <= 0:
        frame = "$0113060000B8#"
    elif duration_ms == 1:
        frame = "$01130601FFB8#"  # 一直响
    else:
        delay = max(1, min(254, round(duration_ms / 10)))
        frame = build_frame(0x01, 0x13, [0x01, delay])
    send_tcp_6000(frame)
```

建议前端按钮：

```text
蜂鸣 200ms -> POST /api/car/beep {"duration_ms":200}
关闭蜂鸣 -> POST /api/car/beep {"duration_ms":0}
```

## 7. 与 STOP 命令配合

之前推导的 STOP 帧：

```text
$0110060000B5#
```

DANGER 时 PC 后端可以：

```text
1. 发送 STOP: $0110060000B5#
2. 发送蜂鸣: $0113060114CD#
```

建议先只打印，不立即控车；稳定后再打开真实发送。
