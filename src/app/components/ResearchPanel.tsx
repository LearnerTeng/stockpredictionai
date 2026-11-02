import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import type { UiLanguage } from '../types'

export function ResearchPanel() {
  const { t, i18n } = useTranslation('research')
  const [query, setQuery] = useState('')
  const [symbol, setSymbol] = useState('')
  const [mode, setMode] = useState('keyword')
  const [asOf, setAsOf] = useState('')
  const status = useQuery({ queryKey: ['research-status'], queryFn: api.researchStatus, refetchInterval: 60000 })
  const answer = useMutation({ mutationFn: () => api.researchAnswer(query, symbol.trim().toUpperCase(), mode,
    (i18n.resolvedLanguage ?? i18n.language) as UiLanguage, asOf ? new Date(asOf).toISOString() : undefined) })
  return <section className="panel analysis-result">
    <h2>{t('title')}</h2><p>{t('description')}</p>
    <form onSubmit={event => { event.preventDefault(); answer.mutate() }}>
      <label htmlFor="research-question">{t('question')}</label>
      <textarea id="research-question" value={query} onChange={e => setQuery(e.target.value)} maxLength={1000}
        rows={3} required style={{ width: '100%', margin: '8px 0' }} />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        <label>{t('symbol')}<input value={symbol} onChange={e => setSymbol(e.target.value)} maxLength={32} /></label>
        <label>{t('cutoff')}<input type="datetime-local" value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
        <label>{t('mode')}<select value={mode} onChange={e => setMode(e.target.value)}>
          <option value="keyword">{t('keyword')}</option><option value="vector">{t('vector')}</option><option value="hybrid">{t('hybrid')}</option>
        </select></label>
        <button className="primary-button" disabled={answer.isPending || !query.trim()}>{answer.isPending ? t('running') : t('submit')}</button>
      </div>
    </form>
    {status.data && <p className="form-note">{t('coverage', { documents: status.data.documents, ready: status.data.jobs.ready ?? 0,
      pending: (status.data.jobs.pending ?? 0) + (status.data.jobs.retry ?? 0), failed: status.data.jobs.failed ?? 0 })}</p>}
    {status.error && <p className="inline-alert">{t('unavailable')}</p>}
    {answer.error && <p className="inline-alert">{answer.error.message}</p>}
    {answer.data && <div>
      <p>{t(answer.data.status)}</p>
      {answer.data.claims.map((claim, index) => <section key={index}>
        <p>{claim.text} <a href={`#evidence-${claim.evidence_id}`} onClick={e => { e.preventDefault(); document.getElementById(`evidence-${claim.evidence_id}`)?.scrollIntoView() }}>[{answer.data.evidence.items.findIndex(item => item.id === claim.evidence_id) + 1}]</a></p>
        <blockquote>{claim.quote}</blockquote>
      </section>)}
      {answer.data.evidence.items.length > 0 && <h3>{t('sources')}</h3>}
      {answer.data.evidence.items.map((item, index) => <details key={item.id} id={`evidence-${item.id}`}>
        <summary>[{index + 1}] {item.title} · {item.source}</summary>
        <p>{item.text}</p><small>{t('available', { date: new Date(item.available_at).toLocaleString(), revision: item.revision })}</small>
        {item.url && /^https?:\/\//i.test(item.url) && <p><a href={item.url} target="_blank" rel="noreferrer">{t('original')}</a></p>}
      </details>)}
      <small>{t('saved', { id: answer.data.id })}</small>
    </div>}
  </section>
}
