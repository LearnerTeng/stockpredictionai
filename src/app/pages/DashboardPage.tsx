import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, CircleGauge, Crosshair, WalletCards } from 'lucide-react'
import { api } from '../api'
import { Link } from '../router'
import { PerformanceChart } from '../components/Charts'
import { Change, DataStamp, ErrorPanel, LoadingPanel, money, PageHeader, Score } from '../components/UI'

export function DashboardPage() {
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard })
  if (dashboard.isPending) return <LoadingPanel label="正在加载投资组合" />
  if (dashboard.error) return <ErrorPanel error={dashboard.error} />
  const data = dashboard.data
  const topPick = data.summary.top_pick

  return (
    <>
      <PageHeader
        eyebrow="Portfolio command center"
        title="早上好，这是你的市场驾驶舱"
        description="推荐来自确定性评分模型，AI 负责解释；所有交易均处于模拟盘。"
        action={<DataStamp value={data.generated_at} mode={data.data_mode} />}
      />

      <section className="kpi-grid">
        <article className="kpi-card kpi-featured">
          <div className="kpi-icon"><WalletCards /></div><span>组合总资产</span>
          <strong>{money(data.portfolio.equity)}</strong>
          <small>现金 {money(data.portfolio.cash)} · 持仓 {money(data.portfolio.market_value)}</small>
        </article>
        <article className="kpi-card">
          <div className="kpi-icon"><ArrowUpRight /></div><span>区间收益</span>
          <strong><Change value={data.summary.portfolio_return_pct} /></strong>
          <small>领先 SPY <Change value={data.summary.alpha_pct} /></small>
        </article>
        <article className="kpi-card">
          <div className="kpi-icon"><Crosshair /></div><span>首选股票</span>
          <strong>{topPick?.symbol ?? '--'}</strong>
          <small>{topPick ? `推荐度 ${topPick.score} · 预期 ${topPick.projected_return_pct}%` : '暂无推荐'}</small>
        </article>
        <article className="kpi-card">
          <div className="kpi-icon"><CircleGauge /></div><span>风险姿态</span>
          <strong>{data.summary.risk_posture === 'balanced' ? '均衡' : '偏满仓'}</strong>
          <small>单笔上限 $10,000 · 单股上限 25%</small>
        </article>
      </section>

      <section className="dashboard-grid">
        <article className="panel panel-wide">
          <div className="panel-title"><div><span>PERFORMANCE</span><h2>我的收益 vs 市场</h2></div><Link to="/portfolio">查看组合</Link></div>
          <PerformanceChart points={data.performance.points} />
        </article>
        <article className="panel">
          <div className="panel-title"><div><span>AI SHORTLIST</span><h2>今日推荐</h2></div><Link to="/recommendations">全部</Link></div>
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
        <div className="panel-title"><div><span>POSITIONS</span><h2>当前持仓</h2></div><Link to="/trading">模拟交易</Link></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>股票</th><th>数量</th><th>成本</th><th>现价</th><th>市值</th><th>持仓占比</th><th>浮动盈亏</th></tr></thead>
            <tbody>{data.portfolio.positions.map((position) => (
              <tr key={position.symbol}>
                <td><Link to={`/stocks/${position.symbol}`} className="symbol-cell"><strong>{position.symbol}</strong><span>{position.name}</span></Link></td>
                <td>{position.quantity}</td><td>${position.average_cost.toFixed(2)}</td><td>${position.last_price.toFixed(2)}</td>
                <td>{money(position.market_value)}</td><td>{position.weight_pct.toFixed(1)}%</td><td><Change value={position.unrealized_pnl_pct} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </>
  )
}
