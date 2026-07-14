# FCar

小车前后端原型：Flask API + React 监控台（实时影像占位流、车辆状态、告警）。

## 目录

```
backend/     Flask 后端（端口 5000）
frontend/    React + Vite 前端（端口 5173，代理 /api）
```

## 后端

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py run.py
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
