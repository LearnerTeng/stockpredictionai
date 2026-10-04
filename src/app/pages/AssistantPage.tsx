import { useMutation } from '@tanstack/react-query'
import { Bot, BrainCircuit, Database, ShieldAlert, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { PageHeader } from '../components/UI'
import type { AnalysisResult, UiLanguage } from '../types'

export function AssistantPage() {
  const { t, i18n } = useTranslation('assistant')
  const [symbol, setSymbol] = useState('NVDA')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const analysis = useMutation({
    mutationFn: async () => {
      const prediction = await api.predict(symbol.trim().toUpperCase())
      return api.analyze(prediction, (i18n.resolvedLanguage ?? i18n.language) as UiLanguage)
    },
    onSuccess: setResult,
  })

  return (
    <>
      <PageHeader eyebrow={t('eyebrow')} title={t('title')} description={t('description')} />
      <section className="assistant-layout">
        <aside className="panel assistant-context">
          <div className="assistant-orb"><BrainCircuit /></div><h2>{t('boundaries')}</h2>
          <div className="context-item"><Database /><div><strong>{t('dataOnlyTitle')}</strong><span>{t('dataOnlyText')}</span></div></div>
          <div className="context-item"><ShieldAlert /><div><strong>{t('noOrdersTitle')}</strong><span>{t('noOrdersText')}</span></div></div>
          <div className="context-item"><Bot /><div><strong>{t('fallbackTitle')}</strong><span>{t('fallbackText')}</span></div></div>
        </aside>
        <div className="assistant-main">
          <article className="panel analysis-composer">
            <label htmlFor="assistant-symbol">{t('symbol')}</label>
            <div><input id="assistant-symbol" value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} maxLength={16} /><button className="primary-button" onClick={() => analysis.mutate()} disabled={!symbol.trim() || analysis.isPending}><Sparkles size={17} />{analysis.isPending ? t('running') : t('generate')}</button></div>
            <p>{t('process')}</p>
          </article>
          {analysis.error && <div className="inline-alert">{analysis.error.message}</div>}
          {result ? <article className="panel analysis-result"><span className="eyebrow">AI ANALYSIS · {result.language}</span><h2>{result.title}</h2><p className="analysis-summary">{result.summary}</p><div className="analysis-sections">{result.sections.map((section) => <section key={section.heading}><h3>{section.heading}</h3><ul>{section.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}</ul></section>)}</div><footer>{result.disclaimer}</footer></article> : <article className="panel assistant-empty"><Sparkles /><h2>{t('waitingTitle')}</h2><p>{t('waitingText')}</p></article>}
        </div>
      </section>
    </>
  )
}
