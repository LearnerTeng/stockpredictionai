import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, Bot, CalendarClock, Database, ExternalLink, Newspaper, Play, TrendingUp } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { Link, useRouter } from '../router'
import { PriceChart, SimulationPnlChart } from '../components/Charts'
import { Change, ErrorPanel, LoadingPanel, money, PageHeader, Score } from '../components/UI'
import { currencyForMarket, type CurrencyCode } from '../i18n/format'
import type { PositionScenario, PriceBar } from '../types'

function ScenarioPanel({ scenario, currency }: { scenario: PositionScenario; currency: CurrencyCode }) {
  const { t } = useTranslation('stock')
  return (
    <article className="panel scenario-panel">
      <div className="panel-title">
        <div>
          <span>{scenario.id === 'manual' ? 'MANUAL ENTRY' : 'AI TIMING'}</span>
          <h2>{scenario.id === 'manual' ? t('manualEntry') : t('aiTiming')}</h2>
        </div>
        <strong className={scenario.pnl >= 0 ? 'positive' : 'negative'}>{money(scenario.pnl, currency)}</strong>
      </div>
      <div className="scenario-kpis">
        <div><span>{t('entryDate')}</span><strong>{scenario.entry_date}</strong></div>
        <div><span>{t('entryPrice')}</span><strong>{money(scenario.entry_price, currency, 2)}</strong></div>
        <div><span>{t('returnRate')}</span><strong><Change value={scenario.pnl_pct} /></strong></div>
        <div><span>{t('maxDrawdown')}</span><strong><Change value={scenario.max_drawdown_pct} /></strong></div>
      </div>
      <SimulationPnlChart points={scenario.points} />
      <div className="simulation-assessment">
        {scenario.assessment.map((item) => <p key={item}>{item}</p>)}
      </div>
      <div className="table-wrap scenario-table">
        <table>
          <thead><tr><th>{t('table.date')}</th><th>{t('table.close')}</th><th>{t('table.value')}</th><th>{t('table.pnl')}</th><th>{t('table.type')}</th></tr></thead>
          <tbody>
            {scenario.points.slice(-8).map((point) => (
              <tr key={`${scenario.id}-${point.trade_date}`}>
                <td>{point.trade_date}</td>
                <td>{money(point.close, currency, 2)}</td>
                <td>{money(point.value, currency)}</td>
                <td><Change value={point.pnl_pct} /></td>
                <td><span className={`order-status ${point.projected ? '' : 'status-paper_filled'}`}>{point.projected ? t('projected') : t('actual')}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  )
}

export function StockPage({ symbol }: { symbol: string }) {
  const { t } = useTranslation(['stock', 'sentiment'])
  const { searchParams } = useRouter()
  const [quantity, setQuantity] = useState('10')
  const [entryPrice, setEntryPrice] = useState('')
  const [forecastSteps, setForecastSteps] = useState('20')
  const detail = useQuery({ queryKey: ['monitor-stock', symbol], queryFn: () => api.monitorStock(symbol) })
  const bars = useQuery({ queryKey: ['bars', symbol], queryFn: () => api.bars(symbol), retry: false })
  const prediction = useQuery({ queryKey: ['prediction', symbol], queryFn: () => api.predict(symbol), retry: false })
  const sentiment = useQuery({ queryKey: ['sentiment-stock', symbol], queryFn: () => api.sentimentStock(symbol), retry: false })
  const simulation = useMutation({
    mutationFn: () => api.simulatePosition({
      symbol,
      quantity: Number(quantity),
      entry_price: entryPrice.trim() ? Number(entryPrice) : undefined,
      forecast_steps: Number(forecastSteps),
    }),
  })

  const chartBars = useMemo<PriceBar[]>(() => {
    const actualBars = bars.data?.items ?? []
    const projectedBars = simulation.data?.forecast_bars ?? []
    return [...actualBars, ...projectedBars]
  }, [bars.data?.items, simulation.data?.forecast_bars])

  if (detail.isPending) return <LoadingPanel label={t('loading', { symbol })} />
  if (detail.error) return <ErrorPanel error={detail.error} />
  const stock = detail.data
  const item = stock.recommendation ?? {
    symbol: stock.symbol,
    name: stock.name,
    score: stock.ai_score ?? 0,
    stance: 'monitoring',
    horizon: t('waitingScore'),
    latest_price: stock.latest_price ?? 0,
    projected_return_pct: stock.projected_return_pct ?? 0,
    components: { trend: 0, fundamental: 0, model: 0, market: 0, risk: 0 },
    thesis: t('noThesis'),
    risks: [],
    source: 'monitor-universe',
    generated_at: stock.updated_at ?? '',
  }
  const currency = currencyForMarket(stock.market)
  const latestPrice = simulation.data?.latest_bar.close ?? stock.latest_price ?? item.latest_price
  const future = prediction.data?.future_forecast
  const projectedMove = future?.delta_pct ?? item.projected_return_pct
  const quant = prediction.data?.quant_forecast
  const backTarget = searchParams.get('from') || '/monitor'

  return (
    <>
      <Link to={backTarget} className="back-link"><ArrowLeft size={16} />{t('back')}</Link>
      <PageHeader
        eyebrow={`${item.source} · ${item.horizon}`}
        title={`${stock.symbol} / ${stock.name}`}
        description={t('description')}
        action={<div className="stock-quote"><span>{t('referencePrice')}</span><strong>{money(latestPrice, currency, 2)}</strong><Change value={projectedMove} /></div>}
      />

      <section className="stock-command-grid">
        <article className="panel price-panel">
          <div className="panel-title">
            <div><span>MONITOR + FORECAST</span><h2>{t('chartTitle')}</h2></div>
            <small><Database size={14} /> {t('chartHint')}</small>
          </div>
          {bars.isPending ? <LoadingPanel /> : <PriceChart bars={chartBars} />}
        </article>
        <article className="panel score-panel stock-score-panel">
          <Score value={item.score} />
          <h2>{item.score >= 80 ? t('attention.high') : item.score >= 68 ? t('attention.positive') : t('attention.neutral')}</h2>
          <p>{item.thesis}</p>
          <div className="factor-list factor-list-large">
            {Object.entries(item.components).map(([key, value]) => (
              <div key={key}><span>{t(`factors.${key}`)}<b>{value}</b></span><i><em style={{ width: `${value}%` }} /></i></div>
            ))}
          </div>
          <div className="prediction-readout">
            <div><Bot /><span>{t('predictionStatus')}</span><strong>{prediction.isPending ? t('calculating') : prediction.error ? t('failed') : t('steps', { count: prediction.data?.forecast_steps ?? 0 })}</strong></div>
            <div><TrendingUp /><span>{t('predictionEnd')}</span><strong>{future ? money(future.predictions[future.predictions.length - 1], currency, 2) : '--'}</strong></div>
            {quant && <>
              <p>{quant.fallback_used ? t('baselineForecast') : t('registeredForecast')} · {quant.data_cutoff ?? quant.trained_until}</p>
              {quant.data_stale && <p className="negative">{t('staleForecast')}</p>}
              {quant.forecasts.map((forecast) => <div key={forecast.horizon_days}><span>{t('excessForecast', { days: forecast.horizon_days, benchmark: quant.objective.benchmark })}</span><strong><Change value={forecast.excess_return_pct} /></strong></div>)}
            </>}
          </div>
        </article>
      </section>

      <section className="stock-sentiment-grid">
        <article className="panel stock-sentiment-summary">
          <div className="panel-title"><div><span>NEWS SENTIMENT</span><h2>{t('sentiment:title')}</h2></div>{sentiment.data?.snapshot.negative_shock && <span className="negative"><AlertTriangle />{t('sentiment:shocks')}</span>}</div>
          {sentiment.isPending ? <LoadingPanel /> : sentiment.error ? <p className="muted-copy">{sentiment.error.message}</p> : <>
            <div className="sentiment-window-values">
              {(['score_1d', 'score_3d', 'score_7d'] as const).map((key, index) => <div key={key}><span>{[1, 3, 7][index]}D</span><strong>{sentiment.data.snapshot[key] === null ? '--' : <Change value={sentiment.data.snapshot[key] ?? 0} suffix="" />}</strong></div>)}
              <div><span>{t('sentiment:sources')}</span><strong>{sentiment.data.snapshot.source_count}</strong></div>
            </div>
            <div className="shadow-forecast">
              <div><Bot /><span>{t('stock:predictionStatus')}</span><strong>{prediction.data?.sentiment_shadow?.status ?? '...'}</strong></div>
              {prediction.data?.sentiment_shadow?.forecasts?.map((item) => <div key={item.horizon_days}><span>{item.horizon_days}D</span><strong><Change value={item.shadow_excess_return_pct} /></strong><small>{item.sentiment_adjustment_pct >= 0 ? '+' : ''}{item.sentiment_adjustment_pct.toFixed(2)}% sentiment</small></div>)}
            </div>
          </>}
        </article>
        <article className="panel stock-news-feed">
          <div className="panel-title"><div><span>TRACEABLE SOURCES</span><h2>{t('sentiment:latestNews')}</h2></div><Link to="/sentiment">{t('sentiment:marketScore')}</Link></div>
          <div className="news-list compact">
            {sentiment.data?.articles.slice(0, 6).map((article) => <div className="news-item" key={article.id}>
              <div className="news-meta"><span className={`sentiment-badge ${article.sentiment_label ?? 'pending'}`}>{article.sentiment_label ? t(`sentiment:labels.${article.sentiment_label}`) : t('sentiment:pending')}</span><time>{article.published_at.slice(0, 10)}</time></div>
              <h3>{article.url ? <a href={article.url} target="_blank" rel="noopener noreferrer">{article.title}<ExternalLink /></a> : article.title}</h3>
              <div className="news-source"><Newspaper />{article.source_domain || article.source}</div>
            </div>)}
            {!sentiment.isPending && !sentiment.data?.articles.length && <div className="empty-table">{t('sentiment:noData')}</div>}
          </div>
        </article>
      </section>

      <section className="panel simulation-ticket">
        <div className="panel-title">
          <div><span>PAPER POSITION SIMULATION</span><h2>{t('simulationTitle')}</h2></div>
          <button className="primary-button" onClick={() => simulation.mutate()} disabled={simulation.isPending || Number(quantity) <= 0}>
            <Play size={16} />{simulation.isPending ? t('simulating') : t('runSimulation')}
          </button>
        </div>
        <div className="simulation-form">
          <label>{t('quantity')}<input type="number" min="0.01" step="0.01" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
          <label>{t('entryPrice')}<input type="number" min="0.01" step="0.01" placeholder={t('defaultPrice', { price: money(latestPrice, currency, 2) })} value={entryPrice} onChange={(event) => setEntryPrice(event.target.value)} /></label>
          <label>{t('forecastDays')}<input type="number" min="1" max="60" value={forecastSteps} onChange={(event) => setForecastSteps(event.target.value)} /></label>
        </div>
        {simulation.error && <div className="inline-alert">{simulation.error.message}</div>}
      </section>

      {simulation.data ? (
        <>
          <section className="ai-entry-strip">
            <div><CalendarClock /><span>{t('aiEntry')}</span><strong>{simulation.data.ai_entry.trade_date} · {money(simulation.data.ai_entry.price, currency, 2)}</strong></div>
            <div><Score value={simulation.data.ai_entry.score} compact /><p>{simulation.data.ai_entry.reason}</p></div>
          </section>
          <section className="simulation-grid">
            {simulation.data.scenarios.map((scenario) => <ScenarioPanel key={scenario.id} scenario={scenario} currency={currency} />)}
          </section>
          <p className="disclaimer">{simulation.data.disclaimer}</p>
        </>
      ) : (
        <section className="panel assistant-empty">
          <TrendingUp />
          <h2>{t('waitingTitle')}</h2>
          <p>{t('waitingText')}</p>
        </section>
      )}
    </>
  )
}
