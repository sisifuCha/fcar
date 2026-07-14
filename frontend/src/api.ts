export type VehicleStatus = {
  id: string
  name: string
  online: boolean
  battery: number
  speed_kmh: number
  mode: string
  position: { lat: number; lng: number; heading: number }
  updated_at: string
}

export type AlertItem = {
  id: string
  level: 'info' | 'warning' | 'critical' | string
  code: string
  message: string
  acked: boolean
  created_at: string
}

export type ObstacleLevel = 'CLEAR' | 'WARN' | 'DANGER' | 'UNKNOWN' | string

export type SensorHealth = {
  connected: boolean
  alive: boolean
  url: string
  last_error: string | null
  age_sec: number | null
  [k: string]: unknown
}

export type ObstacleStatus = {
  level: ObstacleLevel
  raw_level: ObstacleLevel
  has_obstacle: boolean
  distance_m: number | null
  source: 'lidar' | 'fusion' | 'vision_only' | 'none' | string
  label: string | null
  message: string
  timestamp: number
  fusion_policy: string
  config: ObstacleConfig
  control: {
    actuation_enabled: boolean
    beep_enabled: boolean
    stop_enabled: boolean
    last_frame: string | null
    last_action: string | null
    last_error: string | null
  }
  sensors: { lidar: SensorHealth; vision: SensorHealth }
}

export type ObstacleConfig = {
  car_ip: string
  warn_distance_m: number
  danger_distance_m: number
  front_min_deg: number
  front_max_deg: number
  lidar_offset_m: number
  max_range_m: number
  vision_enabled: boolean
  vision_conf: number
  vision_area_warn: number
  vision_area_danger: number
  actuation_enabled: boolean
  beep_enabled: boolean
  stop_enabled: boolean
  beep_duration_ms: number
  [k: string]: unknown
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string }>('/api/health'),
  vehicleStatus: () => request<VehicleStatus>('/api/vehicle/status'),
  sendCommand: (action: string, extra?: Record<string, unknown>) =>
    request<{ ok: boolean; vehicle: VehicleStatus }>('/api/vehicle/command', {
      method: 'POST',
      body: JSON.stringify({ action, ...extra }),
    }),
  alerts: () => request<{ items: AlertItem[] }>('/api/alerts'),
  ackAlert: (id: string) =>
    request<AlertItem>(`/api/alerts/${id}/ack`, { method: 'POST' }),
  createAlert: (payload: { level: string; code: string; message: string }) =>
    request<AlertItem>('/api/alerts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  streamUrl: '/api/stream/mjpeg',

  obstacleStatus: () => request<ObstacleStatus>('/api/obstacle/status'),
  updateObstacleConfig: (patch: Partial<ObstacleConfig>) =>
    request<ObstacleStatus>('/api/obstacle/config', {
      method: 'POST',
      body: JSON.stringify(patch),
    }),
  carBeep: (duration_ms = 200) =>
    request<{ ok: boolean; sent: boolean }>('/api/car/beep', {
      method: 'POST',
      body: JSON.stringify({ duration_ms }),
    }),
  carStop: () =>
    request<{ ok: boolean; sent: boolean }>('/api/car/stop', { method: 'POST' }),
  obstacleVideoUrl: '/api/obstacle/video',
}
