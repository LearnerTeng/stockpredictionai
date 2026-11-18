import { SentimentEvaluationPanel } from './SentimentEvaluationPanel'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import type { NewsComparison, NewsLine, Portfolio } from '../types'
import { NewsComparisonChart } from './Charts'

const lines: NewsLine[] = ['deepseek', 'ultra', 'experiment', 'holdings']
const copy = {
  'zh-CN': {title: '新闻策略模拟对照', deepseek: 'DeepSeek 模拟', ultra: 'Ultra 模拟', experiment: '实验特征策略', holdings: '当前持仓基准',
    description: '多选要运行和展示的模拟线。各线使用同一持仓快照、资金及成交成本。无证据的线显示缺失。',
    queue: '启用所选模型并加入后台队列', file: '导入回放 JSON（含带时间的持仓快照）', run: '运行所选模拟线',
    missing: '未配置密钥', ready: '密钥已配置', empty: '暂无可用证据', result: '回放记录', gain: '收益', drawdown: '最大回撤', costs: '手续费 / 滑点'},
  en: {title: 'News strategy comparison', deepseek: 'DeepSeek simulation', ultra: 'Ultra simulation', experiment: 'Experimental features', holdings: 'Current holdings baseline',
    description: 'Select independent lines to run and display. All use the same portfolio snapshot, capital and execution costs. Missing evidence stays explicit.',
    queue: 'Enable selected models and queue news', file: 'Import replay JSON with a dated holdings snapshot', run: 'Run selected lines', missing: 'Key missing', ready: 'Key configured', empty: 'Insufficient evidence', result: 'Replay record', gain: 'Return', drawdown: 'Max drawdown', costs: 'Commission / slippage'},
  ja: {title: 'ニュース戦略の比較', deepseek: 'DeepSeek シミュレーション', ultra: 'Ultra シミュレーション', experiment: '実験特徴量戦略', holdings: '現在保有の基準線',
    description: '実行・表示する系列を選択。同一の保有スナップショット、資金、取引コストで比較します。証拠不足は明示されます。',
    queue: '選択モデルを有効にしてキューに追加', file: '日時付き保有情報を含む回放 JSON を読込', run: '選択系列を実行', missing: 'キー未設定', ready: 'キー設定済み', empty: '証拠不足', result: '回放記録', gain: 'リターン', drawdown: '最大ドローダウン', costs: '手数料 / スリッページ'},
}

