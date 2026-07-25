import type { ReactNode } from 'react'

export const money = (value: number) => new Intl.NumberFormat('zh-CN', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
}).format(value)

export const number = (value: number, digits = 2) => new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: digits, minimumFractionDigits: digits,
}).format(value)

export function Change({ value, suffix = '%' }: { value: number; suffix?: string }) {
  return <span className={value >= 0 ? 'positive' : 'negative'}>{value >= 0 ? '+' : ''}{number(value)}{suffix}</span>
}

export function Score({ value, compact = false }: { value: number; compact?: boolean }) {
  return (
    <div className={`score-ring ${compact ? 'score-ring-compact' : ''}`} style={{ '--score': `${value * 3.6}deg` } as React.CSSProperties}>
      <div><strong>{Math.round(value)}</strong>{!compact && <span>推荐度</span>}</div>
    </div>
  )
}

export function PageHeader({ eyebrow, title, description, action }: {
  eyebrow: string; title: string; description: string; action?: ReactNode
}) {
  return (
    <div className="page-header">
      <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>
      {action && <div className="page-actions">{action}</div>}
    </div>
  )
}

export function LoadingPanel({ label = '正在读取数据' }: { label?: string }) {
  return <div className="state-panel"><span className="loader" /><p>{label}</p></div>
}

export function ErrorPanel({ error }: { error: Error }) {
  return <div className="state-panel state-error"><strong>数据暂时不可用</strong><p>{error.message}</p><small>请确认 Python 网关已在 8000 端口启动。</small></div>
}

export function DataStamp({ value, mode = 'DEMO' }: { value?: string; mode?: string }) {
  return <div className="data-stamp"><span>{mode.toUpperCase()}</span>{value ? `更新时间 ${new Date(value).toLocaleString('zh-CN')}` : '演示数据'}</div>
}
