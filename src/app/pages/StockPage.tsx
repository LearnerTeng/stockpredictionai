import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Bot, CalendarClock, Database, Play, TrendingUp } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api } from '../api'
import { Link } from '../router'
import { PriceChart, SimulationPnlChart } from '../components/Charts'
import { Change, ErrorPanel, LoadingPanel, money, number, PageHeader, Score } from '../components/UI'
import type { PositionScenario, PriceBar } from '../types'

const labels: Record<string, string> = {
  trend: '趋势',
  fundamental: '基本面',
  model: '模型',
  market: '市场',
  risk: '风险',
}

function ScenarioPanel({ scenario }: { scenario: PositionScenario }) {
  return (
    <article className="panel scenario-panel">
      <div className="panel-title">
        <div>
          <span>{scenario.id === 'manual' ? 'MANUAL ENTRY' : 'AI TIMING'}</span>
          <h2>{scenario.id === 'manual' ? '手动买入模拟' : 'AI 建议时点模拟'}</h2>
        </div>
        <strong className={scenario.pnl >= 0 ? 'positive' : 'negative'}>{money(scenario.pnl)}</strong>
      </div>
      <div className="scenario-kpis">
        <div><span>买入日</span><strong>{scenario.entry_date}</strong></div>
        <div><span>买入价</span><strong>${number(scenario.entry_price)}</strong></div>
        <div><span>收益率</span><strong><Change value={scenario.pnl_pct} /></strong></div>
        <div><span>最大回撤</span><strong><Change value={scenario.max_drawdown_pct} /></strong></div>
      </div>
      <SimulationPnlChart points={scenario.points} />
      <div className="simulation-assessment">
        {scenario.assessment.map((item) => <p key={item}>{item}</p>)}
      </div>
      <div className="table-wrap scenario-table">
        <table>
          <thead><tr><th>日期</th><th>收盘</th><th>市值</th><th>盈亏</th><th>类型</th></tr></thead>
          <tbody>
            {scenario.points.slice(-8).map((point) => (
              <tr key={`${scenario.id}-${point.trade_date}`}>
                <td>{point.trade_date}</td>
                <td>${number(point.close)}</td>
                <td>{money(point.value)}</td>
                <td><Change value={point.pnl_pct} /></td>
                <td><span className={`order-status ${point.projected ? '' : 'status-paper_filled'}`}>{point.projected ? '预测' : '实际'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  )
}

export function StockPage({ symbol }: { symbol: string }) {
  const [quantity, setQuantity] = useState('10')
  const [entryPrice, setEntryPrice] = useState('')
  const [forecastSteps, setForecastSteps] = useState('20')
  const recommendation = useQuery({ queryKey: ['recommendation', symbol], queryFn: () => api.recommendation(symbol) })
  const bars = useQuery({ queryKey: ['bars', symbol], queryFn: () => api.bars(symbol), retry: false })
  const prediction = useQuery({ queryKey: ['prediction', symbol], queryFn: () => api.predict(symbol), retry: false })
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

  if (recommendation.isPending) return <LoadingPanel label={`正在读取 ${symbol}`} />
  if (recommendation.error) return <ErrorPanel error={recommendation.error} />
  const item = recommendation.data
  const latestPrice = simulation.data?.latest_bar.close ?? item.latest_price
  const projectedMove = prediction.data
    ? ((prediction.data.predictions[prediction.data.predictions.length - 1] - latestPrice) / latestPrice) * 100
    : item.projected_return_pct

  return (
    <>
      <Link to="/recommendations" className="back-link"><ArrowLeft size={16} />返回推荐列表</Link>
      <PageHeader
        eyebrow={`${item.source} · ${item.horizon}`}
        title={`${item.symbol} / ${item.name}`}
        description="单股监控、模型预测、手动买入模拟和 AI 建议买点收益在同一画面完成。"
        action={<div className="stock-quote"><span>参考价格</span><strong>${number(latestPrice)}</strong><Change value={projectedMove} /></div>}
      />

      <section className="stock-command-grid">
        <article className="panel price-panel">
          <div className="panel-title">
            <div><span>MONITOR + FORECAST</span><h2>K 线监控与预测投影</h2></div>
            <small><Database size={14} /> 实线为实际行情，右侧为模型投影</small>
          </div>
          {bars.isPending ? <LoadingPanel /> : <PriceChart bars={chartBars} />}
        </article>
        <article className="panel score-panel stock-score-panel">
          <Score value={item.score} />
          <h2>{item.score >= 80 ? '高关注' : item.score >= 68 ? '积极观察' : '中性观察'}</h2>
          <p>{item.thesis}</p>
          <div className="factor-list factor-list-large">
            {Object.entries(item.components).map(([key, value]) => (
              <div key={key}><span>{labels[key]}<b>{value}</b></span><i><em style={{ width: `${value}%` }} /></i></div>
            ))}
          </div>
          <div className="prediction-readout">
            <div><Bot /><span>预测状态</span><strong>{prediction.isPending ? '计算中' : prediction.error ? '失败' : `${prediction.data?.forecast_steps ?? 0} 步`}</strong></div>
            <div><TrendingUp /><span>预测末端</span><strong>{prediction.data ? `$${number(prediction.data.predictions[prediction.data.predictions.length - 1] ?? latestPrice)}` : '--'}</strong></div>
          </div>
        </article>
      </section>

      <section className="panel simulation-ticket">
        <div className="panel-title">
          <div><span>PAPER POSITION SIMULATION</span><h2>输入模拟买入参数</h2></div>
          <button className="primary-button" onClick={() => simulation.mutate()} disabled={simulation.isPending || Number(quantity) <= 0}>
            <Play size={16} />{simulation.isPending ? '模拟中...' : '运行收益模拟'}
          </button>
        </div>
        <div className="simulation-form">
          <label>数量<input type="number" min="0.01" step="0.01" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
          <label>买入价<input type="number" min="0.01" step="0.01" placeholder={`默认 ${number(latestPrice)}`} value={entryPrice} onChange={(event) => setEntryPrice(event.target.value)} /></label>
          <label>预测交易日<input type="number" min="1" max="60" value={forecastSteps} onChange={(event) => setForecastSteps(event.target.value)} /></label>
        </div>
        {simulation.error && <div className="inline-alert">{simulation.error.message}</div>}
      </section>

      {simulation.data ? (
        <>
          <section className="ai-entry-strip">
            <div><CalendarClock /><span>AI 建议买点</span><strong>{simulation.data.ai_entry.trade_date} · ${number(simulation.data.ai_entry.price)}</strong></div>
            <div><Score value={simulation.data.ai_entry.score} compact /><p>{simulation.data.ai_entry.reason}</p></div>
          </section>
          <section className="simulation-grid">
            {simulation.data.scenarios.map((scenario) => <ScenarioPanel key={scenario.id} scenario={scenario} />)}
          </section>
          <p className="disclaimer">{simulation.data.disclaimer}</p>
        </>
      ) : (
        <section className="panel assistant-empty">
          <TrendingUp />
          <h2>等待模拟参数</h2>
          <p>输入数量和可选买入价后，系统会生成手动买入与 AI 建议买入时点两套 K 线收益路径。</p>
        </section>
      )}
    </>
  )
}
