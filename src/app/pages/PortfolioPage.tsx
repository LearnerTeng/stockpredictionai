import { useQuery } from '@tanstack/react-query'
import { AllocationChart, PerformanceChart } from '../components/Charts'
import { Change, ErrorPanel, LoadingPanel, money, PageHeader } from '../components/UI'
import { api } from '../api'

export function PortfolioPage() {
  const portfolio = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })
  const performance = useQuery({ queryKey: ['performance'], queryFn: api.performance })
  if (portfolio.isPending || performance.isPending) return <LoadingPanel label="正在计算组合收益" />
  if (portfolio.error) return <ErrorPanel error={portfolio.error} />
  if (performance.error) return <ErrorPanel error={performance.error} />
  const data = portfolio.data

  return (
    <>
      <PageHeader eyebrow="Portfolio analytics" title="我的投资组合" description="持仓、现金、资产配置与基准收益集中展示。" action={<span className="paper-pill">PAPER PORTFOLIO</span>} />
      <section className="portfolio-summary">
        <div><span>净资产</span><strong>{money(data.equity)}</strong></div>
        <div><span>持仓市值</span><strong>{money(data.market_value)}</strong></div>
        <div><span>可用现金</span><strong>{money(data.cash)}</strong></div>
        <div><span>未实现盈亏</span><strong><Change value={data.unrealized_pnl} suffix=" USD" /></strong></div>
      </section>
      <section className="dashboard-grid equal-grid">
        <article className="panel"><div className="panel-title"><div><span>ASSET ALLOCATION</span><h2>资产配置</h2></div></div><AllocationChart positions={data.positions} cash={data.cash} /></article>
        <article className="panel"><div className="panel-title"><div><span>EQUITY CURVE</span><h2>资产曲线</h2></div></div><PerformanceChart points={performance.data.points} valueMode /></article>
      </section>
      <section className="panel">
        <div className="panel-title"><div><span>OPEN POSITIONS</span><h2>持仓明细</h2></div></div>
        <div className="table-wrap"><table><thead><tr><th>股票</th><th>数量</th><th>平均成本</th><th>参考价格</th><th>市值</th><th>权重</th><th>盈亏</th></tr></thead><tbody>{data.positions.map((position) => <tr key={position.symbol}><td><strong>{position.symbol}</strong><small>{position.name}</small></td><td>{position.quantity}</td><td>${position.average_cost.toFixed(2)}</td><td>${position.last_price.toFixed(2)}</td><td>{money(position.market_value)}</td><td>{position.weight_pct.toFixed(2)}%</td><td><Change value={position.unrealized_pnl_pct} /></td></tr>)}</tbody></table></div>
      </section>
    </>
  )
}
