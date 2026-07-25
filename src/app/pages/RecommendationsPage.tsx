import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, SlidersHorizontal } from 'lucide-react'
import { api } from '../api'
import { Link } from '../router'
import { Change, DataStamp, ErrorPanel, LoadingPanel, PageHeader, Score } from '../components/UI'

const labels: Record<string, string> = { trend: '趋势', fundamental: '基本面', model: '模型', market: '市场', risk: '风险调整' }

export function RecommendationsPage() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['recommendations'], queryFn: api.recommendations })
  const refresh = useMutation({
    mutationFn: () => api.refreshRecommendations(query.data?.items.map((item) => item.symbol) ?? ['AAPL', 'MSFT', 'NVDA', 'AMZN']),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['recommendations'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  if (query.isPending) return <LoadingPanel label="正在计算推荐列表" />
  if (query.error) return <ErrorPanel error={query.error} />

  return (
    <>
      <PageHeader
        eyebrow="Deterministic ranking"
        title="AI 推荐股票"
        description="推荐度由趋势、模型、市场和风险因子组成，LLM 不参与评分计算。"
        action={<button className="primary-button" onClick={() => refresh.mutate()} disabled={refresh.isPending}><RefreshCw size={17} className={refresh.isPending ? 'spin' : ''} />{refresh.isPending ? '刷新中' : '刷新行情评分'}</button>}
      />
      {refresh.error && <div className="inline-alert">刷新失败：{refresh.error.message}</div>}
      <div className="filter-row"><div><SlidersHorizontal size={16} />按推荐度排序</div><DataStamp mode={query.data.data_mode} /></div>
      <section className="recommendation-grid">
        {query.data.items.map((item, index) => (
          <article className="recommendation-card" key={item.symbol}>
            <div className="rank-number">0{index + 1}</div>
            <div className="recommendation-card-head">
              <div><span className={`stance stance-${item.stance}`}>{item.stance}</span><h2>{item.symbol}</h2><p>{item.name}</p></div>
              <Score value={item.score} />
            </div>
            <div className="price-line"><strong>${item.latest_price.toFixed(2)}</strong><span>模型预期 <Change value={item.projected_return_pct} /></span></div>
            <p className="thesis">{item.thesis}</p>
            <div className="factor-list">
              {Object.entries(item.components).map(([key, value]) => (
                <div key={key}><span>{labels[key] ?? key}<b>{value}</b></span><i><em style={{ width: `${value}%` }} /></i></div>
              ))}
            </div>
            <div className="risk-line"><strong>主要风险</strong><span>{item.risks.join(' · ')}</span></div>
            <Link className="card-link" to={`/stocks/${item.symbol}`}>查看完整分析 <span>↗</span></Link>
          </article>
        ))}
      </section>
      <p className="disclaimer">演示与研究用途，不构成投资建议。刷新功能依赖 Yahoo 行情网络连接，基本面因子在未接入财报源前保持中性值。</p>
    </>
  )
}
