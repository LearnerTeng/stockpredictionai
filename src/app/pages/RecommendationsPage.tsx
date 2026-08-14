import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, SlidersHorizontal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { Link } from '../router'
import { Change, DataStamp, ErrorPanel, LoadingPanel, money, PageHeader, Score } from '../components/UI'

export function RecommendationsPage() {
  const { t } = useTranslation('recommendations')
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['recommendations'], queryFn: api.recommendations })
  const refresh = useMutation({
    mutationFn: () => api.refreshRecommendations(query.data?.items.map((item) => item.symbol) ?? ['AAPL', 'MSFT', 'NVDA', 'AMZN']),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['recommendations'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  if (query.isPending) return <LoadingPanel label={t('loading')} />
  if (query.error) return <ErrorPanel error={query.error} />

  return (
    <>
      <PageHeader
        eyebrow={t('eyebrow')}
        title={t('title')}
        description={t('description')}
        action={<button className="primary-button" onClick={() => refresh.mutate()} disabled={refresh.isPending}><RefreshCw size={17} className={refresh.isPending ? 'spin' : ''} />{refresh.isPending ? t('refreshing') : t('refresh')}</button>}
      />
      {refresh.error && <div className="inline-alert">{t('refreshFailed', { message: refresh.error.message })}</div>}
      <div className="filter-row"><div><SlidersHorizontal size={16} />{t('sort')}</div><DataStamp mode={query.data.data_mode} /></div>
      <section className="recommendation-grid">
        {query.data.items.map((item, index) => (
          <article className="recommendation-card" key={item.symbol}>
            <div className="rank-number">0{index + 1}</div>
            <div className="recommendation-card-head">
              <div><span className={`stance stance-${item.stance}`}>{item.stance}</span><h2>{item.symbol}</h2><p>{item.name}</p></div>
              <Score value={item.score} />
            </div>
            <div className="price-line"><strong>{money(item.latest_price, 'USD', 2)}</strong><span>{t('expected')} <Change value={item.projected_return_pct} /></span></div>
            <p className="thesis">{item.thesis}</p>
            <div className="factor-list">
              {Object.entries(item.components).map(([key, value]) => (
                <div key={key}><span>{t(`factors.${key}`)}<b>{value}</b></span><i><em style={{ width: `${value}%` }} /></i></div>
              ))}
            </div>
            <div className="risk-line"><strong>{t('mainRisk')}</strong><span>{item.risks.join(' · ')}</span></div>
            <Link className="card-link" to={`/stocks/${item.symbol}`}>{t('view')} <span>↗</span></Link>
          </article>
        ))}
      </section>
      <p className="disclaimer">{t('disclaimer')}</p>
    </>
  )
}
