import { useMutation } from '@tanstack/react-query'
import { Bot, BrainCircuit, Database, ShieldAlert, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import { PageHeader } from '../components/UI'
import type { AnalysisResult } from '../types'

export function AssistantPage() {
  const [symbol, setSymbol] = useState('NVDA')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const analysis = useMutation({
    mutationFn: async () => {
      const prediction = await api.predict(symbol.trim().toUpperCase())
      return api.analyze(prediction)
    },
    onSuccess: setResult,
  })

  return (
    <>
      <PageHeader eyebrow="Model interpretation" title="AI 分析助手" description="先运行数值预测，再由 AI 解释模型形态、误差与风险；不会生成自动交易指令。" />
      <section className="assistant-layout">
        <aside className="panel assistant-context">
          <div className="assistant-orb"><BrainCircuit /></div><h2>分析边界</h2>
          <div className="context-item"><Database /><div><strong>仅使用后端预测数据</strong><span>不虚构新闻、财报或实时行情</span></div></div>
          <div className="context-item"><ShieldAlert /><div><strong>不直接给出买卖指令</strong><span>订单必须经过独立风控与确认</span></div></div>
          <div className="context-item"><Bot /><div><strong>本地降级可用</strong><span>未配置 OpenAI Key 时返回规则解释</span></div></div>
        </aside>
        <div className="assistant-main">
          <article className="panel analysis-composer">
            <label htmlFor="assistant-symbol">股票代码</label>
            <div><input id="assistant-symbol" value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} maxLength={16} /><button className="primary-button" onClick={() => analysis.mutate()} disabled={!symbol.trim() || analysis.isPending}><Sparkles size={17} />{analysis.isPending ? '预测与分析中...' : '生成模型解读'}</button></div>
            <p>分析过程会调用 `/predict`，随后把结构化预测传给 `/ai/analyze`。</p>
          </article>
          {analysis.error && <div className="inline-alert">{analysis.error.message}</div>}
          {result ? <article className="panel analysis-result"><span className="eyebrow">AI ANALYSIS</span><h2>{result.title}</h2><p className="analysis-summary">{result.summary}</p><div className="analysis-sections">{result.sections.map((section) => <section key={section.heading}><h3>{section.heading}</h3><ul>{section.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}</ul></section>)}</div><footer>{result.disclaimer}</footer></article> : <article className="panel assistant-empty"><Sparkles /><h2>等待分析任务</h2><p>输入已导入历史数据的股票代码，系统将生成可审计的模型解释。</p></article>}
        </div>
      </section>
    </>
  )
}