export function NewsLinesPanel() {
  const { i18n } = useTranslation()
  const c = copy[i18n.resolvedLanguage as keyof typeof copy] ?? copy.en
  const labels = c === copy['zh-CN']
    ? {background:'后台新闻分析', lines:'本次回放曲线', save:'保存后台模型设置', notRun:'本次未运行', capital:'初始资金', snapshot:'持仓快照', release:'使用文件内快照'}
    : c === copy.ja
    ? {background:'バックグラウンド分析', lines:'表示・実行する系列', save:'モデル設定を保存', notRun:'未実行', capital:'初期資金', snapshot:'保有スナップショット', release:'ファイル内の保有情報を使用'}
    : {background:'Background news analysis', lines:'Replay lines', save:'Save background models', notRun:'Not run', capital:'Initial capital', snapshot:'Holdings snapshot', release:'Use snapshot from file'}
  const cache = useQueryClient()
  const [selected, setSelected] = useState<NewsLine[]>(lines)
  const [file, setFile] = useState<Record<string, unknown>>()
  const [fileError, setFileError] = useState('')
  const [report, setReport] = useState<NewsComparison>()
  const [portfolioId, setPortfolioId] = useState('primary')
  const [snapshot, setSnapshot] = useState<{as_of: string; portfolio: Portfolio}>()
  const portfolios = useQuery({queryKey: ['portfolios'], queryFn: api.portfolios})
  const capture = useMutation({mutationFn: () => api.newsHoldingSnapshot(portfolioId), onSuccess: setSnapshot})
  const status = useQuery({queryKey: ['news-lines'], queryFn: api.newsLines, refetchInterval: 15000})
  const [draftModels, setDraftModels] = useState<NewsLine[] | null>(null)
  const background = draftModels ?? status.data?.enabled ?? []
  const queue = useMutation({mutationFn: () => api.enableNewsLines(background),
    onSuccess: async () => {await cache.invalidateQueries({queryKey: ['news-lines']}); setDraftModels(null)}})
  const compare = useMutation({mutationFn: () => {
    const dataset = structuredClone((file?.dataset ?? file) as Record<string, unknown>)
    if (snapshot) {
      const assets = dataset.assets as Record<string, {symbol: string}>
      const quantities: Record<string, number> = {}
      for (const p of snapshot.portfolio.positions) {
        const matches = Object.entries(assets).filter(([, a]) => a.symbol === p.symbol)
        if (p.quantity && matches.length !== 1) throw new Error(`Missing or ambiguous holding: ${p.symbol}`)
        if (p.quantity) quantities[matches[0][0]] = p.quantity
      }
      dataset.holding_snapshot = {as_of: snapshot.as_of, quantities, cash: snapshot.portfolio.cash}
    }
    return api.compareNewsLines({dataset, config: file?.config ?? {}, lines: selected})
  },
    onSuccess: value => {setReport(value); void cache.invalidateQueries({queryKey: ['news-lines']})}})
  const shown = report ?? status.data?.comparisons[0]
  const series = selected.flatMap(line => {
    const points = shown?.results[line]?.replay?.equity_curve
    return points?.length ? [{name: c[line], points}] : []
  })
  return <div className="research-tools" id="sentiment-research" tabIndex={-1}><section className="panel work-panel">
    <div className="work-panel-heading"><h2>{c.title}</h2><p>{c.description}</p></div>
    <details><summary>{labels.background}</summary>
      {(['deepseek', 'ultra'] as const).map(line => <p key={line}><label className="check-field">
        <input type="checkbox" checked={background.includes(line)} disabled={!status.data || queue.isPending}
          onChange={e => setDraftModels(e.target.checked ? [...background, line] : background.filter(l => l !== line))} />
        {c[line]} · {status.data?.models[line]?.model} · {status.data?.models[line]?.configured ? c.ready : c.missing}
      </label> {Object.entries(status.data?.models[line]?.jobs ?? {}).map(([state,n]) => `${state} × ${n}`).join(' · ')}</p>)}
      <button className="secondary-button" disabled={!status.data || !draftModels || queue.isPending} onClick={() => queue.mutate()}>{labels.save}</button>
    </details>
    <fieldset className="option-group"><legend>{labels.lines}</legend><div className="option-list">{lines.map(line => <label className="check-option" key={line}>
      <input type="checkbox" checked={selected.includes(line)} onChange={e => setSelected(old => e.target.checked ? [...old, line] : old.filter(l => l !== line))} /> {c[line]}
    </label>)}</div></fieldset>
    <div className="form-row"><select aria-label={c.holdings} value={portfolioId} onChange={e => {setPortfolioId(e.target.value); setSnapshot(undefined)}}>
      {(portfolios.data?.items ?? []).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
    </select> <button className="secondary-button" disabled={capture.isPending} onClick={() => capture.mutate()}>{c.holdings} · {i18n.language.startsWith('zh') ? '保存当前快照' : i18n.language.startsWith('ja') ? '現在を記録' : 'Capture snapshot'}</button>
    {snapshot && <><small> {new Date(snapshot.as_of).toLocaleString()}</small> <button className="secondary-button" onClick={() => setSnapshot(undefined)}>{labels.release}</button></>}</div>
    <label className="field">{c.file} <input type="file" accept=".json" onChange={async e => {
      setFile(undefined); setFileError(''); const f = e.target.files?.[0]; if (!f) return
      try { if (f.size > 10000000) throw new Error('JSON exceeds 10 MB'); setFile(JSON.parse(await f.text())) } catch (error) {setFileError(String(error))}
    }} /></label>
    <button className="primary-button" disabled={!file || !selected.length || compare.isPending} onClick={() => compare.mutate()}>{c.run}</button>
    {(fileError || status.error || queue.error || compare.error || capture.error) && <p className="inline-alert">{fileError || status.error?.message || queue.error?.message || compare.error?.message || capture.error?.message}</p>}
    {shown && <><p>{c.result}: {shown.id.slice(0, 12)}</p>
      <p>{shown.period?.join(' → ')} · {labels.capital} USD {shown.initial_capital?.toLocaleString()}
        {shown.snapshot_as_of && <> · {labels.snapshot} {new Date(shown.snapshot_as_of).toLocaleString()}</>}</p>
      {Object.entries(shown.model_pins ?? {}).map(([line, pin]) => <small key={line} style={{display:'block',overflowWrap:'anywhere'}}>{c[line as 'deepseek' | 'ultra']} · {pin.provider} / {pin.model} · {pin.version}</small>)}
      {series.length > 0 && <NewsComparisonChart series={series} />}
      {selected.map(line => {const result = shown.results[line]; const m = result?.replay?.metrics; return <p key={line}>{c[line]}: {m ? `${c.gain} ${m.return_pct.toFixed(2)}% · ${c.drawdown} ${m.max_drawdown_pct.toFixed(2)}% · ${c.costs} ${m.commission.toFixed(2)} / ${m.slippage.toFixed(2)}` : shown.selected.includes(line) ? c.empty : labels.notRun}</p>})}
    </>}
  </section><SentimentEvaluationPanel /></div>
}
