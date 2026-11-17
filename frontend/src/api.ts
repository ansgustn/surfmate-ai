// 백엔드(backend/app/models.py)와 맞춘 타입
export type Status = 'optimal' | 'caution' | 'avoid'

export interface Spot {
  id: string
  name: string
  region: string
  lat: number
  lon: number
  bottom_type: 'sand' | 'reef' | 'mixed' | 'rock' | 'unknown'
  beginner_friendly: boolean
  board_fit: string[]
  popularity: number
  note: string | null
}

export interface Conditions {
  wave_height_m: number
  wave_period_s: number
  wind_speed_ms: number
  wind_dir_deg: number
  tide_m: number
  source: 'kma' | 'open-meteo' | 'mock'
  station: string | null
}

export type CrowdLevel = 'low' | 'normal' | 'high'

export interface Congestion {
  score: number
  level: CrowdLevel
  level_label: string
  slots: { label: string; score: number; level: CrowdLevel; level_label: string }[]
  factors: string[]
  method: string
}

export interface SpotReport {
  spot: Spot
  conditions: Conditions
  grade: { status: Status; label: string; reasons: string[] }
  distance_km: number | null
  congestion: Congestion | null
}

export interface Coords {
  lat: number
  lon: number
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  reply: string
  spot: SpotReport | null
  alternatives: SpotReport[]
  model: string
}

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]),
  )
  const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`)
  return res.json() as Promise<T>
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // 본문이 JSON 이 아니면 상태 코드만
  }
  return `API ${res.status}`
}

export const api = {
  chat: async (message: string, history: ChatTurn[], c?: Coords): Promise<ChatResponse> => {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history, lat: c?.lat, lon: c?.lon }),
    })
    if (!res.ok) throw new Error(await errorMessage(res))
    return res.json() as Promise<ChatResponse>
  },
  recommend: (c: Coords, limit = 3, maxKm = 50) =>
    get<SpotReport[]>('/recommend', { lat: c.lat, lon: c.lon, limit, max_km: maxKm }),
  // 위치 없이 호출하면 전체 스팟을 등급순으로 돌려준다
  allReports: () => get<SpotReport[]>('/recommend', { limit: 500 }),
}

export const STATUS_COLOR: Record<Status, string> = {
  optimal: 'var(--optimal)',
  caution: 'var(--caution)',
  avoid: 'var(--avoid)',
}

export const BOTTOM_LABEL: Record<Spot['bottom_type'], string> = {
  sand: '모래 지형',
  reef: '암초 지형',
  mixed: '모래·암반 혼재',
  rock: '암반 지형',
  unknown: '미확인 (현장 확인 필요)',
}

const DIRS = ['북', '북동', '동', '남동', '남', '남서', '서', '북서']
export const windDirLabel = (deg: number) => `${DIRS[Math.round(deg / 45) % 8]}풍`
