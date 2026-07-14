# FCar

小车前后端原型：Flask API + React 监控台（实时影像、车辆状态、告警、**障碍物检测**）。

## 目录

```
backend/     Flask 后端（端口 5000），含 PC 端障碍物检测子系统 app/obstacle/
frontend/    React + Vite 前端（端口 5173，代理 /api）
```

## 后端（推荐 conda，因需 opencv/torch/ultralytics）

```powershell
conda env create -f backend/environment.yml   # 创建 fcar 环境（python 3.10）
conda activate fcar
# GPU（RTX 4060）跑 YOLO，装 CUDA 版 torch：
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
cd backend
python run.py
```

> 环境变量 `CAR_IP` 指定小车地址（默认 `192.168.137.174`）：
> `set CAR_IP=192.168.137.174 && python run.py`

## 障碍物检测子系统

PC 端连小车三路：`6602` 雷达 WS（距离权威）、`6500` RGB 视频（YOLO 确认 + 类别）、
`6000` 控制 TCP（DANGER 时发 STOP + 蜂鸣）。融合策略 `lidar_authority_vision_confirm`，
带去抖状态机（CLEAR/WARN/DANGER）与双向降级（雷达缺→`vision_only`；视觉缺→`lidar`）。

**安全**：`actuation_enabled` 默认 `False`（dry-run 只打印 `would_send`），
在前端"障碍物检测"面板或 `POST /api/obstacle/config {"actuation_enabled":true}` 打开后才真发帧。

### 无小车本地联调 + 自测

```powershell
python backend/scripts/mock_car.py            # 本机模拟 6602/6500/6000（stdin: c/w/d/b/q）
python backend/scripts/smoke_test.py          # 逻辑单测：控制帧/前方距离/去抖
python backend/scripts/integration_test.py    # 真 socket：雷达WS→DANGER→dry-run/真发
python backend/scripts/app_test.py            # HTTP 层：端点/配置热更新
```

## 前端

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:5173

## 主要接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/vehicle/status` | 车辆状态 |
| PATCH | `/api/vehicle/status` | 更新状态字段 |
| POST | `/api/vehicle/command` | 指令：`start` / `stop` / `emergency` / `set_speed` |
| GET | `/api/alerts` | 告警列表（`?unacked=true`） |
| POST | `/api/alerts` | 新建告警 |
| POST | `/api/alerts/<id>/ack` | 确认告警 |
| GET | `/api/stream` | 影像流元信息 |
| GET | `/api/stream/mjpeg` | MJPEG 占位预览（可换成真实摄像头） |
| GET | `/api/obstacle/status` | 障碍物融合状态（level/distance/label/source/sensors） |
| GET | `/api/obstacle/health` | 子系统健康（雷达/视觉存活、actuation 状态） |
| GET/POST | `/api/obstacle/config` | 读取 / 热更新阈值、角度窗口、`lidar_offset_m`、`actuation_enabled` 等 |
| GET | `/api/obstacle/video` | YOLO 标注后的 MJPEG 流 |
| POST | `/api/car/beep` | 手动蜂鸣（`{"duration_ms":200}`） |
| POST | `/api/car/stop` | 手动发送 STOP 帧 |
