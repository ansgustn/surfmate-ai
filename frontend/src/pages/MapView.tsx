import { useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { api, BOTTOM_LABEL, STATUS_COLOR, windDirLabel, type SpotReport, type Status } from '../api'
import { CrowdBadge } from '../components/CrowdBadge'
import { StatusBadge } from '../components/StatusBadge'
import { SourceNote } from './Home'

/** 줌에 따라: 아주 멀리 → 시도 묶음, 중간 → 시군 묶음, 가까이 → 해변별 점 */
const REGION_ZOOM = 8
const SPOT_ZOOM = 10
const PROVINCE: Record<string, string> = {
  고성: '강원', 속초: '강원', 양양: '강원', 강릉: '강원', 동해: '강원', 삼척: '강원',
  울진: '경북', 영덕: '경북', 포항: '경북', 경주: '경북',
  울산: '부산·울산', 부산: '부산·울산', 거제: '경남', 제주: '제주', 태안: '충남',
}
const isUnverified = (r: SpotReport) => r.spot.bottom_type === 'unknown'
const STATUS_RANK: Record<Status, number> = { optimal: 0, caution: 1, avoid: 2 }

interface Props {
  selectedId: string | null
  onSelect: (id: string) => void
}

export function MapView({ selectedId, onSelect }: Props) {
  const [reports, setReports] = useState<SpotReport[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.allReports().then(setReports).catch((e: Error) => setError(e.message))
  }, [])

  const selected = reports.find((r) => r.spot.id === selectedId) ?? reports[0]

  return (
    <div className="map-page">
      <div className="map-wrap">
        <MapContainer center={[36.5, 128.9]} zoom={7} className="map">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <Markers reports={reports} selectedId={selected?.spot.id} onSelect={onSelect} />
          {selectedId && selected
            ? <FlyTo lat={selected.spot.lat} lon={selected.spot.lon} />
            : <FitAll reports={reports} />}
        </MapContainer>
        <SpotSearch reports={reports} onSelect={onSelect} />
        <div className="legend">
          <span><i style={{ background: 'var(--optimal)' }} />입수 최적</span>
          <span><i style={{ background: 'var(--caution)' }} />주의 요망</span>
          <span><i style={{ background: 'var(--avoid)' }} />입수 자제</span>
          <span><i className="hollow" />지형 미확인</span>
          <span className="legend-hint">확대하면 해변별로 보여요</span>
        </div>
      </div>

      <aside className="detail">
        {error && <p className="error">백엔드에 연결하지 못했습니다. ({error})</p>}
        {selected && <Detail r={selected} />}
        {reports.length > 0 && <SourceNote reports={reports} />}
      </aside>
    </div>
  )
}

/** 멀리서 보면 지역별 묶음(가장 좋은 등급 색 + 해변 수), 확대하면 해변별 점 */
function Markers({ reports, selectedId, onSelect }: { reports: SpotReport[]; selectedId?: string; onSelect: (id: string) => void }) {
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })

  if (zoom >= SPOT_ZOOM) {
    // 지형이 확인된 해변을 나중에 그려 위에 오게
    const ordered = [...reports].sort((a, b) => Number(!isUnverified(a)) - Number(!isUnverified(b)))
    return (
      <>
        {ordered.map((r) => (
          <CircleMarker
            key={r.spot.id}
            center={[r.spot.lat, r.spot.lon]}
            radius={r.spot.id === selectedId ? 12 : isUnverified(r) ? 6 : 9}
            pathOptions={isUnverified(r)
              ? { color: STATUS_COLOR[r.grade.status], weight: 2, fillColor: '#fff', fillOpacity: 0.9 }
              : { color: '#fff', weight: 2, fillColor: STATUS_COLOR[r.grade.status], fillOpacity: 1 }}
            eventHandlers={{ click: () => onSelect(r.spot.id) }}
          >
            <Tooltip direction="top" offset={[0, -8]}>
              {r.spot.region} {r.spot.name} · {r.grade.label}{isUnverified(r) ? ' (지형 미확인)' : ''}
            </Tooltip>
          </CircleMarker>
        ))}
      </>
    )
  }

  const groups = new Map<string, SpotReport[]>()
  const groupOf = (r: SpotReport) => (zoom >= REGION_ZOOM ? r.spot.region : PROVINCE[r.spot.region] ?? r.spot.region)
  for (const r of reports) groups.set(groupOf(r), [...(groups.get(groupOf(r)) ?? []), r])
  return (
    <>
      {[...groups].map(([region, rs]) => {
        const lat = rs.reduce((a, r) => a + r.spot.lat, 0) / rs.length
        const lon = rs.reduce((a, r) => a + r.spot.lon, 0) / rs.length
        const best = rs.reduce((a, r) => (STATUS_RANK[r.grade.status] < STATUS_RANK[a.grade.status] ? r : a))
        return (
          <CircleMarker
            key={region}
            center={[lat, lon]}
            radius={14}
            pathOptions={{ color: '#fff', weight: 3, fillColor: STATUS_COLOR[best.grade.status], fillOpacity: 0.9 }}
            eventHandlers={{ click: () => map.flyTo([lat, lon], zoom >= REGION_ZOOM ? SPOT_ZOOM + 1 : REGION_ZOOM + 1, { duration: 0.8 }) }}
          >
            <Tooltip permanent direction="right" offset={[14, 0]} className="region-label">
              {region} {rs.length}곳
            </Tooltip>
          </CircleMarker>
        )
      })}
    </>
  )
}

