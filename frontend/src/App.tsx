import { useState } from 'react'
import { Chat } from './pages/Chat'
import { Home } from './pages/Home'
import { MapView } from './pages/MapView'
import { useLocation } from './useLocation'

type Tab = 'home' | 'map' | 'chat'
const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'home', label: '홈', icon: '🏠' },
  { id: 'map', label: '지도', icon: '🗺️' },
  { id: 'chat', label: '챗봇', icon: '💬' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('home')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loc, setLoc] = useLocation()

  const openOnMap = (id: string) => {
    setSelectedId(id)
    setTab('map')
  }

  return (
    <div className="app">
      <header className="topbar">🏄 SurfMate AI</header>
      <main>
        {tab === 'home' && <Home loc={loc} setLoc={setLoc} onSelect={openOnMap} />}
        {tab === 'map' && <MapView selectedId={selectedId} onSelect={setSelectedId} />}
        {tab === 'chat' && <Chat loc={loc} onSelect={openOnMap} />}
      </main>
      <nav className="tabbar">
        {TABS.map((t) => (
          <button key={t.id} aria-current={tab === t.id} onClick={() => setTab(t.id)}>
            <span aria-hidden>{t.icon}</span>
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  )
}
