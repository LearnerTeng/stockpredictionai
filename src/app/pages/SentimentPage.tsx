import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ExternalLink, Mail, Newspaper, RefreshCw, Settings2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { formatDateTime } from '../i18n/format'
import { Change, DataStamp, ErrorPanel, LoadingPanel, number, PageHeader } from '../components/UI'
import type { SentimentArticle, SentimentSettings } from '../types'

const windows = ['24h', '3d', '7d'] as const
const markets = ['', 'US', 'JP'] as const

function SentimentBadge({ article }: { article: SentimentArticle }) {
  const { t } = useTranslation('sentiment')
  if (!article.sentiment_label) return <span className="sentiment-badge pending">{t('pending')}</span>
  return <span className={`sentiment-badge ${article.sentiment_label}`}>{t(`labels.${article.sentiment_label}`)}</span>
}

export function SentimentPage() {
  const { t, i18n } = useTranslation(['sentiment', 'common'])
  const queryClient = useQueryClient()
  const [windowValue, setWindowValue] = useState<typeof windows[number]>('24h')
  const [market, setMarket] = useState<typeof markets[number]>('')
  const [symbol, setSymbol] = useState('')
  const [label, setLabel] = useState('')
  const [tier, setTier] = useState('')
  const [source, setSource] = useState('')
  const [eventType, setEventType] = useState('')
  const [page, setPage] = useState(1)
  const [showSettings, setShowSettings] = useState(false)
  const [recipients, setRecipients] = useState('')
  const [notice, setNotice] = useState('')

  const filters = { window: windowValue, market, symbol, label, source_tier: tier, source, event_type: eventType, page, page_size: 40 }
  const query = useQuery({ queryKey: ['sentiment-overview', filters], queryFn: () => api.sentimentOverview(filters) })
  const settings = useQuery({ queryKey: ['sentiment-settings'], queryFn: api.sentimentSettings })
  useEffect(() => setRecipients((settings.data?.email_recipients ?? []).join(', ')), [settings.data?.email_recipients])

  const refresh = useMutation({
    mutationFn: () => api.refreshSentiment({ mode: 'incremental', markets: market ? [market] : ['US', 'JP'] }),
    onSuccess: (result) => setNotice(t('sentiment:queued', { id: result.job.id.slice(0, 8) })),
  })
  const saveSettings = useMutation({
    mutationFn: (payload: Partial<SentimentSettings>) => api.updateSentimentSettings(payload),
    onSuccess: (value) => {
      queryClient.setQueryData(['sentiment-settings'], value)
      setNotice(t('sentiment:settingsSaved'))
    },
  })

  if (query.isPending) return <LoadingPanel label={t('sentiment:loading')} />
  if (query.error) return <ErrorPanel error={query.error} />
  const data = query.data
  const score = data.summary.score

  return (
    <>
      <PageHeader
        eyebrow={t('sentiment:eyebrow')}
        title={t('sentiment:title')}
        description={t('sentiment:description')}
        action={<div className="sentiment-page-actions"><DataStamp value={data.generated_at} mode="NEWS" /><button className="secondary-button" onClick={() => setShowSettings((value) => !value)}><Settings2 />{t('sentiment:settings')}</button><button className="primary-button" disabled={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw className={refresh.isPending ? 'spin' : ''} />{t('sentiment:refresh')}</button></div>}
      />

      {(notice || refresh.error || saveSettings.error) && <div className={`inline-alert ${refresh.error || saveSettings.error ? '' : 'notice-success'}`}>{refresh.error?.message ?? saveSettings.error?.message ?? notice}</div>}

      {showSettings && <section className="panel sentiment-settings">
        <div className="panel-title"><div><span>SERVER SCHEDULE</span><h2>{t('sentiment:settingsTitle')}</h2></div><span className={`smtp-state ${settings.data?.smtp_configured ? 'ready' : ''}`}><Mail />{settings.data?.smtp_configured ? t('sentiment:smtpReady') : t('sentiment:smtpMissing')}</span></div>
        <div className="sentiment-settings-grid">
          <label>{t('sentiment:interval')}<input type="number" min="5" max="1440" value={settings.data?.interval_minutes ?? 30} onChange={(event) => queryClient.setQueryData<SentimentSettings>(['sentiment-settings'], (current) => current ? { ...current, interval_minutes: Number(event.target.value) } : current)} /></label>
          <label>{t('sentiment:recipients')}<input value={recipients} onChange={(event) => setRecipients(event.target.value)} placeholder="name@example.com" /></label>
          <label className="settings-check"><input type="checkbox" checked={settings.data?.email_enabled ?? false} onChange={(event) => queryClient.setQueryData<SentimentSettings>(['sentiment-settings'], (current) => current ? { ...current, email_enabled: event.target.checked } : current)} />{t('sentiment:emailAlerts')}</label>
          <button className="secondary-button" onClick={() => saveSettings.mutate({ interval_minutes: settings.data?.interval_minutes ?? 30, email_enabled: settings.data?.email_enabled ?? false, email_recipients: recipients.split(',').map((value) => value.trim()).filter(Boolean), notification_language: i18n.resolvedLanguage as 'zh-CN' | 'en' | 'ja' })}>{t('common:actions.save')}</button>
        </div>
      </section>}

      <section className="panel sentiment-toolbar">
        <div className="sentiment-segments">{windows.map((item) => <button key={item} className={windowValue === item ? 'active' : ''} onClick={() => { setWindowValue(item); setPage(1) }}>{item}</button>)}</div>
        <div className="sentiment-segments">{markets.map((item) => <button key={item || 'all'} className={market === item ? 'active' : ''} onClick={() => { setMarket(item); setPage(1) }}>{t(`common:market.${item || 'all'}`)}</button>)}</div>
        <input value={symbol} onChange={(event) => { setSymbol(event.target.value.toUpperCase()); setPage(1) }} placeholder={t('sentiment:symbolFilter')} />
        <select value={label} onChange={(event) => { setLabel(event.target.value); setPage(1) }}><option value="">{t('sentiment:allSentiment')}</option><option value="positive">{t('sentiment:labels.positive')}</option><option value="neutral">{t('sentiment:labels.neutral')}</option><option value="negative">{t('sentiment:labels.negative')}</option></select>
        <select value={tier} onChange={(event) => { setTier(event.target.value); setPage(1) }}><option value="">{t('sentiment:allSources')}</option><option value="primary">{t('sentiment:primary')}</option><option value="secondary">{t('sentiment:secondary')}</option></select>
        <input value={source} onChange={(event) => { setSource(event.target.value); setPage(1) }} placeholder={t('sentiment:mediaFilter')} />
        <select value={eventType} onChange={(event) => { setEventType(event.target.value); setPage(1) }}><option value="">{t('sentiment:allEvents')}</option>{['earnings', 'guidance', 'merger_acquisition', 'regulatory', 'macro', 'product', 'management', 'legal', 'analyst', 'other'].map((item) => <option key={item} value={item}>{t(`sentiment:events.${item}`)}</option>)}</select>
      </section>

      <section className="sentiment-kpis">
        <div><span>{t('sentiment:marketScore')}</span><strong className={score === null ? '' : score >= 0 ? 'positive' : 'negative'}>{score === null ? '--' : number(score, 3)}</strong></div>
        <div><span>{t('sentiment:articles')}</span><strong>{data.summary.articles}</strong></div>
        <div><span>{t('sentiment:distribution')}</span><strong><i className="positive">{data.summary.positive}</i> / {data.summary.neutral} / <i className="negative">{data.summary.negative}</i></strong></div>
        <div><span>{t('sentiment:shocks')}</span><strong className={data.summary.negative_shocks ? 'negative' : ''}>{data.summary.negative_shocks}</strong></div>
      </section>

      <section className="panel sentiment-trend">
        <div className="panel-title"><div><span>30 DAY HISTORY</span><h2>{t('sentiment:trend')}</h2></div></div>
        <div className="sentiment-trend-chart">
          {data.trend.map((item) => <div key={item.date} title={`${item.date} ${number(item.score, 3)}`}><i className={item.score >= 0 ? 'up' : 'down'} style={{ height: `${Math.max(Math.abs(item.score) * 42, 2)}px` }} /><span>{item.date.slice(5)}</span></div>)}
          {!data.trend.length && <p>{t('sentiment:noTrend')}</p>}
        </div>
      </section>

      <section className="sentiment-layout">
        <article className="panel sentiment-ranking">
          <div className="panel-title"><div><span>SYMBOL SIGNALS</span><h2>{t('sentiment:ranking')}</h2></div></div>
          <div className="table-wrap"><table><thead><tr><th>{t('sentiment:symbol')}</th><th>1D</th><th>3D</th><th>7D</th><th>{t('sentiment:sources')}</th></tr></thead><tbody>
            {data.symbols.map((item) => <tr key={item.symbol}><td><strong>{item.symbol}</strong>{item.negative_shock && <AlertTriangle className="shock-icon" />}</td><td>{item.score_1d === null ? '--' : <Change value={item.score_1d} suffix="" />}</td><td>{item.score_3d === null ? '--' : <Change value={item.score_3d} suffix="" />}</td><td>{item.score_7d === null ? '--' : <Change value={item.score_7d} suffix="" />}</td><td>{item.source_count}</td></tr>)}
            {!data.symbols.length && <tr><td colSpan={5} className="empty-table">{t('sentiment:noData')}</td></tr>}
          </tbody></table></div>
        </article>

        <article className="panel sentiment-feed">
          <div className="panel-title"><div><span>TRACEABLE SOURCES</span><h2>{t('sentiment:latestNews')}</h2></div><small>{t('sentiment:resultCount', { count: data.total })}</small></div>
          <div className="news-list">
            {data.articles.map((article) => <div className="news-item" key={`${article.id}-${article.symbol}`}>
              <div className="news-meta"><strong>{article.symbol}</strong><SentimentBadge article={article} /><span className={`source-tier ${article.source_tier}`}>{article.source_tier === 'primary' ? t('sentiment:primary') : t('sentiment:secondary')}</span><time>{formatDateTime(article.published_at)}</time></div>
              <h3>{article.url ? <a href={article.url} target="_blank" rel="noopener noreferrer">{article.title}<ExternalLink /></a> : article.title}</h3>
              {article.summary && <p>{article.summary}</p>}
              <div className="news-source"><Newspaper />{article.source_domain || article.source}{article.event_type && <span>{t(`sentiment:events.${article.event_type}`)}</span>}{article.sentiment_score !== null && <b>{number(article.sentiment_score, 3)}</b>}</div>
            </div>)}
            {!data.articles.length && <div className="empty-table">{t('sentiment:noData')}</div>}
          </div>
          {data.pages > 1 && <div className="sentiment-pagination"><button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>{t('sentiment:previous')}</button><span>{page} / {data.pages}</span><button disabled={page >= data.pages} onClick={() => setPage((value) => value + 1)}>{t('sentiment:next')}</button></div>}
        </article>
      </section>

      <section className="panel coverage-strip"><strong>{t('sentiment:coverage')}</strong>{data.coverage.slice(0, 12).map((item) => <span key={`${item.provider}-${item.symbol}`}><b>{item.symbol}</b>{item.provider} · {item.coverage_start ? formatDateTime(item.coverage_start) : '--'} → {item.coverage_end ? formatDateTime(item.coverage_end) : '--'}</span>)}</section>
      <p className="disclaimer">{t('sentiment:disclaimer')}</p>
    </>
  )
}
