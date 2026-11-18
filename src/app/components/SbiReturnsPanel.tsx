import { ArrowDownRight, ArrowUpRight, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { number, money, Change } from './UI'
import { formatDateTime } from '../i18n/format'
import { NewsComparisonChart } from './Charts'
import type { SbiFundReturn } from '../types'

const copy = {
  zh: { returns: '我的收益', positions: '当前持仓', breakdown: '各基金累计收益', detail: '履历',
    asOf: 'SBI 算出日', source: '持仓快照', oneDay: '每日曲线会在有两天以上已导入数据时显示。',
    missing: '尚无 SBI 收益快照。', fund: '基金', account: '账户', state: '状态', open: '持有中', closed: '已清仓',
    growth: '成長', tsumitate: 'つみたて', units: '持有口数', tradeUnits: '变动口数', price: '净值／万口', cost: '取得成本',
    value: '市值', pnl: '浮动盈亏', amount: '金额', purchases: '累计买入', sold: '累计卖出', distributions: '分配金',
    fees: '手续费', cumulative: '累计总收益', day: '日期', action: '事件', daily: '已核对的每日快照',
    events: 'SBI 交易履历', noEvents: '暂无这个分组的履历。', eventsNote: '只显示有事件的日期。口数和净值取自 SBI 当日记录。',
    importTitle: '同步 SBI 日数据', returnsFile: '全期间累计收益 CSV', holdingsFile: '当前持仓 CSV（可选）',
    brokerTotal: 'SBI 显示的累计总收益（日元）', preview: '预览', apply: '写入本地 DB', refresh: '刷新数据',
    saved: '入库成功', latestOnly: '账户收益和持仓数据分别显示其日期。' },
  en: { returns: 'My returns', positions: 'Current positions', breakdown: 'Cumulative return by fund', detail: 'History',
    asOf: 'SBI calculation date', source: 'Holdings snapshot', oneDay: 'The daily chart appears once two dates have been imported.',
    missing: 'No SBI return snapshots yet.', fund: 'Fund', account: 'Account', state: 'Status', open: 'Held', closed: 'Closed',
    growth: 'Growth', tsumitate: 'Tsumitate', units: 'Held units', tradeUnits: 'Event units', price: 'NAV / 10,000 units', cost: 'Cost basis',
    value: 'Market value', pnl: 'Unrealized P/L', amount: 'Amount', purchases: 'Purchases', sold: 'Sales', distributions: 'Distributions',
    fees: 'Fees', cumulative: 'Cumulative total return', day: 'Date', action: 'Event', daily: 'Verified daily snapshots',
    events: 'SBI transaction history', noEvents: 'No history for this account bucket.', eventsNote: 'Only event dates are shown. Units and NAV come from the SBI record.',
    importTitle: 'Sync daily SBI data', returnsFile: 'All-period total-return CSV', holdingsFile: 'Current holdings CSV (optional)',
    brokerTotal: 'Cumulative return shown by SBI (JPY)', preview: 'Preview', apply: 'Save to local DB', refresh: 'Refresh data',
    saved: 'Saved', latestOnly: 'Returns and holdings show their respective dates.' },
  ja: { returns: '私の収益', positions: '現在の保有', breakdown: 'ファンド別トータルリターン', detail: '履歴',
    asOf: 'SBI算出日', source: '保有スナップショット', oneDay: '2日分以上を取り込むと日次チャートを表示します。',
    missing: 'SBIの収益データは未登録です。', fund: 'ファンド', account: '口座', state: '状態', open: '保有中', closed: '解約済',
    growth: '成長', tsumitate: 'つみたて', units: '保有口数', tradeUnits: '取引口数', price: '基準価額／1万口', cost: '取得金額',
    value: '評価額', pnl: '評価損益', amount: '金額', purchases: '累計買付', sold: '累計売却', distributions: '分配金',
    fees: '手数料', cumulative: 'トータルリターン', day: '日付', action: '取引区分', daily: '確認済みの日次データ',
    events: 'SBI取引履歴', noEvents: 'この預り区分の履歴はありません。', eventsNote: '取引日のみ表示します。口数と基準価額はSBIの記録です。',
    importTitle: 'SBIの日次データを同期', returnsFile: '全期間トータルリターンCSV', holdingsFile: '保有ファンドCSV（任意）',
    brokerTotal: 'SBI画面のトータルリターン（円）', preview: 'プレビュー', apply: 'DBに保存', refresh: '更新',
    saved: '保存しました', latestOnly: '収益と保有にはそれぞれのデータ日時を表示します。' },
}

const yen = (value: number) => money(value, 'JPY', 0)

export function SbiReturnsPanel({portfolioId, showPositions = false}: {portfolioId: string; showPositions?: boolean}) {
  const { i18n } = useTranslation()
  const lang = i18n.language.split('-')[0]
  const l = lang === 'ja' ? copy.ja : lang === 'zh' ? copy.zh : copy.en
  const bucket = (value: string) => value === 'growth' ? l.growth : l.tsumitate
  const cache = useQueryClient()
  const report = useQuery({queryKey: ['sbi-returns', portfolioId], queryFn: () => api.sbiReturns(portfolioId),
    refetchInterval: 60000, retry: false})
  const holdings = useQuery({queryKey: ['portfolio', portfolioId], queryFn: () => api.portfolio(portfolioId), enabled: showPositions,
    refetchInterval: 30000})
  const [selected, setSelected] = useState<SbiFundReturn>()
  const detail = useRef<HTMLElement>(null)
  useEffect(() => {
    if (selected) detail.current?.focus()
  }, [selected])
  const history = useQuery({queryKey: ['sbi-fund-history', portfolioId, selected?.code],
    queryFn: () => api.sbiFundHistory(portfolioId, selected!.code), enabled: Boolean(selected)})
  const [preview, setPreview] = useState<FormData>()
  const write = useMutation({mutationFn: (form: FormData) => api.importSbiReturns(portfolioId, form),
    onSuccess: async (_, form) => {
      if (form.get('apply') !== 'true') { setPreview(form); return }
      setPreview(undefined)
      await Promise.all([cache.invalidateQueries({queryKey: ['sbi-returns', portfolioId]}),
        cache.invalidateQueries({queryKey: ['portfolio', portfolioId]})])
    },
  })
  const latest = report.data?.latest
  const days = report.data?.history ?? []
  const current = holdings.data
  const total = latest?.totals
  // 同一基金可出现在多个 NISA 分组，明细按基金代码和账户分组匹配。
  // A fund may appear in multiple NISA buckets. Match details by code and account bucket.
  const active = selected && latest?.funds.find(row => row.code === selected.code && row.bucket === selected.bucket)
  const events = (history.data?.events ?? []).filter(row => row.bucket === active?.bucket)
  const daily = active ? days.flatMap(day => {
    const row = day.funds.find(row => row.code === active.code && row.bucket === active.bucket)
    return row ? [{...row, date: day.as_of, observedAt: day.holdings_observed_at}] : []
  }) : []
  return <>
    <section className="panel sbi-returns-panel">
      <div className="panel-title sbi-return-heading">
        <div><h2>{l.returns}</h2>{latest && <p>{l.asOf} <time dateTime={latest.as_of}>{latest.as_of}</time></p>}</div>
        <button type="button" className="secondary-button" onClick={() => { void report.refetch(); if (showPositions) void holdings.refetch() }}>
          <RefreshCw size={15} />{l.refresh}
        </button>
      </div>
      {report.error && <p role="alert" className="inline-alert">{report.error.message}</p>}
      {total ? <>
        <dl className="sbi-metrics">
          <div className="sbi-metric-main">
            <dt>{l.cumulative}</dt>
            <dd className={total.return_jpy >= 0 ? 'positive' : 'negative'}>{yen(total.return_jpy)}</dd>
            {total.return_pct != null && <span className="sbi-change">{total.return_pct >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}<Change value={total.return_pct} /></span>}
          </div>
          <div><dt>{l.purchases}</dt><dd>{yen(total.purchases)}</dd></div>
          <div><dt>{l.sold}</dt><dd>{yen(total.sold)}</dd></div>
          <div><dt>{l.distributions}</dt><dd>{yen(total.distributions)}</dd></div>
        </dl>
        {days.length > 1 ? <NewsComparisonChart series={[{name: l.cumulative, points: days.map(d => ({date: d.as_of, equity: d.totals.return_jpy}))}]} /> : <p className="form-note">{l.oneDay}</p>}
      </> : !report.isPending && <p>{l.missing}</p>}
    </section>
    {showPositions && <section className="panel sbi-returns-panel">
      <div className="panel-title sbi-return-heading">
        <div><h2>{l.positions}</h2>{current && <p>{l.source} <time>{formatDateTime(current.updated_at)}</time></p>}</div>
        {current && <div className="sbi-holdings-total"><span>{l.value}</span><strong>{yen(current.market_value)}</strong></div>}
      </div>
      {holdings.error && <p role="alert">{holdings.error.message}</p>}
      {current && <>

        <div className="table-wrap"><table><thead><tr><th>{l.fund}</th><th>{l.account}</th><th>{l.units}</th><th>{l.price}</th><th>{l.cost}</th><th>{l.value}</th><th>{l.pnl}</th></tr></thead>
          <tbody>{current.positions.map(p => {
            const fund = latest?.funds.find(row => row.symbol === p.symbol)
            return <tr key={p.symbol}>
              <td>{fund ? <button type="button" className="fund-link" onClick={() => setSelected(fund)}>{p.name}<ChevronRight size={15} aria-label={l.detail} /></button> : p.name}</td>
              <td><span className={`account-bucket account-bucket-${p.account_bucket ?? ''}`}>{p.account_bucket ? bucket(p.account_bucket) : '—'}</span></td><td>{number(p.quantity, 0)}</td><td>{yen(p.last_price)}</td>
              <td>{yen(p.market_value - p.unrealized_pnl)}</td><td>{yen(p.market_value)}</td><td className={p.unrealized_pnl >= 0 ? "positive" : "negative"}>{yen(p.unrealized_pnl)}</td>
            </tr>
          })}</tbody></table></div>
      </>}
    </section>}
    {latest && <details className="panel disclosure-panel"><summary><span>{l.breakdown}</span><ChevronDown size={17} /></summary>
          <div className="table-wrap"><table><thead><tr><th>{l.fund}</th><th>{l.account}</th><th>{l.state}</th>
            <th>{l.value}</th><th>{l.purchases}</th><th>{l.sold}</th><th>{l.distributions}</th><th>{l.cumulative}</th></tr></thead>
            <tbody>{latest.funds.map(row => <tr key={row.code + row.bucket}>
              <td><button type="button" className="fund-link" onClick={() => setSelected(row)}>{row.name}<ChevronRight size={15} aria-label={l.detail} /></button></td>
              <td><span className={`account-bucket account-bucket-${row.bucket}`}>{bucket(row.bucket)}</span></td><td className={row.held ? "" : "work-hint"}>{row.held ? l.open : l.closed}</td><td>{yen(row.value)}</td>
              <td>{yen(row.purchases)}</td><td>{yen(row.sold)}</td><td>{yen(row.distributions)}</td>
              <td>{yen(row.return_jpy)} <Change value={row.return_pct} /></td>
            </tr>)}</tbody></table></div>
        </details>}
    <details className="panel disclosure-panel"><summary><span>{l.importTitle}</span><ChevronDown size={17} /></summary>
        <form className="sbi-import-form" onChange={() => { setPreview(undefined); write.reset() }} onSubmit={event => {
          event.preventDefault()
          write.mutate(new FormData(event.currentTarget))
        }}>
          <label className="field">{l.asOf}<input type="date" name="as_of" required /></label>
          <label className="field">{l.brokerTotal}<input name="total" type="number" step={1} required /></label>
          <label className="field">{l.returnsFile}<input type="file" name="returns" accept=".csv" required /></label>
          <label className="field">{l.holdingsFile}<input type="file" name="holdings" accept=".csv" /></label>
          <button className="secondary-button" disabled={write.isPending}>{l.preview}</button>
        </form>
        {write.error && <p role="alert">{write.error.message}</p>}
        {write.data && <p>{write.variables?.get('apply') === 'true' ? l.saved : l.preview} · {write.data.as_of} · {l.value} {yen(write.data.value)} · {l.cumulative} {yen(write.data.return_jpy)}</p>}
        {preview && <button className="primary-button" disabled={write.isPending} onClick={() => {
          const form = new FormData()
          preview.forEach((value, name) => form.set(name, value))
          form.set('apply', 'true')
          write.mutate(form)
        }}>{l.apply}</button>}
      </details>
    {active && <section className="panel sbi-returns-panel" ref={detail} tabIndex={-1} aria-live="polite">
      <div className="panel-title"><h2>{active.name} · {bucket(active.bucket)}</h2>
        <button className="secondary-button" type="button" onClick={() => setSelected(undefined)} aria-label="Close">×</button></div>
      <h3>{l.daily}</h3>
      <div className="table-wrap"><table><thead><tr><th>{l.asOf}</th><th>{l.source}</th><th>{l.units}</th><th>{l.price}</th><th>{l.value}</th><th>{l.cumulative}</th></tr></thead>
        <tbody>{[...daily].reverse().map(row => <tr key={row.date}>
          <td>{row.date}</td><td>{row.holdings ? row.observedAt?.slice(0, 10) ?? "—" : "—"}</td><td>{row.holdings ? number(row.holdings.quantity, 0) : '—'}</td><td>{row.holdings ? yen(row.holdings.last_price) : '—'}</td>
          <td>{yen(row.value)}</td><td>{yen(row.return_jpy)}</td>
        </tr>)}</tbody></table></div>
      <h3>{l.events}</h3>
      <p className="form-note">{l.eventsNote}</p>
      {history.error && <p role="alert">{history.error.message}</p>}
      {history.isSuccess && !events.length && <p>{l.noEvents}</p>}
      {events.length > 0 && <div className="table-wrap"><table><thead><tr><th>{l.day}</th><th>{l.action}</th><th>{l.tradeUnits}</th>
        <th>{l.amount}</th><th>{l.fees}</th><th>{l.units}</th><th>{l.price}</th><th>{l.value}</th></tr></thead>
        <tbody>{[...events].reverse().map((event, i) => <tr key={event.day + i}>
          <td>{event.day}</td><td>{event.action}</td><td>{number(event.units, 0)}</td><td>{yen(event.amount)}</td>
          <td>{yen(event.fee)}</td><td>{number(event.holding_units, 0)}</td><td>{yen(event.nav)}</td><td>{yen(event.value)}</td>
        </tr>)}</tbody></table></div>}
    </section>}
  </>
}
