import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, CircleGauge, Crosshair, Radar, WalletCards } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { Link } from '../router'
import { PerformanceChart } from '../components/Charts'
import { Change, DataStamp, ErrorPanel, LoadingPanel, money, PageHeader, Score } from '../components/UI'

export function DashboardPage() {
  const { t } = useTranslation('dashboard')
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard })
  if (dashboard.isPending) return <LoadingPanel label={t('loading')} />
  if (dashboard.error) return <ErrorPanel error={dashboard.error} />
  const data = dashboard.data
  const topPick = data.summary.top_pick

  return (
    <>
      <PageHeader
        eyebrow={t('eyebrow')}
        title={t('title')}
        description={t('description')}
        action={<div className="dashboard-actions"><DataStamp value={data.generated_at} mode={data.data_mode} /><Link to="/monitor" className="primary-button"><Radar />{t('enterMonitor')}</Link></div>}
      />

      <section className="kpi-grid">
        <article className="kpi-card kpi-featured">
          <div className="kpi-icon"><WalletCards /></div><span>{t('totalEquity')}</span>
          <strong>{money(data.portfolio.equity)}</strong>
          <small>{t('cashAndPositions', { cash: money(data.portfolio.cash), positions: money(data.portfolio.market_value) })}</small>
        </article>
        <article className="kpi-card">
          <div className="kpi-icon"><ArrowUpRight /></div><span>{t('periodReturn')}</span>
          <strong><Change value={data.summary.portfolio_return_pct} /></strong>
          <small>{t('aheadOfSpy')} <Change value={data.summary.alpha_pct} /></small>
        </article>
        <article className="kpi-card">
          <div className="kpi-icon"><Crosshair /></div><span>{t('topPick')}</span>
          <strong>{topPick?.symbol ?? '--'}</strong>
          <small>{topPick ? t('topPickDetail', { score: topPick.score, return: topPick.projected_return_pct }) : t('noRecommendation')}</small>
        </article>
        <article className="kpi-card">
          <div className="kpi-icon"><CircleGauge /></div><span>{t('riskPosture')}</span>
          <strong>{data.summary.risk_posture === 'balanced' ? t('balanced') : t('concentrated')}</strong>
          <small>{t('riskLimits')}</small>
        </article>
      </section>

      <section className="dashboard-grid">
        <article className="panel panel-wide">
          <div className="panel-title"><div><span>PERFORMANCE</span><h2>{t('performance')}</h2></div><Link to="/portfolio">{t('viewPortfolio')}</Link></div>
          <PerformanceChart points={data.performance.points} />
        </article>
        <article className="panel">
          <div className="panel-title"><div><span>AI SHORTLIST</span><h2>{t('todaysRecommendations')}</h2></div><Link to="/monitor?view=ai">{t('all')}</Link></div>
          <div className="recommendation-stack">
            {data.recommendations.map((item) => (
              <Link to={`/stocks/${item.symbol}`} className="recommendation-row" key={item.symbol}>
                <Score value={item.score} compact />
                <div><strong>{item.symbol}</strong><span>{item.name}</span></div>
                <div className="row-end"><Change value={item.projected_return_pct} /><small>{item.horizon}</small></div>
              </Link>
            ))}
          </div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-title"><div><span>POSITIONS</span><h2>{t('positions')}</h2></div><Link to="/trading">{t('paperTrade')}</Link></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t('table.stock')}</th><th>{t('table.quantity')}</th><th>{t('table.cost')}</th><th>{t('table.price')}</th><th>{t('table.marketValue')}</th><th>{t('table.weight')}</th><th>{t('table.pnl')}</th></tr></thead>
            <tbody>{data.portfolio.positions.map((position) => (
              <tr key={position.symbol}>
                <td><Link to={`/stocks/${position.symbol}`} className="symbol-cell"><strong>{position.symbol}</strong><span>{position.name}</span></Link></td>
                <td>{position.quantity}</td><td>{money(position.average_cost, 'USD', 2)}</td><td>{money(position.last_price, 'USD', 2)}</td>
                <td>{money(position.market_value)}</td><td>{position.weight_pct.toFixed(1)}%</td><td><Change value={position.unrealized_pnl_pct} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </>
  )
}
