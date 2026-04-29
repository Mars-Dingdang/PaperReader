import type { StageItem } from '../lib/api'

type Props = {
  status: string
  progress: number
  currentStageLabel?: string | null
  etaSeconds?: number | null
  stages: StageItem[]
}

function formatEta(s?: number | null): string {
  if (s == null || s <= 0) return '—'
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}m ${sec}s`
}

export function ProgressBar({ status, progress, currentStageLabel, etaSeconds, stages }: Props) {
  if (status === 'done' || stages.length === 0) {
    if (status === 'done') {
      return (
        <div className="progress-bar done">
          <div className="progress-track"><div className="progress-fill" style={{ width: '100%' }} /></div>
          <div className="progress-meta">
            <span className="muted small">已完成</span>
          </div>
        </div>
      )
    }
    if (status === 'failed') {
      return (
        <div className="progress-bar failed">
          <div className="progress-track"><div className="progress-fill" style={{ width: '100%' }} /></div>
          <div className="progress-meta">
            <span className="small" style={{ color: 'var(--danger)' }}>处理失败</span>
          </div>
        </div>
      )
    }
    return null
  }

  const pct = Math.max(0, Math.min(100, progress))
  return (
    <div className={`progress-bar ${status}`}>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="progress-stages">
        {stages.map((s) => (
          <div
            key={s.key}
            className={`stage-dot ${s.status}`}
            title={`${s.label} · ${s.status}${s.duration_ms ? ` · ${(s.duration_ms / 1000).toFixed(1)}s` : ''}`}
          >
            <span className="stage-tick" />
            <span className="stage-label small">{s.label}</span>
          </div>
        ))}
      </div>
      <div className="progress-meta">
        <span className="small">
          {status === 'awaiting_review'
            ? '等待人工审核…'
            : currentStageLabel
              ? `当前：${currentStageLabel}`
              : '处理中'}
        </span>
        <span className="muted small">{pct}% · 预计剩余 {formatEta(etaSeconds)}</span>
      </div>
    </div>
  )
}
