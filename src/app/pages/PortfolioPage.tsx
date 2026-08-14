import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { AllocationChart, PerformanceChart } from '../components/Charts'
import { Change, ErrorPanel, LoadingPanel, money, PageHeader } from '../components/UI'
import { api } from '../api'

export function PortfolioPage() {
  const { t } = useTranslation('portfolio')
  const portfolio = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })
  const performance = useQuery({ queryKey: ['performance'], queryFn: api.performance })
  if (portfolio.isPending || performance.isPending) return <LoadingPanel label={t('loading')} />
  if (portfolio.error) return <ErrorPanel error={portfolio.error} />
  if (performance.error) return <ErrorPanel error={performance.error} />
  const data = portfolio.data

  return (
    <>
      <PageHeader eyebrow={t('eyebrow')} title={t('title')} description={t('description')} action={<span className="paper-pill">{t('paperPortfolio')}</span>} />
      <section className="portfolio-summary">
        <div><span>{t('equity')}</span><strong>{money(data.equity)}</strong></div>
        <div><span>{t('marketValue')}</span><strong>{money(data.market_value)}</strong></div>
        <div><span>{t('cash')}</span><strong>{money(data.cash)}</strong></div>
        <div><span>{t('unrealizedPnl')}</span><strong>{money(data.unrealized_pnl)}</strong></div>
      </section>
      <section className="dashboard-grid equal-grid">
        <article className="panel"><div className="panel-title"><div><span>ASSET ALLOCATION</span><h2>{t('allocation')}</h2></div></div><AllocationChart positions={data.positions} cash={data.cash} /></article>
        <article className="panel"><div className="panel-title"><div><span>EQUITY CURVE</span><h2>{t('equityCurve')}</h2></div></div><PerformanceChart points={performance.data.points} valueMode /></article>
      </section>
      <section className="panel">
        <div className="panel-title"><div><span>OPEN POSITIONS</span><h2>{t('positions')}</h2></div></div>
        <div className="table-wrap"><table><thead><tr><th>{t('table.stock')}</th><th>{t('table.quantity')}</th><th>{t('table.averageCost')}</th><th>{t('table.referencePrice')}</th><th>{t('table.marketValue')}</th><th>{t('table.weight')}</th><th>{t('table.pnl')}</th></tr></thead><tbody>{data.positions.map((position) => <tr key={position.symbol}><td><strong>{position.symbol}</strong><small>{position.name}</small></td><td>{position.quantity}</td><td>{money(position.average_cost, 'USD', 2)}</td><td>{money(position.last_price, 'USD', 2)}</td><td>{money(position.market_value)}</td><td>{position.weight_pct.toFixed(2)}%</td><td><Change value={position.unrealized_pnl_pct} /></td></tr>)}</tbody></table></div>
      </section>
    </>
  )
}
