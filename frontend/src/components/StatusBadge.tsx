import type { Status } from '../api'

const LABEL: Record<Status, string> = { optimal: '입수 최적', caution: '주의 요망', avoid: '입수 자제' }

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge badge-${status}`}>{LABEL[status]}</span>
}
