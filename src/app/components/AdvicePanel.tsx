import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, API_BASE } from '../api'

type Evidence = { id: string; body: string; url?: string; source: string; available_at: string }
type Report = { decision: { action: string; reason: string; stale: boolean; position_stale?: boolean; quote_stale?: boolean; horizon: string; simulation_eligible: boolean; score: number | null; position_limit: number | null }; explanation: { summary: string; risks: string[]; conditions: string[]; claims: {text: string; evidence_id: string; quote: string}[] }; evidence: Evidence[]; model: string; generated_at: string; analysis_at?: string; rule_version?: string; prompt_version?: string; quote_available_at?: string; quote_time: string | null; position_time: string | null }
type Job = { id: string; symbol: string; portfolio_id: string; status: string; error?: string; kind: string; result: Report | null }
type Replay = {analysis_at: string; input_hash: string; decision: Report['decision']}
type Settings = { enabled: boolean; interval_seconds: number; rpm: number; target_rpm: number; background_rpm: number; concurrency: number; position_limit: number; allocation_targets: Record<string, number>; keyword_only: boolean }
type Status = { jobs: Record<string, number>; calls_last_minute: number; last_success: string | null; models: Record<string, {model: string; configured: boolean}> }
async function call<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch(API_BASE + path, body === undefined ? undefined : { method, headers: {'Content-Type':'application/json'}, body:JSON.stringify(body) })
  const result = await response.json()
  if (!response.ok) throw new Error(result.error || String(response.status))
  return result
}
const labels = {
  'zh-CN': { title:'持仓与自选建议', symbol:'股票代码', account:'账户', run:'生成建议', review:'Ultra 复核', ask:'围绕报告提问', settings:'自动分析设置', auto:'自动检查变化', save:'保存', frequency:'检查间隔（秒）', quota:'每分钟调度额度', background:'后台额度', cap:'单标的上限（%）', allocation:'长期配置目标（当前标的，%）', empty:'尚无报告；生成后可查看证据及触发条件。', status:'运行状态', quote:'行情时间', position:'持仓时间', generated:'分析时间', risks:'风险', conditions:'触发条件', evidence:'证据', trade:'打开模拟交易', stale:'行情缺失或过期', watch:'关注', consider_buy:'考虑买入', hold:'持有', consider_reduce:'考虑减仓', insufficient_evidence:'证据不足', pending:'排队中', retry:'等待重试', running:'分析中', ready:'已完成', failed:'失败', superseded:'已被新任务替代' },
  en: {title:'Portfolio and watchlist advice',symbol:'Symbol',account:'Account',run:'Generate advice',review:'Ultra review',ask:'Ask about this report',settings:'Analysis settings',auto:'Check for changes automatically',save:'Save',frequency:'Check interval (seconds)',quota:'Requests per minute',background:'Background budget',cap:'Position cap (%)',allocation:'Long-term target for this symbol (%)',empty:'No report yet. Generate one to inspect evidence and conditions.',status:'Runtime status',quote:'Quote time',position:'Position time',generated:'Analysis time',risks:'Risks',conditions:'Conditions',evidence:'Evidence',trade:'Open paper trading',stale:'Missing or stale quote',watch:'Watch',consider_buy:'Consider buying',hold:'Hold',consider_reduce:'Consider reducing',insufficient_evidence:'Insufficient evidence',pending:'Queued',retry:'Waiting to retry',running:'Analyzing',ready:'Ready',failed:'Failed',superseded:'Superseded'},
  ja: {title:'保有・ウォッチ銘柄の分析',symbol:'銘柄',account:'口座',run:'分析を生成',review:'Ultraで再確認',ask:'レポートについて質問',settings:'分析設定',auto:'変更を自動確認',save:'保存',frequency:'確認間隔（秒）',quota:'毎分の呼出上限',background:'バックグラウンド枠',cap:'銘柄上限（%）',allocation:'この銘柄の長期配分目標（%）',empty:'レポートはまだありません。生成すると根拠と条件を確認できます。',status:'稼働状況',quote:'株価時点',position:'保有時点',generated:'分析時点',risks:'リスク',conditions:'条件',evidence:'根拠',trade:'模擬取引を開く',stale:'株価が未取得または古い',watch:'注目',consider_buy:'購入を検討',hold:'保有',consider_reduce:'縮小を検討',insufficient_evidence:'根拠不足',pending:'待機中',retry:'再試行待ち',running:'分析中',ready:'完了',failed:'失敗',superseded:'新しいタスクに置換'}
}
export function AdvicePanel({symbol: fixedSymbol, portfolioId, controls = false}: {symbol?: string; portfolioId?: string; controls?: boolean}) {
  const {i18n} = useTranslation()
  const lang = (i18n.resolvedLanguage || 'zh-CN') as keyof typeof labels
  const l = labels[lang] || labels['zh-CN']
  const label = (key: string) => (l as Record<string,string>)[key] || key
  const [symbol, setSymbol] = useState(fixedSymbol || '')
  const [account, setAccount] = useState(portfolioId || 'primary')
  const chosenSymbol = fixedSymbol || symbol
  const chosenAccount = portfolioId || account
  const [question, setQuestion] = useState('')
  const [draft, setDraft] = useState<Settings | null>(null)
  const qc = useQueryClient()
  const accounts = useQuery({queryKey:['advice-accounts'],queryFn:()=>call<{items:{id:string;name:string}[]}>('/portfolios')})
  const reports = useQuery({queryKey:['advice',chosenSymbol,chosenAccount], queryFn:()=>call<{items:Job[]}>(`/advice?portfolio_id=${encodeURIComponent(chosenAccount)}${chosenSymbol ? '&symbol='+encodeURIComponent(chosenSymbol) : ''}`),refetchInterval:5000})
  const config = useQuery({queryKey:['ai-settings'],queryFn:()=>call<Settings>('/ai/settings'),enabled:controls})
  const status = useQuery({queryKey:['ai-status'],queryFn:()=>call<Status>('/ai/status'),refetchInterval:10000,enabled:controls})
  const runtime = useQuery({queryKey: ['runtime-status'], queryFn: api.runtimeStatus, refetchInterval: 10000, enabled: controls})
  const replay = useMutation({mutationFn: async (id: string) => ({
    id, result: await call<Replay>(`/advice/jobs/${encodeURIComponent(id)}/replay`),
  })})
  const replayLabel = lang === 'zh-CN' ? '重放规则' : lang === 'ja' ? 'ルールを再実行' : 'Replay rules'
  const jobs = reports.data?.items || []
  const report = jobs.find(j=>j.kind === 'analysis' && j.result)
  // 提交后由后台执行，页面轮询已保存的报告。
  // The worker runs submitted jobs while the page polls persisted reports.
  const submit = useMutation({mutationFn:(kind:string)=>call<Job>('/advice/jobs',{symbol:chosenSymbol,portfolio_id:chosenAccount,kind,language:lang,question,parent_id:report?.id}),onSuccess:()=>qc.invalidateQueries({queryKey:['advice']})})
  const save = useMutation({mutationFn:()=>call<Settings>('/ai/settings',draft,'PUT'),onSuccess:()=>{setDraft(null);qc.invalidateQueries({queryKey:['ai-settings']})}})
  const cfg = draft || config.data
  const edit = (patch:Partial<Settings>) => cfg && setDraft({...cfg,...patch})
  const error = reports.error || submit.error || save.error || config.error
  return <section className="panel work-panel advice-panel">
    <div className="work-panel-heading"><h2>{l.title}</h2></div>
    <form className="form-row" onSubmit={event => { event.preventDefault(); if (chosenSymbol && !submit.isPending) submit.mutate('analysis') }}>
      {!fixedSymbol && <label className="field">{l.symbol}<input value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} maxLength={32}/></label>}
      {!portfolioId && <label className="field">{l.account}<select value={account} onChange={e=>setAccount(e.target.value)}>{accounts.data?.items.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}
      <button className="primary-button" disabled={!chosenSymbol || submit.isPending}>{l.run}</button>
    </form>
    {error && <p className="inline-alert" role="alert">{error.message}</p>}
    {jobs.slice(0,3).map(j=><p key={j.id}>{j.symbol} · {j.kind} · {label(j.status)} {j.error || ''}</p>)}
    {!report && <p className="work-hint">{l.empty}</p>}
    {jobs.filter(j=>j.result).slice(0,5).map(j=>{const r=j.result!;return <article key={j.id} className="work-result">
      <h3>{j.symbol} · {label(r.decision.action)} · {j.kind}</h3>
      <small>{r.model} · {l.generated}: {r.analysis_at || r.generated_at} · {r.rule_version} · {r.prompt_version}</small>
      <p>{l.quote}: {r.quote_time || '—'} {r.quote_available_at ? `(${r.quote_available_at})` : ''} · {l.position}: {r.position_time || '—'} {r.decision.position_stale ? ` · ${r.decision.reason}` : r.decision.stale && ` · ${l.stale}`}</p>
      <button className="secondary-button" disabled={replay.isPending} onClick={() => replay.mutate(j.id)}>{replayLabel}</button>
      {replay.data?.id === j.id && <p>{label(replay.data.result.decision.action)} · {replay.data.result.analysis_at} · {replay.data.result.input_hash.slice(0, 12)}</p>}
      {replay.isError && replay.variables === j.id && <p className="inline-alert" role="alert">{replay.error.message}</p>}
      <p>{r.explanation.summary}</p>
      <h4>{l.risks}</h4><ul>{r.explanation.risks.map((v,i)=><li key={i}>{v}</li>)}</ul>
      <h4>{l.conditions}</h4><ul>{r.explanation.conditions.map((v,i)=><li key={i}>{v}</li>)}</ul>
      <details><summary>{l.evidence}</summary>{r.explanation.claims.map((c,i)=><blockquote key={i}>{c.text}<br/>“{c.quote}”</blockquote>)}{r.evidence.map(e=><p key={e.id}>{e.source} · {e.available_at} {e.url && /^https?:\/\//.test(e.url) && <a href={e.url} target="_blank" rel="noreferrer">{e.url}</a>}</p>)}</details>
      {r.decision.simulation_eligible && <a href="#/trading">{l.trade}</a>}
    </article>})}
    {report && chosenSymbol && <div className="form-row"><button className="secondary-button" disabled={submit.isPending} onClick={()=>submit.mutate('review')}>{l.review}</button><input aria-label={l.ask} placeholder={l.ask} value={question} onChange={e=>setQuestion(e.target.value)} maxLength={1000}/><button className="secondary-button" disabled={!question.trim() || submit.isPending} onClick={()=>submit.mutate('question')}>{l.ask}</button></div>}
    {controls && <details><summary>{l.status} · {runtime.data?.status}</summary>
      {runtime.error && <p className="inline-alert" role="alert">{runtime.error.message}</p>}
      <ul>{Object.entries(runtime.data?.services ?? {}).map(([name, service]) => <li key={name}>
        {name} · {service.status}
        {service.ingestion_in_progress && (lang === 'zh-CN' ? ' · 正在抓取新闻' : lang === 'ja' ? ' · ニュース取得中' : ' · Fetching news')}
        {service.last_success ? `· ${new Date(service.last_success).toLocaleString()}` : ''}
        {service.last_ingestion ? ` · ${new Date(service.last_ingestion).toLocaleString()}` : ''}
        {service.retry_in_seconds > 0 ? ` · ${service.retry_in_seconds}s` : ''} {service.error}
      </li>)}</ul>
    </details>}
    {controls && cfg && <details><summary>{l.settings}</summary><div className="form-row"><label className="check-field"><input type="checkbox" checked={cfg.enabled} onChange={e=>edit({enabled:e.target.checked})}/>{l.auto}</label>
      {([['interval_seconds',l.frequency],['target_rpm',l.quota],['background_rpm',l.background]] as const).map(([key,title])=><label key={key} className="field">{title}<input type="number" value={cfg[key]} onChange={e=>edit({[key]:Number(e.target.value)})}/></label>)}
      <label className="field">{l.cap}<input type="number" min={1} max={25} value={cfg.position_limit*100} onChange={e=>edit({position_limit:Number(e.target.value)/100})}/></label>
      {chosenSymbol && <label className="field">{l.allocation}<input type="number" min={1} max={100} value={(cfg.allocation_targets[chosenAccount+':'+chosenSymbol] || 0)*100} onChange={e=>edit({allocation_targets:{...cfg.allocation_targets,[chosenAccount+':'+chosenSymbol]:Number(e.target.value)/100}})}/></label>}
      <button className="secondary-button" disabled={!draft || save.isPending} onClick={()=>save.mutate()}>{l.save}</button></div>
      <h4>{l.status}</h4>{status.data && <><p>{status.data.calls_last_minute} / {cfg.target_rpm} · {l.generated}: {status.data.last_success || '—'}</p><ul>{Object.entries(status.data.jobs).map(([state,count])=><li key={state}>{label(state)}: {count}</li>)}</ul>{Object.entries(status.data.models).map(([task,model])=><p key={task}>{task} · {model.model} · {model.configured ? '✓' : '—'}</p>)}</>}
    </details>}
  </section>
}
