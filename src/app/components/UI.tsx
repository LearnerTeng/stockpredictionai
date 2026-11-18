import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { formatDateTime, formatMoney, formatNumber, type CurrencyCode } from '../i18n/format'

export const money = (value: number, currency: CurrencyCode = 'USD', maximumFractionDigits = 0) => formatMoney(value, currency, maximumFractionDigits)
export const number = (value: number, digits = 2) => formatNumber(value, digits)

export function Change({ value, suffix = '%' }: { value: number; suffix?: string }) {
  return <span className={value >= 0 ? 'positive' : 'negative'}>{value >= 0 ? '+' : ''}{number(value)}{suffix}</span>
}

export function Score({ value, compact = false }: { value: number; compact?: boolean }) {
  const { t } = useTranslation('common')
  return (
    <div className={`score-ring ${compact ? 'score-ring-compact' : ''}`} style={{ '--score': `${value * 3.6}deg` } as React.CSSProperties}>
      <div><strong>{Math.round(value)}</strong>{!compact && <span>{t('recommendationScore')}</span>}</div>
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

export function LoadingPanel({ label }: { label?: string }) {
  const { t } = useTranslation('common')
  return <div className="state-panel"><span className="loader" /><p>{label ?? t('loading')}</p></div>
}

export function ErrorPanel({ error }: { error: Error }) {
  const { t } = useTranslation('common')
  return <div className="state-panel state-error"><strong>{t('errorTitle')}</strong><p>{error.message}</p><small>{t('errorHint')}</small></div>
}

export function DataStamp({ value, mode = 'DEMO' }: { value?: string; mode?: string }) {
  const { t } = useTranslation('common')
  return <div className="data-stamp"><span>{mode.toUpperCase()}</span>{value ? t('updatedAt', { value: formatDateTime(value) }) : t('demoData')}</div>
}
