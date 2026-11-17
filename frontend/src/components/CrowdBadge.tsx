import type { CrowdLevel } from '../api'

const LABEL: Record<CrowdLevel, string> = { low: '여유', normal: '보통', high: '혼잡' }

/** 라인업 혼잡도(추정) 표시. 안전 등급 배지와 구분되도록 테두리형 */
export function CrowdBadge({ level, prefix = '혼잡도 ' }: { level: CrowdLevel; prefix?: string }) {
  return (
    <span className={`crowd crowd-${level}`}>
      <i aria-hidden />
      {prefix}{LABEL[level]}
    </span>
  )
}