/** 해변·지역 이름 검색 → 고르면 그 해변으로 이동 */
function SpotSearch({ reports, onSelect }: { reports: SpotReport[]; onSelect: (id: string) => void }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const results = useMemo(() => {
    const t = q.replace(/\s|해변|해수욕장/g, '')
    if (!t) return []
    return reports
      .filter((r) => `${r.spot.region}${r.spot.name}`.replace(/\s|해변/g, '').includes(t))
      .sort((a, b) => Number(isUnverified(a)) - Number(isUnverified(b)) || STATUS_RANK[a.grade.status] - STATUS_RANK[b.grade.status])
      .slice(0, 8)
  }, [q, reports])

  const pick = (id: string) => {
    onSelect(id)
    setQ('')
    setOpen(false)
  }

  return (
    <div className="spot-search">
      <input
        type="search"
        value={q}
        placeholder={`해변 검색 (${reports.length}곳)`}
        aria-label="해변 검색"
        onChange={(e) => { setQ(e.target.value); setOpen(true) }}
        onKeyDown={(e) => { if (e.key === 'Enter' && results[0]) pick(results[0].spot.id) }}
      />
      {open && q && (
        <ul className="search-results" role="listbox">
          {results.length === 0 && <li className="muted small">찾는 해변이 없어요</li>}
          {results.map((r) => (
            <li key={r.spot.id}>
              <button type="button" onClick={() => pick(r.spot.id)}>
                <span>{r.spot.region} {r.spot.name}{isUnverified(r) && <em className="muted small"> · 지형 미확인</em>}</span>
                <StatusBadge status={r.grade.status} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 처음 열 때 모든 해변이 한 화면에 들어오게 */
function FitAll({ reports }: { reports: SpotReport[] }) {
  const map = useMap()
  useEffect(() => {
    if (!reports.length) return
    map.invalidateSize() // 탭 전환 직후에는 지도 크기가 아직 0일 수 있음
    // 아래쪽은 범례에 가리지 않도록 여백을 더 둔다
    map.fitBounds(reports.map((r) => [r.spot.lat, r.spot.lon] as [number, number]),
      { paddingTopLeft: [30, 30], paddingBottomRight: [30, 60] })
  }, [map, reports])
  return null
}

function FlyTo({ lat, lon }: { lat: number; lon: number }) {
  const map = useMap()
  useEffect(() => {
    map.flyTo([lat, lon], 12, { duration: 0.8 })
  }, [map, lat, lon])
  return null
}

function Detail({ r }: { r: SpotReport }) {
  const c = r.conditions
  return (
    <>
      <div className="spot-card-head">
        <h2>{r.spot.region} {r.spot.name}</h2>
        <StatusBadge status={r.grade.status} />
      </div>
      {isUnverified(r) && (
        <p className="unverified-note">공공데이터에서 자동으로 가져온 해변이에요. 바닥 지형·이안류·서핑 가능 여부가 확인되지 않아 최소 '주의 요망'으로 표시합니다.</p>
      )}
      <dl className="detail-grid">
        <dt>파고</dt><dd>{c.wave_height_m} m</dd>
        <dt>파주기</dt><dd>{c.wave_period_s} s</dd>
        <dt>풍향</dt><dd>{windDirLabel(c.wind_dir_deg)} ({c.wind_speed_ms} m/s)</dd>
        <dt>조위</dt><dd>{c.tide_m} m (평균해수면 기준)</dd>
        <dt>출처</dt><dd>{c.source === 'kma' ? `기상청 실측 (${c.station})` : c.source === 'open-meteo' ? 'Open-Meteo 예보' : '가짜(mock) 데이터'}</dd>
        <dt>지형</dt><dd>{BOTTOM_LABEL[r.spot.bottom_type]}</dd>
        <dt>추천 보드</dt><dd>{r.spot.board_fit.length ? r.spot.board_fit.join(', ') : '정보 없음'}</dd>
      </dl>
      <h3>판단 근거</h3>
      <ul className="reasons">
        {r.grade.reasons.map((s) => <li key={s}>{s}</li>)}
      </ul>
      {r.spot.note && <p className="muted">{r.spot.note}</p>}
      <h3>혼잡도 예측</h3>
      {r.congestion ? (
        <>
          <div className="crowd-now">
            <span>지금</span>
            <CrowdBadge level={r.congestion.level} prefix="" />
          </div>
          <ul className="slots" aria-label="시간대별 혼잡도">
            {r.congestion.slots.map((s) => (
              <li key={s.label}>
                <span>{s.label}</span>
                <span className="bar" aria-hidden><span className={`bar-fill crowd-${s.level}`} style={{ width: `${Math.max(s.score, 3)}%` }} /></span>
                <CrowdBadge level={s.level} prefix="" />
              </li>
            ))}
          </ul>
          <p className="muted small">요인: {r.congestion.factors.join(' · ')}</p>
          <p className="muted small">※ {r.congestion.method}. 실제 인원 데이터가 아닌 추정치입니다.</p>
        </>
      ) : (
        <p className="muted">혼잡도 정보가 없습니다.</p>
      )}
    </>
  )
}
