import { useEffect, useState } from 'react'
import { api, BOTTOM_LABEL, windDirLabel, type SpotReport } from '../api'
import { CrowdBadge } from '../components/CrowdBadge'
import { StatusBadge } from '../components/StatusBadge'
import { PRESETS, type LocationState } from '../useLocation'

interface Props {
  loc: LocationState
  setLoc: (l: LocationState) => void
  onSelect: (spotId: string) => void
}

export function Home({ loc, setLoc, onSelect }: Props) {
  const [reports, setReports] = useState<SpotReport[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setReports(null)
    setError(null)
    api.recommend(loc.coords).then(setReports).catch((e: Error) => setError(e.message))
  }, [loc])

  const nearest = reports?.slice().sort((a, b) => (a.distance_km ?? 0) - (b.distance_km ?? 0))[0]

  return (
    <div className="page">
      <header className="greeting">
        <p>안녕하세요!</p>
        <h1>지금 조건에 맞는<br />최적의 서핑 스팟을 추천해드려요.</h1>
        <div className="loc-row">
          <span>📍 {loc.label}</span>
          {Object.entries(PRESETS).map(([label, coords]) => (
            <button key={label} className="chip" aria-pressed={loc.label === label}
              onClick={() => setLoc({ coords, label })}>{label}</button>
          ))}
        </div>
      </header>

      {nearest && (
        <section className="cond-cards" aria-label={`${nearest.spot.name} 현재 기상`}>
          <Cond title="파고" value={`${nearest.conditions.wave_height_m} m`} />
          <Cond title="풍향" value={windDirLabel(nearest.conditions.wind_dir_deg)}
            sub={`${nearest.conditions.wind_speed_ms} m/s`} />
          <Cond title="조위" value={`${nearest.conditions.tide_m} m`} sub="평균해수면 기준" />
          <p className="cond-caption">가장 가까운 {nearest.spot.name} 기준</p>
        </section>
      )}

      <section>
        <h2>추천 스팟 TOP 3</h2>
        {error && <p className="error">백엔드에 연결하지 못했습니다. ({error})<br />backend 폴더에서 <code>uvicorn app.main:app --reload --port 8010</code> 를 실행했는지 확인해 주세요.</p>}
        {!reports && !error && <p className="muted">불러오는 중…</p>}
        {reports?.length === 0 && (
          <p className="muted">50km 안에 등록된 서핑 스팟이 없습니다. 위의 지역 버튼을 눌러 보세요.</p>
        )}
        <ol className="spot-list">
          {reports?.map((r) => (
            <li key={r.spot.id}>
              <button className="spot-card" onClick={() => onSelect(r.spot.id)}>
                <div className="spot-card-head">
                  <strong>{r.spot.name}</strong>
                  <StatusBadge status={r.grade.status} />
                </div>
                <div className="muted">
                  파고 {r.conditions.wave_height_m}m · {BOTTOM_LABEL[r.spot.bottom_type]}
                  {r.distance_km !== null && ` · ${r.distance_km}km`}
                </div>
                <div className="reason">{r.grade.reasons[0]}</div>
                {r.congestion && <div className="card-foot"><CrowdBadge level={r.congestion.level} /></div>}
              </button>
            </li>
          ))}
        </ol>
      </section>
      {reports && reports.length > 0 && <SourceNote reports={reports} />}
    </div>
  )
}

export function SourceNote({ reports }: { reports: SpotReport[] }) {
  const has = (src: string) => reports.some((r) => r.conditions.source === src)
  const parts = [
    has('kma') && '기상청 해양관측 실측',
    has('open-meteo') && 'Open-Meteo 예보 모델(연안 격자 기준)',
    has('mock') && '개발용 가짜(mock) 데이터',
  ].filter(Boolean)
  return <p className="disclaimer">기상: {parts.join(' · ')}</p>
}

function Cond({ title, value, sub }: { title: string; value: string; sub?: string }) {
  return (
    <div className="cond">
      <span className="muted">{title}</span>
      <strong>{value}</strong>
      {sub && <span className="muted small">{sub}</span>}
    </div>
  )
}
