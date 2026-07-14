# 小车端激光雷达报警接口文档（备用/历史方案）

版本：v1-legacy

> 注意：本文件记录的是之前“小车端自己检测并报警”的实现方案。根据最新架构，后续主路线已经调整为：**电脑端负责所有检测和处理逻辑，小车端只负责通过 6000/6500/6602 传输控制、视频和雷达数据**。
>
> 因此，`obstacle_alert/obstacle_app.py` 及其 6511 接口只保留为硬件验证、断网 fallback 或历史参考，不作为后续主方案。

## 1. 旧方案目标

旧方案目标：

```text
小车端 Docker ROS2 /scan
  -> 小车端计算 front_min_m
  -> 小车端判断 CLEAR / WARN / DANGER
  -> 小车端蜂鸣/停车
  -> 小车端 6511 HTTP 接口输出状态
```

对应入口：

```bash
python3 obstacle_alert/obstacle_app.py
```

接口：

```text
GET http://<CAR_IP>:6511/api/obstacle/status
GET http://<CAR_IP>:6511/api/obstacle/health
GET/POST http://<CAR_IP>:6511/api/obstacle/config
```

## 2. 当前主方案

当前主方案已经调整为：

```text
小车端：
  6000 控制 TCP
  6500 视频流 /video_feed
  6602 雷达/里程计 WebSocket

电脑端：
  连接 6602 获取雷达数据
  可选连接 6500 获取视频
  执行障碍物检测、报警、停车/避障决策
  后续通过 6000 给小车发送 STOP/控制命令
```

主方案文档：

```text
obstacle_alert/doc/06_pc_side_architecture.md
obstacle_alert/doc/02_detection_technical方案.md
obstacle_alert/doc/03_app_alarm_interface.md
```

## 3. 旧方案仍然有用的地方

虽然不再作为主架构，但该接口仍可用于：

1. 小车端硬件验证；
2. 雷达 `/scan` 距离计算参考；
3. 蜂鸣器/停车命令验证；
4. 网络断开时的车端 fallback 原型；
5. 给电脑端算法复用状态机/阈值逻辑。

## 4. 不建议继续扩展的部分

后续不建议继续把以下逻辑放在小车端：

- 复杂 YOLO/视觉检测；
- 多传感器融合主决策；
- 避障路径规划；
- APP 主报警状态生成；
- 电脑端已经可以承担的重计算任务。

这些应放到电脑端实现。

## 5. 旧接口状态格式参考

旧小车端接口返回格式示例：

```json
{
  "level": "DANGER",
  "has_obstacle": true,
  "distance_m": 0.42,
  "source": "lidar",
  "message": "前方 0.42m 有障碍物",
  "timestamp": 1720000000.0
}
```

电脑端主方案可复用这个 JSON 格式，但 `source` 应改为：

```text
lidar_ws_6602
vision_6500
fusion
```

## 6. 旧方案启动命令

只检测、不触发硬件动作：

```bash
python3 obstacle_alert/obstacle_app.py --no-beep --no-stop
```

检测 + 蜂鸣，不停车：

```bash
python3 obstacle_alert/obstacle_app.py --no-stop
```

检测 + 蜂鸣 + 停车：

```bash
python3 obstacle_alert/obstacle_app.py
```

再次强调：这些是旧的小车端方案命令，后续主路线改为电脑端处理。
