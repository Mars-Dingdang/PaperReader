import type { FailureItem, LatexRecoveryItem, StageItem } from '../lib/api'

type Props = {
  status: string
  progress: number
  currentStageLabel?: string | null
  etaSeconds?: number | null
  stages: StageItem[]
  failure?: FailureItem | null
  latexRecovery?: LatexRecoveryItem | null
  retrying?: boolean
  onRetry?: () => void
}

function formatEta(s?: number | null): string {
  if (s == null || s <= 0) return '—'
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}m ${sec}s`
}

export function ProgressBar({
  status,
  progress,
  currentStageLabel,
  etaSeconds,
  stages,
  failure,
  latexRecovery,
  retrying = false,
  onRetry
}: Props) {
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
          <div className="progress-track"><div className="progress-fill" style={{ width: `${Math.max(4, progress)}%` }} /></div>
          <div className="failure-panel">
            <div className="failure-heading">
              <span className="small" style={{ color: 'var(--danger)' }}>
                {failure ? `${failure.stage}${failure.chunk ? ` · chunk ${failure.chunk}` : ''} 失败` : '处理失败'}
              </span>
              {failure?.retryable && onRetry && (
                <button className="btn small retry-button" disabled={retrying} onClick={onRetry}>
                  {retrying ? '正在重新排队…' : '从此处重试'}
                </button>
              )}
            </div>
            {failure?.message && <p className="failure-message small">{failure.message}</p>}
            {latexRecovery?.diagnosis && (
              <div className="recovery-detail small">
                <strong>模型诊断：</strong>{latexRecovery.diagnosis}
              </div>
            )}
            {!!latexRecovery?.repairs.length && (
              <details className="recovery-detail small">
                <summary>查看自动修复记录（{latexRecovery.repairs.length}）</summary>
                {latexRecovery.repairs.map((repair, index) => (
                  <div key={`${repair.start_line}-${index}`}>
                    第 {repair.start_line}{repair.end_line !== repair.start_line ? `–${repair.end_line}` : ''} 行：{repair.reason || '最小修复'}
                  </div>
                ))}
              </details>
            )}
          </div>
        </div>
      )
  }
  if (stages.length === 0) return null

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
            : status === 'recovering'
              ? currentStageLabel || '正在恢复 LaTeX…'
            : currentStageLabel
              ? `当前：${currentStageLabel}`
              : '处理中'}
        </span>
        <span className="muted small">{pct}% · 预计剩余 {formatEta(etaSeconds)}</span>
      </div>
      {latexRecovery?.diagnosis && (
        <div className="recovery-detail small">
          <strong>模型诊断：</strong>{latexRecovery.diagnosis}
          {!!latexRecovery.repairs.length && ` · 已应用 ${latexRecovery.repairs.length} 处最小修复`}
        </div>
      )}
    </div>
  )
}
