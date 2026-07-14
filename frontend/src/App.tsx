import { useCallback, useEffect, useState } from 'react'
import {
  api,
  type AlertItem,
  type ObstacleStatus,
  type SensorHealth,
  type VehicleStatus,
} from './api'
import './App.css'

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}

function sensorText(s: SensorHealth): string {
  if (s.alive) return '在线'
  if (s.connected) return '连接中 / 数据陈旧'
  return '离线'
}

export default function App() {
  const [vehicle, setVehicle] = useState<VehicleStatus | null>(null)
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [obstacle, setObstacle] = useState<ObstacleStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [v, a] = await Promise.all([api.vehicleStatus(), api.alerts()])
      setVehicle(v)
      setAlerts(a.items)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '无法连接后端')
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 2000)
    return () => window.clearInterval(timer)
  }, [refresh])

  const refreshObstacle = useCallback(async () => {
    try {
      setObstacle(await api.obstacleStatus())
    } catch {
      setObstacle(null)
    }
  }, [])

  useEffect(() => {
    void refreshObstacle()
    const timer = window.setInterval(() => void refreshObstacle(), 500)
    return () => window.clearInterval(timer)
  }, [refreshObstacle])

  async function toggleActuation() {
    if (!obstacle) return
    try {
      setObstacle(
        await api.updateObstacleConfig({
          actuation_enabled: !obstacle.config.actuation_enabled,
        }),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换执行模式失败')
    }
  }

  async function beepTest() {
    try {
      await api.carBeep(200)
    } catch (e) {
      setError(e instanceof Error ? e.message : '蜂鸣失败')
    }
  }

  async function manualStop() {
    try {
      await api.carStop()
    } catch (e) {
      setError(e instanceof Error ? e.message : '停车失败')
    }
  }

  async function runCommand(action: string, extra?: Record<string, unknown>) {
    setBusy(true)
    try {
      await api.sendCommand(action, extra)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '指令失败')
    } finally {
      setBusy(false)
    }
  }

  async function ack(id: string) {
    try {
      await api.ackAlert(id)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '确认失败')
    }
  }

  async function simulateObstacle() {
    try {
      await api.createAlert({
        level: 'warning',
        code: 'OBS',
        message: '检测到前方障碍物，请减速或绕行',
      })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '告警创建失败')
    }
  }

  return (
    <div className="page">
      <header className="top">
        <div className="brand">
          <span className="brand-mark" aria-hidden />
          <div>
            <h1>FCar</h1>
            <p>车载监控台 · 实时影像与告警</p>
          </div>
        </div>
        <div className={`link-state ${error ? 'bad' : 'ok'}`}>
          {error ? `后端异常：${error}` : 'API 已连接'}
        </div>
      </header>

      <main className="grid">
        <section className="panel obstacle-panel">
          <div className="panel-head">
            <h2>障碍物检测</h2>
            {obstacle ? (
              <span className={`tag obstacle-badge level-${obstacle.level}`}>
                {obstacle.level}
              </span>
            ) : (
              <span className="tag">未连接</span>
            )}
          </div>
          {obstacle ? (
            <div className="obstacle-body">
              <div className="stream-frame">
                <img src={api.obstacleVideoUrl} alt="YOLO 标注画面" />
              </div>
              <p className={`obstacle-message level-${obstacle.level}`}>
                {obstacle.message}
              </p>
              <dl className="status-list">
                <div>
                  <dt>距离</dt>
                  <dd>
                    {obstacle.distance_m == null
                      ? '—'
                      : `${obstacle.distance_m.toFixed(2)} m`}
                  </dd>
                </div>
                <div>
                  <dt>类别</dt>
                  <dd>{obstacle.label ?? '—'}</dd>
                </div>
                <div>
                  <dt>来源</dt>
                  <dd>{obstacle.source}</dd>
                </div>
                <div>
                  <dt>雷达</dt>
                  <dd>{sensorText(obstacle.sensors.lidar)}</dd>
                </div>
                <div>
                  <dt>视觉</dt>
                  <dd>{sensorText(obstacle.sensors.vision)}</dd>
                </div>
                <div>
                  <dt>执行</dt>
                  <dd className={obstacle.config.actuation_enabled ? 'mode mode-driving' : 'muted'}>
                    {obstacle.config.actuation_enabled ? '真实发送' : 'dry-run（只打印）'}
                  </dd>
                </div>
              </dl>
              <div className="actions">
                <button type="button" onClick={() => void toggleActuation()}>
                  {obstacle.config.actuation_enabled ? '切回 dry-run' : '启用真实控制'}
                </button>
                <button type="button" className="ghost" onClick={() => void beepTest()}>
                  蜂鸣测试
                </button>
                <button type="button" className="danger" onClick={() => void manualStop()}>
                  手动 STOP
                </button>
              </div>
            </div>
          ) : (
            <p className="muted">障碍物服务未连接（后端未启动或子系统未运行）</p>
          )}
        </section>

        <section className="panel stream-panel">
          <div className="panel-head">
            <h2>实时影像</h2>
            <span className="tag live">MJPEG</span>
          </div>
          <div className="stream-frame">
            <img src={api.streamUrl} alt="小车实时预览" />
          </div>
        </section>

        <section className="panel status-panel">
          <div className="panel-head">
            <h2>车辆状态</h2>
          </div>
          {vehicle ? (
            <dl className="status-list">
              <div>
                <dt>编号</dt>
                <dd>{vehicle.id}</dd>
              </div>
              <div>
                <dt>在线</dt>
                <dd>{vehicle.online ? '是' : '否'}</dd>
              </div>
              <div>
                <dt>模式</dt>
                <dd className={`mode mode-${vehicle.mode}`}>{vehicle.mode}</dd>
              </div>
              <div>
                <dt>电量</dt>
                <dd>{vehicle.battery}%</dd>
              </div>
              <div>
                <dt>速度</dt>
                <dd>{vehicle.speed_kmh.toFixed(1)} km/h</dd>
              </div>
              <div>
                <dt>位置</dt>
                <dd>
                  {vehicle.position.lat.toFixed(4)}, {vehicle.position.lng.toFixed(4)}
                </dd>
              </div>
              <div>
                <dt>更新</dt>
                <dd>{formatTime(vehicle.updated_at)}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted">加载中…</p>
          )}

          <div className="actions">
            <button type="button" disabled={busy} onClick={() => void runCommand('start')}>
              启动
            </button>
            <button type="button" disabled={busy} onClick={() => void runCommand('stop')}>
              停车
            </button>
            <button
              type="button"
              className="danger"
              disabled={busy}
              onClick={() => void runCommand('emergency')}
            >
              急停
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => void simulateObstacle()}>
              模拟障碍告警
            </button>
          </div>
        </section>

        <section className="panel alerts-panel">
          <div className="panel-head">
            <h2>告警</h2>
            <span className="tag">{alerts.filter((a) => !a.acked).length} 未确认</span>
          </div>
          <ul className="alerts">
            {alerts.length === 0 && <li className="muted">暂无告警</li>}
            {alerts.map((a) => (
              <li key={a.id} className={`alert level-${a.level} ${a.acked ? 'acked' : ''}`}>
                <div className="alert-main">
                  <strong>{a.code}</strong>
                  <span>{a.message}</span>
                  <time>{formatTime(a.created_at)}</time>
                </div>
                {!a.acked && (
                  <button type="button" className="ghost" onClick={() => void ack(a.id)}>
                    确认
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  )
}
