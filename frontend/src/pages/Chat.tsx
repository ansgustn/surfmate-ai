import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type ChatTurn, type SpotReport } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import type { LocationState } from '../useLocation'

interface Message extends ChatTurn {
  alternatives?: SpotReport[]
  error?: boolean
}

interface Props {
  loc: LocationState
  onSelect: (spotId: string) => void
}

const EXAMPLES = [
  '근처에 초보자가 가기 좋은 해변 있어?',
  '지금 해운대 해변 어때? 초보자도 들어갈 수 있을까?',
  '양양 쪽은 지금 어때?',
  '제주 쪽은 지금 어때?',
  '오늘 덜 붐비는 곳은 어디야?',
]

const GREETING: Message = {
  role: 'assistant',
  content: '안녕하세요! 해변 이름을 넣어 물어보시면 지금 상태를 분석하고, 더 안전한 대안 스팟도 알려드릴게요.',
}

// 챗봇 탭을 떠났다 돌아와도 대화가 남도록 모듈 범위에 보관 (새로고침하면 초기화)
let saved: Message[] = [GREETING]

export function Chat({ loc, onSelect }: Props) {
  const [messages, setMessages] = useState<Message[]>(saved)
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    saved = messages
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  async function send(text: string) {
    const q = text.trim()
    if (!q || pending) return
    // 인사말·오류는 대화 기록에서 뺀다
    const history: ChatTurn[] = messages
      .filter((m) => m !== GREETING && !m.error)
      .slice(-10)
      .map(({ role, content }) => ({ role, content }))
    setMessages((m) => [...m, { role: 'user', content: q }])
    setInput('')
    setPending(true)
    try {
      const r = await api.chat(q, history, loc.coords)
      setMessages((m) => [...m, { role: 'assistant', content: r.reply, alternatives: r.alternatives }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', content: (e as Error).message, error: true }])
    } finally {
      setPending(false)
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void send(input)
  }

  return (
    <div className="chat">
      <div className="chat-log" aria-live="polite">
        {messages.map((m, i) => (
          <div key={i} className={`bubble-row ${m.role}`}>
            <div className={`bubble ${m.role}${m.error ? ' error' : ''}`}>{m.content}</div>
            {m.alternatives && m.alternatives.length > 0 && (
              <div className="alts">
                <p className="muted small">대안 스팟 추천</p>
                {m.alternatives.map((a) => (
                  <button key={a.spot.id} className="spot-card" onClick={() => onSelect(a.spot.id)}>
                    <div className="spot-card-head">
                      <strong>{a.spot.name}</strong>
                      <StatusBadge status={a.grade.status} />
                    </div>
                    <div className="muted">파고 {a.conditions.wave_height_m}m · {a.spot.region}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {pending && (
          <div className="bubble-row assistant">
            <div className="bubble assistant muted">분석 중… (첫 질문은 모델을 불러오느라 조금 걸려요)</div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      {/* 추천 질문: 입력창 위에 항상 표시 (대화 중에도 누를 수 있게) */}
      <div className="examples" aria-label="추천 질문">
        <span className="examples-title">추천 질문</span>
        {EXAMPLES.map((q) => (
          <button key={q} type="button" className="chip suggest" disabled={pending} onClick={() => void send(q)}>{q}</button>
        ))}
      </div>
      <form className="chat-input" onSubmit={onSubmit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="메시지를 입력하세요"
          aria-label="메시지"
          maxLength={500}
          disabled={pending}
        />
        <button type="submit" disabled={pending || !input.trim()}>보내기</button>
      </form>
    </div>
  )
}
