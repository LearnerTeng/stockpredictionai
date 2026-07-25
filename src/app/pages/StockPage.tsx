import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Bot, Clock3, Database } from 'lucide-react'
import { api } from '../api'
import { Link } from '../router'
import { PriceChart } from '../components/Charts'
import { Change, ErrorPanel, LoadingPanel, PageHeader, Score } from '../components/UI'

const labels: Record<string, string> = { trend: '趋势', fundamental: '基本面', model: '预测模型', market: '市场环境', risk: '风险调整' }

export function StockPage({ symbol }: { symbol: string }) {
  const recommendation = useQuery({ queryKey: ['recommendation', symbol], queryFn: () => api.recommendation(symbol) })
  const bars = useQuery({ queryKey: ['bars', symbol], queryFn: () => api.bars(symbol), retry: false })
  if (recommendation.isPending) return <LoadingPanel label={`正在读取 ${symbol}`} />
  if (recommendation.error) return <ErrorPanel error={recommendation.error} />
  const item = recommendation.data

  return (
    <>
      <Link to="/recommendations" className="back-link"><ArrowLeft size={16} />返回推荐列表</Link>
      <PageHeader
        eyebrow={`${item.source} · ${item.horizon}`}
        title={`${item.symbol} / ${item.name}`}
        description={item.thesis}
        action={<div className="stock-quote"><span>参考价格</span><strong>${item.latest_price.toFixed(2)}</strong><Change value={item.projected_return_pct} /></div>}
      />
      <section className="stock-hero-grid">
        <article className="panel price-panel">
          <div className="panel-title"><div><span>PRICE ACTION</span><h2>历史行情</h2></div><small><Database size={14} /> 本地数据库</small></div>
          {bars.isPending ? <LoadingPanel /> : <PriceChart bars={bars.data?.items ?? []} />}
        </article>
        <article className="panel score-panel">
          <Score value={item.score} />
          <h2>{item.score >= 80 ? '高关注' : item.score >= 68 ? '积极观察' : '中性观察'}</h2>
          <p>推荐度是多因子排序结果，不代表上涨概率。</p>
          <div className="factor-list factor-list-large">
            {Object.entries(item.components).map(([key, value]) => <div key={key}><span>{labels[key]}<b>{value}</b></span><i><em style={{ width: `${value}%` }} /></i></div>)}
          </div>
        </article>
      </section>
      <section className="three-column-grid">
        <article className="panel info-card"><Bot /><span>模型观点</span><strong>{item.projected_return_pct >= 0 ? '偏多' : '谨慎'}</strong><p>未来 {item.horizon} 预期变化 <Change value={item.projected_return_pct} />。</p></article>
        <article className="panel info-card"><Clock3 /><span>分析时间</span><strong>{new Date(item.generated_at).toLocaleDateString('zh-CN')}</strong><p>任何交易前应刷新价格和风险检查。</p></article>
        <article className="panel info-card risk-card"><Database /><span>风险清单</span><strong>{item.risks.length} 项</strong><p>{item.risks.join('；')}</p></article>
      </section>
    </>
  )
}
