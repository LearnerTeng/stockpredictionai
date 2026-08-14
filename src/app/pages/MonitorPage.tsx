import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Filter,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Star,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { useRouter } from '../router'
import { Change, DataStamp, ErrorPanel, money, number, PageHeader } from '../components/UI'
import { currencyForMarket, formatDateTime } from '../i18n/format'
import type { MarketCode, MonitorSettings, MonitorStock, MonitorView } from '../types'

const views: MonitorView[] = ['all', 'wanted', 'holding', 'ai']

const markets: Array<'' | MarketCode> = ['', 'US', 'JP', 'HK']

const fixedIntervals = [5, 15, 30, 60]

type StockForm = {
  symbol: string
  market: MarketCode
  name: string
  exchange: string
  sector: string
}

function StockEditor({ stock, onClose, onSave, pending }: {
  stock: MonitorStock | null
  onClose: () => void
  onSave: (form: StockForm) => void
  pending: boolean
}) {
  const { t } = useTranslation(['monitor', 'common'])
  const [form, setForm] = useState<StockForm>({
    symbol: stock?.symbol ?? '',
    market: stock?.market ?? 'US',
    name: stock?.name === stock?.symbol ? '' : stock?.name ?? '',
    exchange: stock?.exchange ?? '',
    sector: stock?.sector ?? '',
  })

  const update = (key: keyof StockForm, value: string) => setForm((current) => ({ ...current, [key]: value }))

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="monitor-modal" role="dialog" aria-modal="true" aria-labelledby="stock-editor-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div><span>{stock ? t('monitor:editor.editEyebrow') : t('monitor:editor.addEyebrow')}</span><h2 id="stock-editor-title">{stock ? t('monitor:editor.editTitle') : t('monitor:editor.addTitle')}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label={t('common:actions.close')}><X /></button>
        </div>
        <form onSubmit={(event) => { event.preventDefault(); onSave(form) }}>
          <div className="monitor-form-grid">
            <label>{t('monitor:editor.market')}<select value={form.market} onChange={(event) => update('market', event.target.value)} disabled={Boolean(stock)}><option value="US">{t('common:market.US')}</option><option value="JP">{t('common:market.JP')}</option><option value="HK">{t('common:market.HK')}</option></select></label>
            <label>{t('monitor:editor.symbol')}<input value={form.symbol} onChange={(event) => update('symbol', event.target.value.toUpperCase())} placeholder={form.market === 'JP' ? '7203' : form.market === 'HK' ? '700' : 'NVDA'} disabled={Boolean(stock)} required /></label>
            <label>{t('monitor:editor.name')}<input value={form.name} onChange={(event) => update('name', event.target.value)} placeholder={t('monitor:editor.namePlaceholder')} /></label>
            <label>{t('monitor:editor.exchange')}<input value={form.exchange} onChange={(event) => update('exchange', event.target.value)} placeholder="NASDAQ / TSE / HKEX" /></label>
            <label className="form-span">{t('monitor:editor.sector')}<input value={form.sector} onChange={(event) => update('sector', event.target.value)} placeholder={t('monitor:editor.sectorPlaceholder')} /></label>
          </div>
          <p className="form-note">{t('monitor:editor.note')}</p>
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>{t('common:actions.cancel')}</button><button className="primary-button" disabled={pending || !form.symbol.trim()}>{pending ? t('common:actions.saving') : stock ? t('monitor:editor.save') : t('monitor:editor.addAndFetch')}</button></div>
        </form>
      </section>
    </div>
  )
}

function SortHeader({ field, label, currentSort, currentOrder, onSort }: {
  field: string
  label: string
  currentSort: string
  currentOrder: string
  onSort: (field: string) => void
}) {
  const active = currentSort === field
  return <button className={`sort-header ${active ? 'active' : ''}`} onClick={() => onSort(field)}>{label}{active && (currentOrder === 'asc' ? <ArrowUp /> : <ArrowDown />)}</button>
}

