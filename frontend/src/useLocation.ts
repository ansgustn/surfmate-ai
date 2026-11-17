import { useEffect, useState } from 'react'
import type { Coords } from './api'

export const PRESETS: Record<string, Coords> = {
  '부산 해운대': { lat: 35.1631, lon: 129.1636 },
  '양양 죽도': { lat: 37.9727, lon: 128.7597 },
  '강릉 금진': { lat: 37.6533, lon: 129.0469 },
  '포항 월포': { lat: 36.2155, lon: 129.3763 },
  '태안 만리포': { lat: 36.7869, lon: 126.1424 },
  '제주시': { lat: 33.4996, lon: 126.5312 },
  '서귀포 중문': { lat: 33.2449, lon: 126.4109 },
}

export type LocationState = { coords: Coords; label: string }

/** 브라우저 위치를 쓰고, 거부되거나 실패하면 부산 해운대를 기본값으로 쓴다. */
export function useLocation() {
  const [loc, setLoc] = useState<LocationState>({ coords: PRESETS['부산 해운대'], label: '부산 해운대' })

  useEffect(() => {
    if (!('geolocation' in navigator)) return
    navigator.geolocation.getCurrentPosition(
      (p) => setLoc({ coords: { lat: p.coords.latitude, lon: p.coords.longitude }, label: '현재 위치' }),
      () => {},
      { timeout: 5000 },
    )
  }, [])

  return [loc, setLoc] as const
}
