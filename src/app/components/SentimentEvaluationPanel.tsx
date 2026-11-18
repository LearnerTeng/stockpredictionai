import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import type { SentimentEvaluationInput } from '../types'

const copy = {
  'zh-CN': {title: '新闻情绪的增量预测评估', symbols: '标的（逗号分隔）', start: '起始日期', end: '结束日期',
    run: '评估当前模型', replay: '按原模型与截止时点重跑', samples: '配对样本', horizon: '交易日',
    empty: '历史数据不足', baseline: '仅价格', sentiment: '价格与情绪', stats: '平均绝对误差（百分点） / 方向命中率',
    coverage: '历史覆盖（标的行情 / 基准行情 / 有新闻的交易日 / 总交易日）'},
  en: {title: 'Incremental news sentiment evaluation', symbols: 'Symbols (comma separated)', start: 'Start date', end: 'End date',
    run: 'Evaluate current model', replay: 'Replay pinned model and cutoff', samples: 'Paired samples', horizon: 'sessions',
    empty: 'Insufficient historical data', baseline: 'Price only', sentiment: 'Price + sentiment', stats: 'MAE (percentage points) / Direction accuracy',
    coverage: 'History coverage (stock bars / benchmark bars / sessions with news / total sessions)'},
  ja: {title: 'ニュース感情の追加効果', symbols: '銘柄（カンマ区切り）', start: '開始日', end: '終了日',
    run: '現在のモデルで評価', replay: '元のモデルと基準時刻で再実行', samples: '対応サンプル', horizon: '取引日',
    empty: '履歴データ不足', baseline: '株価のみ', sentiment: '株価と感情', stats: '平均絶対誤差（ポイント） / 方向正解率',
    coverage: '履歴の範囲（銘柄価格 / ベンチマーク価格 / ニュースあり / 全取引日）'},
}

export function SentimentEvaluationPanel() {
  const {i18n} = useTranslation()
  const labels = copy[i18n.resolvedLanguage as keyof typeof copy] ?? copy.en
  const cache = useQueryClient()
  const saved = useQuery({queryKey: ['sentiment-evaluation'], queryFn: api.lastSentimentEvaluation})
  const [symbols, setSymbols] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [line, setLine] = useState<SentimentEvaluationInput['line']>('deepseek')
  const run = useMutation({mutationFn: api.evaluateSentiment,
    onSuccess: report => cache.setQueryData(['sentiment-evaluation'], {report})})
  const shown = run.data ?? saved.data?.report
  const inputs = {start, end, symbols: symbols.split(',').map(item => item.trim()).filter(Boolean), line}
  const error = run.error || saved.error
  return <section className="panel work-panel">
    <div className="work-panel-heading"><h2>{labels.title}</h2></div>
    <form className="work-form" onSubmit={event => {event.preventDefault(); run.mutate(inputs)}}>
      <label className="field">{labels.symbols} <input required placeholder="AAPL, 7203.T" value={symbols} onChange={event => setSymbols(event.target.value)} /></label>
      <div className="form-row"><label className="field">{labels.start} <input type="date" required value={start} onChange={event => setStart(event.target.value)} /></label>{' '}
      <label className="field">{labels.end} <input type="date" required value={end} onChange={event => setEnd(event.target.value)} /></label>{' '}
      <select aria-label="News model" value={line} onChange={event => setLine(event.target.value as SentimentEvaluationInput['line'])}>
        <option value="deepseek">DeepSeek</option><option value="ultra">Ultra</option>
      </select></div>
      <div className="form-row"><button className="primary-button" disabled={run.isPending}>{labels.run}</button>{' '}
      {shown && <button type="button" className="secondary-button" disabled={run.isPending} onClick={() => run.mutate(shown.inputs)}>{labels.replay}</button>}</div>
    </form>
    {error && <p className="inline-alert" role="alert">{error.message}</p>}
    {shown && <>
      <p>{shown.inputs.start} → {shown.inputs.end} · {shown.inputs.symbols.join(', ')} · {shown.inputs.as_of}</p>
      {Object.values(shown.inputs.model_pins ?? {}).map(pin => <p key={pin.model}>{pin.provider} / {pin.model} · {pin.version}</p>)}
      <p>{labels.stats}</p>
      {(['US', 'JP'] as const).map(market => <div key={market}><h3>{market} · {shown.benchmarks[market]}</h3>
        {shown.metrics[market].map(row => <p key={row.horizon}>{row.horizon} {labels.horizon} · {labels.samples} {row.samples}
          {row.baseline && row.sentiment ? ` · ${labels.baseline} ${row.baseline.mae_pct.toFixed(2)} / ${(100 * row.baseline.direction_accuracy).toFixed(1)}% · ${labels.sentiment} ${row.sentiment.mae_pct.toFixed(2)} / ${(100 * row.sentiment.direction_accuracy).toFixed(1)}%` : ` · ${labels.empty}`}
        </p>)}
      </div>)}
      <details><summary>{labels.coverage}</summary>
        {Object.entries(shown.coverage).map(([symbol, row]) => <p key={symbol}>{symbol} · {row.stock_bars} / {row.benchmark_bars} / {row.sessions_with_news} / {row.exchange_sessions}</p>)}
      </details>
    </>}
  </section>
}