export function MonitorPage() {
  const { t } = useTranslation(['monitor', 'common'])
  const queryClient = useQueryClient()
  const { location, navigate, searchParams } = useRouter()
  const paramsKey = searchParams.toString()
  const filters = useMemo(() => Object.fromEntries(new URLSearchParams(paramsKey).entries()), [paramsKey])
  const view = (filters.view as MonitorView) || 'all'
  const [searchText, setSearchText] = useState(filters.q ?? '')
  const [advanced, setAdvanced] = useState(false)
  const [editor, setEditor] = useState<MonitorStock | 'new' | null>(null)
  const [customInterval, setCustomInterval] = useState('15')
  const [intervalChoice, setIntervalChoice] = useState('15')
  const [remainingSeconds, setRemainingSeconds] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => setSearchText(filters.q ?? ''), [filters.q])

  const query = useQuery({
    queryKey: ['monitor-stocks', paramsKey],
    queryFn: () => api.monitorStocks(filters),
  })
  const settings = useQuery({ queryKey: ['monitor-settings'], queryFn: api.monitorSettings })

  const updateUrl = (updates: Record<string, string | number | null>, resetPage = true) => {
    const next = new URLSearchParams(paramsKey)
    Object.entries(updates).forEach(([key, value]) => {
      if (value === null || value === '') next.delete(key)
      else next.set(key, String(value))
    })
    if (resetPage) next.delete('page')
    const serialized = next.toString()
    navigate(`/monitor${serialized ? `?${serialized}` : ''}`)
  }

  const invalidateMonitor = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['monitor-stocks'] }),
      queryClient.invalidateQueries({ queryKey: ['monitor-stock'] }),
      queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
    ])
  }

  const wantedMutation = useMutation({
    mutationFn: ({ symbol, wanted }: { symbol: string; wanted: boolean }) => api.setMonitorWanted(symbol, wanted),
    onSuccess: invalidateMonitor,
  })
  const saveMutation = useMutation({
    mutationFn: async (form: StockForm) => {
      if (editor === 'new') {
        const result = await api.addMonitorStock(form)
        return { stock: result.item, warnings: result.warnings }
      }
      const stock = await api.updateMonitorStock((editor as MonitorStock).symbol, {
        market: form.market,
        name: form.name,
        exchange: form.exchange,
        sector: form.sector,
      })
      return { stock, warnings: [] as string[] }
    },
    onSuccess: async (result) => {
      setEditor(null)
      setNotice(result.warnings.length ? t('monitor:addedWithWarnings', { warnings: result.warnings.join('; ') }) : t('monitor:saved'))
      await invalidateMonitor()
    },
  })
  const settingsMutation = useMutation({
    mutationFn: api.updateMonitorSettings,
    onSuccess: (value) => queryClient.setQueryData(['monitor-settings'], value),
  })
  const refresh = useMutation({
    mutationFn: () => api.refreshMonitor(filters),
    onSuccess: async (result) => {
      setNotice(result.errors.length
        ? t('monitor:refreshPartial', { success: result.refreshed.length, failed: result.errors.length })
        : t('monitor:refreshDone', { count: result.refreshed.length }))
      await invalidateMonitor()
    },
  })

  const monitorSettings: MonitorSettings = settings.data ?? { auto_refresh_enabled: false, interval_minutes: 15, updated_at: null }
  const intervalSeconds = monitorSettings.interval_minutes * 60

  useEffect(() => {
    setCustomInterval(String(monitorSettings.interval_minutes))
    setIntervalChoice(fixedIntervals.includes(monitorSettings.interval_minutes) ? String(monitorSettings.interval_minutes) : 'custom')
    setRemainingSeconds(intervalSeconds)
  }, [intervalSeconds, monitorSettings.interval_minutes, paramsKey])

  useEffect(() => {
    if (!monitorSettings.auto_refresh_enabled) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible' && !refresh.isPending) {
        setRemainingSeconds((current) => Math.max(current - 1, 0))
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [monitorSettings.auto_refresh_enabled, refresh.isPending])

  useEffect(() => {
    if (monitorSettings.auto_refresh_enabled && remainingSeconds === 0 && !refresh.isPending) {
      refresh.mutate()
      setRemainingSeconds(intervalSeconds)
    }
  }, [intervalSeconds, monitorSettings.auto_refresh_enabled, refresh, remainingSeconds])

  const saveSettings = (next: Partial<MonitorSettings>) => settingsMutation.mutate({
    auto_refresh_enabled: next.auto_refresh_enabled ?? monitorSettings.auto_refresh_enabled,
    interval_minutes: next.interval_minutes ?? monitorSettings.interval_minutes,
  })

  const sort = filters.sort ?? (view === 'ai' || view === 'wanted' ? 'ai_score' : view === 'holding' ? 'market_value' : 'updated_at')
  const order = filters.order ?? 'desc'
  const handleSort = (field: string) => updateUrl({ sort: field, order: sort === field && order === 'desc' ? 'asc' : 'desc' })

  if (query.error) return <ErrorPanel error={query.error} />
  const data = query.data
  const statuses = data?.facets.statuses ?? { all: 0, wanted: 0, holding: 0, ai: 0 }
  const page = data?.page ?? Number(filters.page ?? 1)
  const pages = data?.pages ?? 1
  const refreshErrors = refresh.data?.errors ?? []
  return (
    <>
      <PageHeader
        eyebrow={t('monitor:eyebrow')}
        title={t('monitor:title')}
        description={t('monitor:description')}
        action={<div className="monitor-header-actions"><DataStamp value={data?.generated_at} mode={data?.data_mode} /><button className="primary-button" onClick={() => setEditor('new')}><Plus />{t('monitor:addStock')}</button></div>}
      />

      <section className="monitor-toolbar panel">
        <div className="monitor-tabs" role="tablist">
          {views.map((item) => <button key={item} role="tab" aria-selected={view === item} className={view === item ? 'active' : ''} onClick={() => updateUrl({ view: item === 'all' ? null : item, sort: null, order: null })}><span>{t(`monitor:views.${item}`)}</span><b>{statuses[item] ?? 0}</b></button>)}
        </div>
        <div className="monitor-basic-filters">
          <form className="monitor-query" onSubmit={(event) => { event.preventDefault(); updateUrl({ q: searchText }) }}><Search /><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={t('monitor:searchPlaceholder')} /><button aria-label={t('common:actions.search')}>{t('common:actions.search')}</button></form>
          <div className="market-segments">{markets.map((market) => <button key={market || 'all'} className={(filters.market ?? '') === market ? 'active' : ''} onClick={() => updateUrl({ market })}>{t(`common:market.${market || 'all'}`)}<small>{market ? data?.facets.markets[market] ?? 0 : statuses.all}</small></button>)}</div>
          <button className={`secondary-button filter-toggle ${advanced ? 'active' : ''}`} onClick={() => setAdvanced((value) => !value)}><Filter />{t('monitor:advanced')}</button>
        </div>
        {advanced && <div className="advanced-filters">
          <label>{t('monitor:filters.sector')}<select value={filters.sector ?? ''} onChange={(event) => updateUrl({ sector: event.target.value })}><option value="">{t('monitor:filters.allSectors')}</option>{Object.keys(data?.facets.sectors ?? {}).map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>{t('monitor:filters.exchange')}<select value={filters.exchange ?? ''} onChange={(event) => updateUrl({ exchange: event.target.value })}><option value="">{t('monitor:filters.allExchanges')}</option>{Object.keys(data?.facets.exchanges ?? {}).map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>{t('monitor:filters.minPrice')}<input type="number" min="0" value={filters.price_min ?? ''} onChange={(event) => updateUrl({ price_min: event.target.value })} /></label>
          <label>{t('monitor:filters.maxPrice')}<input type="number" min="0" value={filters.price_max ?? ''} onChange={(event) => updateUrl({ price_max: event.target.value })} /></label>
          <label>{t('monitor:filters.minScore')}<input type="number" min="0" max="100" value={filters.score_min ?? ''} onChange={(event) => updateUrl({ score_min: event.target.value })} /></label>
          <label>{t('monitor:filters.maxScore')}<input type="number" min="0" max="100" value={filters.score_max ?? ''} onChange={(event) => updateUrl({ score_max: event.target.value })} /></label>
          <label>{t('monitor:filters.direction')}<select value={filters.forecast_direction ?? ''} onChange={(event) => updateUrl({ forecast_direction: event.target.value })}><option value="">{t('monitor:filters.all')}</option><option value="up">{t('monitor:filters.up')}</option><option value="down">{t('monitor:filters.down')}</option></select></label>
          <label>{t('monitor:filters.freshness')}<select value={filters.freshness ?? ''} onChange={(event) => updateUrl({ freshness: event.target.value })}><option value="">{t('monitor:filters.all')}</option><option value="24h">{t('monitor:filters.within24h')}</option><option value="3d">{t('monitor:filters.within3d')}</option><option value="7d">{t('monitor:filters.within7d')}</option><option value="stale">{t('monitor:filters.stale')}</option></select></label>
          <button className="filter-reset" onClick={() => navigate(`/monitor${view === 'all' ? '' : `?view=${view}`}`)}>{t('monitor:filters.clear')}</button>
        </div>}
        <div className="refresh-row">
          <button className="secondary-button" onClick={() => refresh.mutate()} disabled={refresh.isPending}><RefreshCw className={refresh.isPending ? 'spin' : ''} />{refresh.isPending ? t('monitor:refreshing') : t('monitor:refreshCurrent')}</button>
          <label className="refresh-check"><input type="checkbox" checked={monitorSettings.auto_refresh_enabled} onChange={(event) => saveSettings({ auto_refresh_enabled: event.target.checked })} />{t('monitor:scheduledRefresh')}</label>
          <select value={intervalChoice} onChange={(event) => { setIntervalChoice(event.target.value); if (event.target.value !== 'custom') saveSettings({ interval_minutes: Number(event.target.value) }) }} disabled={!monitorSettings.auto_refresh_enabled}>{fixedIntervals.map((value) => <option key={value} value={value}>{t('monitor:minutes', { count: value })}</option>)}<option value="custom">{t('monitor:custom')}</option></select>
          {intervalChoice === 'custom' && <label className="custom-interval"><input type="number" min="1" max="1440" value={customInterval} onChange={(event) => setCustomInterval(event.target.value)} onBlur={() => saveSettings({ interval_minutes: Math.min(Math.max(Number(customInterval) || 15, 1), 1440) })} />{t('monitor:minuteUnit')}</label>}
          {monitorSettings.auto_refresh_enabled && <span className="refresh-countdown"><Clock3 />{Math.floor(remainingSeconds / 60)}:{String(remainingSeconds % 60).padStart(2, '0')}</span>}
          <span className="refresh-scope">{t('monitor:currentScope')}</span>
        </div>
      </section>

      {(notice || saveMutation.error || wantedMutation.error || settingsMutation.error) && <div className={`inline-alert ${saveMutation.error || wantedMutation.error || settingsMutation.error ? '' : 'notice-success'}`}>{saveMutation.error?.message ?? wantedMutation.error?.message ?? settingsMutation.error?.message ?? notice}</div>}
      {refreshErrors.length > 0 && <div className="refresh-errors">{refreshErrors.slice(0, 5).map((item) => <span key={item.symbol}><strong>{item.symbol}</strong>{item.error}</span>)}</div>}

      <section className="panel monitor-table-panel">
        <div className="monitor-result-head"><div><strong>{t('monitor:resultCount', { count: data?.total ?? 0 })}</strong></div>{query.isFetching && <span className="querying"><RefreshCw className="spin" />{t('monitor:reading')}</span>}</div>
        <div className="table-wrap">
          <table className="monitor-table">
            <thead><tr><th>{t('monitor:table.stock')}</th><th>{t('monitor:table.marketStatus')}</th><th><SortHeader field="latest_price" label={t('monitor:table.latestPrice')} currentSort={sort} currentOrder={order} onSort={handleSort} /></th><th><SortHeader field="day_change_pct" label={t('monitor:table.dayChange')} currentSort={sort} currentOrder={order} onSort={handleSort} /></th><th><SortHeader field="ai_score" label={t('monitor:table.aiScore')} currentSort={sort} currentOrder={order} onSort={handleSort} /></th><th><SortHeader field="projected_return_pct" label={t('monitor:table.projectedReturn')} currentSort={sort} currentOrder={order} onSort={handleSort} /></th><th><SortHeader field="holding_pnl_pct" label={t('monitor:table.holdingPnl')} currentSort={sort} currentOrder={order} onSort={handleSort} /></th><th>{t('monitor:table.quoteUpdated')}</th><th>{t('monitor:table.actions')}</th></tr></thead>
            <tbody>
              {data?.items.map((stock) => {
                const returnTarget = encodeURIComponent(location)
                const currency = currencyForMarket(stock.market)
                return <tr key={stock.symbol} className="monitor-row" data-view={view} tabIndex={0} onClick={() => navigate(`/stocks/${stock.symbol}?from=${returnTarget}`)} onKeyDown={(event) => { if (event.key === 'Enter') navigate(`/stocks/${stock.symbol}?from=${returnTarget}`) }}>
                  <td><div className="stock-cell"><div className="status-rail">{stock.statuses.map((status) => <i key={status} className={`rail-${status}`} />)}</div><div><strong>{stock.symbol}</strong><span>{stock.name}</span></div></div></td>
                  <td><div className="market-status"><span className="market-tag">{t(`common:market.${stock.market}`)}</span><div>{stock.statuses.map((status) => <b key={status} className={`status-tag status-${status}`}>{t(`common:status.${status}`)}</b>)}</div></div></td>
                  <td>{stock.latest_price === null ? '--' : money(stock.latest_price, currency, 2)}</td>
                  <td>{stock.day_change_pct === null ? '--' : <Change value={stock.day_change_pct} />}</td>
                  <td>{stock.ai_score === null ? '--' : <span className="score-value">{number(stock.ai_score, 0)}</span>}</td>
                  <td>{stock.projected_return_pct === null ? '--' : <Change value={stock.projected_return_pct} />}</td>
                  <td>{stock.holding_pnl_pct === null ? '--' : <div><Change value={stock.holding_pnl_pct} />{stock.market_value !== null && <small>{money(stock.market_value, currency)}</small>}</div>}</td>
                  <td><div className="date-cell"><strong>{stock.latest_trade_date ?? t('monitor:noQuote')}</strong><span>{stock.last_refreshed_at ? formatDateTime(stock.last_refreshed_at) : t('monitor:neverRefreshed')}</span></div></td>
                  <td><div className="row-tools"><button className={stock.wanted ? 'wanted' : ''} title={stock.wanted ? t('monitor:removeWanted') : t('monitor:addWanted')} aria-label={stock.wanted ? t('monitor:removeWanted') : t('monitor:addWanted')} onClick={(event) => { event.stopPropagation(); wantedMutation.mutate({ symbol: stock.symbol, wanted: !stock.wanted }) }}><Star fill={stock.wanted ? 'currentColor' : 'none'} /></button><button title={t('monitor:editMetadata')} aria-label={t('monitor:editMetadata')} onClick={(event) => { event.stopPropagation(); setEditor(stock) }}><Pencil /></button></div></td>
                </tr>
              })}
              {!query.isPending && !data?.items.length && <tr><td colSpan={9}><div className="empty-table">{t('monitor:empty')}</div></td></tr>}
            </tbody>
          </table>
        </div>
        <div className="pagination"><button disabled={page <= 1} onClick={() => updateUrl({ page: page - 1 }, false)}><ChevronLeft />{t('monitor:previous')}</button><span>{t('monitor:page', { page, pages })}</span><button disabled={page >= pages} onClick={() => updateUrl({ page: page + 1 }, false)}>{t('monitor:next')}<ChevronRight /></button></div>
      </section>
      <p className="disclaimer">{t('monitor:disclaimer')}</p>

      {editor && <StockEditor stock={editor === 'new' ? null : editor} onClose={() => setEditor(null)} pending={saveMutation.isPending} onSave={(form) => saveMutation.mutate(form)} />}
    </>
  )
}
