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
}
