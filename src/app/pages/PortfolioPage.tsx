import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { AllocationChart, CorrelationHeatmap, PerformanceChart } from '../components/Charts'
import { Change, ErrorPanel, LoadingPanel, money, number, PageHeader } from '../components/UI'
import { api } from '../api'

export function PortfolioPage() {
  const { t } = useTranslation('portfolio')
  const [requestedPortfolioId, setRequestedPortfolioId] = useState('nisa')
  const portfolios = useQuery({ queryKey: ['portfolios'], queryFn: api.portfolios })
  const available = portfolios.data?.items ?? []
  const selectedPortfolioId = available.some((item) => item.id === requestedPortfolioId)
    ? requestedPortfolioId
    : available[0]?.id ?? requestedPortfolioId
  const selectedItem = available.find((item) => item.id === selectedPortfolioId)
  const queriesEnabled = portfolios.isSuccess && Boolean(selectedItem)
  const portfolio = useQuery({
    queryKey: ['portfolio', selectedPortfolioId],
    queryFn: () => api.portfolio(selectedPortfolioId),
    enabled: queriesEnabled,
  })
  const performance = useQuery({
    queryKey: ['performance', selectedPortfolioId],
    queryFn: () => api.performance(selectedPortfolioId),
    enabled: queriesEnabled,
  })
  const risk = useQuery({
    queryKey: ['portfolio-risk', selectedPortfolioId],
    queryFn: () => api.portfolioRisk(selectedPortfolioId),
    enabled: queriesEnabled && selectedItem?.account_type !== 'nisa',
  })

  if (portfolios.isPending) return <LoadingPanel label={t('loading')} />
  if (portfolios.error) return <ErrorPanel error={portfolios.error} />
  if (!selectedItem) return <ErrorPanel error={new Error(t('noPortfolio'))} />
  if (portfolio.isPending || performance.isPending) return <LoadingPanel label={t('loading')} />
  if (portfolio.error) return <ErrorPanel error={portfolio.error} />
  if (performance.error) return <ErrorPanel error={performance.error} />

  const data = portfolio.data
  const riskData = risk.data
  const currencyDigits = data.currency === 'JPY' ? 0 : 2
  const formatMoney = (value: number) => money(value, data.currency, currencyDigits)
  const accountLabel = data.account_type === 'nisa' ? t('nisaPortfolio') : t('paperPortfolio')

  return (
    <>
      <PageHeader
        eyebrow={t('eyebrow')}
        title={data.name}
        description={t('description')}
        action={(
          <div className="portfolio-switcher">
            <span className={data.account_type === 'nisa' ? 'account-pill account-pill-nisa' : 'paper-pill'}>{accountLabel}</span>
            <label>
              <span>{t('selectPortfolio')}</span>
              <select value={selectedPortfolioId} onChange={(event) => setRequestedPortfolioId(event.target.value)}>
                {available.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
          </div>
        )}
      />
      <section className="portfolio-summary">
        <div><span>{t('equity')}</span><strong>{formatMoney(data.equity)}</strong></div>
        <div><span>{t('marketValue')}</span><strong>{formatMoney(data.market_value)}</strong></div>
        <div><span>{t('costBasis')}</span><strong>{formatMoney(data.cost_basis)}</strong></div>
        <div><span>{t('unrealizedPnl')}</span><strong className={data.unrealized_pnl >= 0 ? 'positive' : 'negative'}>{data.unrealized_pnl >= 0 ? '+' : ''}{formatMoney(data.unrealized_pnl)}</strong></div>
      </section>
      <section className="dashboard-grid equal-grid">
        <article className="panel"><div className="panel-title"><div><span>ASSET ALLOCATION</span><h2>{t('allocation')}</h2></div></div><AllocationChart positions={data.positions} cash={data.cash} /></article>
        <article className="panel">
          <div className="panel-title"><div><span>EQUITY CURVE</span><h2>{t('equityCurve')}</h2></div></div>
          {performance.data.points.length > 1
            ? <PerformanceChart points={performance.data.points} valueMode />
            : <div className="empty-chart"><strong>{t('snapshotOnly')}</strong><span>{t('snapshotOnlyHint')}</span></div>}
        </article>
      </section>
      {data.account_type === 'nisa' && (
        <section className="panel portfolio-source-note">
          <strong>{t('snapshotTitle')}</strong>
          <span>{t('snapshotDescription')}</span>
        </section>
      )}
      {riskData && riskData.status === 'ok' && (
        <section className="panel">
          <div className="panel-title"><div><span>RISK ANALYTICS</span><h2>{t('risk.title')}</h2></div></div>
          {riskData.warnings.length > 0 && <p className="form-note">{riskData.warnings.join(' · ')}</p>}
          <div className="risk-metrics">
            <div><span>{t('risk.sharpe')}</span><strong>{riskData.portfolio?.sharpe ?? '—'}</strong></div>
            <div><span>{t('risk.vol')}</span><strong>{riskData.portfolio?.annualized_vol_pct != null ? `${riskData.portfolio.annualized_vol_pct}%` : '—'}</strong></div>
            <div><span>{t('risk.maxDrawdown')}</span><strong>{riskData.portfolio?.max_drawdown_pct != null ? `${riskData.portfolio.max_drawdown_pct}%` : '—'}</strong></div>
            <div><span>{t('risk.hhi')}</span><strong>{riskData.portfolio?.hhi ?? '—'}</strong></div>
            <div><span>{t('risk.effectiveN')}</span><strong>{riskData.portfolio?.effective_n ?? '—'}</strong></div>
          </div>
          <div className="dashboard-grid equal-grid">
            {riskData.correlation_matrix && (
              <article className="panel">
                <div className="panel-title"><div><span>CORRELATION</span><h2>{t('risk.correlation')}</h2></div></div>
                <CorrelationHeatmap matrix={riskData.correlation_matrix} />
              </article>
            )}
            <article className="panel">
              <div className="panel-title"><div><span>RISK PARITY</span><h2>{t('risk.suggestedWeights')}</h2></div></div>
              <div className="table-wrap"><table><thead><tr><th>{t('table.stock')}</th><th>{t('risk.current')}</th><th>{t('risk.suggested')}</th><th>{t('risk.contribution')}</th></tr></thead><tbody>{riskData.suggested_weights.map((item) => {
                const current = riskData.weights[item.symbol] ?? 0
                const contribution = riskData.contributions.find((entry) => entry.symbol === item.symbol)
                return <tr key={item.symbol}><td><strong>{item.symbol}</strong></td><td>{current.toFixed(2)}%</td><td>{item.weight_pct.toFixed(2)}%</td><td>{contribution?.contribution_pct != null ? `${contribution.contribution_pct.toFixed(2)}%` : '—'}</td></tr>
              })}</tbody></table></div>
              <p className="form-note">{t('risk.parityNote')}</p>
            </article>
          </div>
        </section>
      )}
      {riskData && riskData.status !== 'ok' && (
        <section className="panel">
          <div className="panel-title"><div><span>RISK ANALYTICS</span><h2>{t('risk.title')}</h2></div></div>
          <p className="form-note">{riskData.warnings.join(' · ') || t('risk.noData')}</p>
        </section>
      )}
      <section className="panel">
        <div className="panel-title"><div><span>OPEN POSITIONS</span><h2>{t('positions')}</h2></div></div>
        <div className="table-wrap"><table><thead><tr><th>{t('table.stock')}</th><th>{t('table.account')}</th><th>{t('table.quantity')}</th><th>{t('table.averageCost')}</th><th>{t('table.referencePrice')}</th><th>{t('table.marketValue')}</th><th>{t('table.weight')}</th><th>{t('table.pnl')}</th></tr></thead><tbody>{data.positions.map((position) => (
          <tr key={position.symbol}>
            <td className="fund-name"><strong>{position.name}</strong><small>{position.symbol}</small></td>
            <td>{position.account_bucket ? <span className={`account-bucket account-bucket-${position.account_bucket}`}>{t(`accountBucket.${position.account_bucket}`)}</span> : '—'}</td>
            <td>{number(position.quantity, 0)}</td>
            <td>{money(position.average_cost, position.currency, position.currency === 'JPY' ? 0 : 2)}</td>
            <td>{money(position.last_price, position.currency, position.currency === 'JPY' ? 0 : 2)}{position.price_scale > 1 && <small>{t('perUnits', { count: number(position.price_scale, 0) })}</small>}</td>
            <td>{money(position.market_value, position.currency, position.currency === 'JPY' ? 0 : 2)}</td>
            <td>{position.weight_pct.toFixed(2)}%</td>
            <td><Change value={position.unrealized_pnl_pct} /></td>
          </tr>
        ))}</tbody></table></div>
      </section>
    </>
  )
}
