import './style.css'
import { createFeatures } from './components/features'
import { createFooter } from './components/footer'
import { createHeader } from './components/header'
import { createHero } from './components/hero'
import { createModels } from './components/models'
import { createPredictor } from './components/predictor'
import { createResults } from './components/results'
import { renderAnalysisSections } from './lib/analysis-render'
import { API_BASE, postJson } from './lib/api'
import { saveLatestPrediction } from './lib/prediction-store'

const app = document.querySelector('#app')
const defaultChartData = {
  historical: [185, 188, 190, 193, 191, 195],
  predictions: [195, 197, 198, 200, 202],
}
const emptySummaryText =
  'This area will show an AI-generated explanation of the latest prediction, using only the current model output and historical tail returned by the backend.'

let chartState = { ...defaultChartData }
let form
let statusEl
let symbolMetric
let maeMetric
let rmseMetric
let horizonMetric
let summaryEl
let valuesEl
let apiLabelEl
let canvas
let ctx
let aiSummaryTitleEl
let aiSummaryStatusEl
let aiSummaryTextEl
let aiSummarySectionsEl
let viewInsightsLinkEl

function renderCrash(error) {
  const details = error instanceof Error ? `${error.message}\n\n${error.stack || ''}` : String(error)
  document.body.innerHTML = `
    <main style="padding:40px;font-family:Inter,system-ui,sans-serif;background:#07111f;color:#e2e8f0;min-height:100vh;">
      <section style="max-width:960px;margin:0 auto;border:1px solid rgba(251,113,133,.25);background:rgba(15,23,42,.88);border-radius:24px;padding:24px;">
        <h1 style="margin:0 0 12px;font-size:28px;">Frontend Runtime Error</h1>
        <p style="margin:0 0 16px;color:#cbd5e1;">The page failed before render completed. The error details are shown below.</p>
        <pre style="margin:0;white-space:pre-wrap;word-break:break-word;color:#fecdd3;">${details}</pre>
      </section>
    </main>
  `
}

function setStatus(message, tone = 'neutral') {
  statusEl.textContent = message
  statusEl.dataset.tone = tone
}

function setAiSummaryStatus(message, tone = 'neutral') {
  aiSummaryStatusEl.textContent = message
  aiSummaryStatusEl.dataset.tone = tone
}

function updateMetric(element, value) {
  element.textContent = value
}

function setInsightsLinkEnabled(enabled) {
  viewInsightsLinkEl.classList.toggle('is-disabled', !enabled)
  viewInsightsLinkEl.setAttribute('aria-disabled', String(!enabled))
  if (enabled) {
    viewInsightsLinkEl.href = '/insights.html'
  } else {
    viewInsightsLinkEl.href = '#'
  }
}

function resetAiSummary() {
  aiSummaryTitleEl.textContent = 'Generate a prediction to unlock AI interpretation.'
  aiSummaryTextEl.textContent = emptySummaryText
  setAiSummaryStatus('The summary is generated from the prediction output after a successful forecast.', 'neutral')
  renderAnalysisSections(aiSummarySectionsEl, [])
  setInsightsLinkEnabled(false)
}

function resetMetrics() {
  updateMetric(symbolMetric, '--')
  updateMetric(maeMetric, '--')
  updateMetric(rmseMetric, '--')
  updateMetric(horizonMetric, '--')
  summaryEl.textContent = 'No prediction has been requested yet.'
  valuesEl.textContent = 'Values will appear here after a successful API response.'
  chartState = { ...defaultChartData }
}

function drawChart(historical, predictions) {
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  const displayWidth = Math.max(rect.width, 320)
  const displayHeight = rect.height || 360

  canvas.width = Math.round(displayWidth * dpr)
  canvas.height = Math.round(displayHeight * dpr)
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, displayWidth, displayHeight)

  const padding = { top: 28, right: 24, bottom: 42, left: 58 }
  const width = displayWidth - padding.left - padding.right
  const height = displayHeight - padding.top - padding.bottom
  const allValues = [...historical, ...predictions]
  const min = Math.min(...allValues)
  const max = Math.max(...allValues)
  const range = Math.max(max - min, 1)
  const totalPoints = allValues.length
  const forecastStartIndex = historical.length - 1

  const toX = (index) => padding.left + (index / Math.max(totalPoints - 1, 1)) * width
  const toY = (value) => padding.top + (1 - (value - min) / range) * height

  ctx.fillStyle = '#08111f'
  ctx.fillRect(0, 0, displayWidth, displayHeight)

  ctx.strokeStyle = 'rgba(148, 163, 184, 0.12)'
  ctx.lineWidth = 1
  for (let step = 0; step <= 4; step += 1) {
    const y = padding.top + (height / 4) * step
    ctx.beginPath()
    ctx.moveTo(padding.left, y)
    ctx.lineTo(padding.left + width, y)
    ctx.stroke()
  }

  ctx.strokeStyle = 'rgba(148, 163, 184, 0.45)'
  ctx.beginPath()
  ctx.moveTo(padding.left, padding.top)
  ctx.lineTo(padding.left, padding.top + height)
  ctx.lineTo(padding.left + width, padding.top + height)
  ctx.stroke()

  ctx.fillStyle = '#94a3b8'
  ctx.font = '12px Inter, sans-serif'
  ctx.fillText(max.toFixed(2), 10, padding.top + 4)
  ctx.fillText(min.toFixed(2), 10, padding.top + height)

  ctx.strokeStyle = '#38bdf8'
  ctx.lineWidth = 3
  ctx.beginPath()
  historical.forEach((value, index) => {
    const x = toX(index)
    const y = toY(value)
    if (index === 0) {
      ctx.moveTo(x, y)
    } else {
      ctx.lineTo(x, y)
    }
  })
  ctx.stroke()

  ctx.strokeStyle = '#f59e0b'
  ctx.lineWidth = 3
  ctx.beginPath()
  predictions.forEach((value, index) => {
    const x = toX(forecastStartIndex + index)
    const y = toY(value)
    if (index === 0) {
      ctx.moveTo(x, y)
    } else {
      ctx.lineTo(x, y)
    }
  })
  ctx.stroke()

  const dividerX = toX(forecastStartIndex)
  ctx.setLineDash([6, 6])
  ctx.strokeStyle = 'rgba(248, 250, 252, 0.35)'
  ctx.beginPath()
  ctx.moveTo(dividerX, padding.top)
  ctx.lineTo(dividerX, padding.top + height)
  ctx.stroke()
  ctx.setLineDash([])

  ctx.fillStyle = '#38bdf8'
  ctx.fillRect(padding.left, 12, 12, 12)
  ctx.fillStyle = '#e2e8f0'
  ctx.fillText('Historical close', padding.left + 20, 22)
  ctx.fillStyle = '#f59e0b'
  ctx.fillRect(padding.left + 132, 12, 12, 12)
  ctx.fillStyle = '#e2e8f0'
  ctx.fillText('Forecast', padding.left + 152, 22)
}

function setupScrollAnimations() {
  const animatedNodes = document.querySelectorAll('.animate-on-scroll')
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible')
          observer.unobserve(entry.target)
        }
      })
    },
    { threshold: 0.16 }
  )

  animatedNodes.forEach((node) => observer.observe(node))
}

async function generateAiSummary(prediction) {
  setAiSummaryStatus('Generating AI summary from the latest prediction...', 'loading')
  aiSummaryTitleEl.textContent = 'Generating summary...'
  aiSummaryTextEl.textContent = 'The backend is requesting a structured AI interpretation.'
  renderAnalysisSections(aiSummarySectionsEl, [])

  try {
    const analysis = await postJson('/ai/analyze', {
      analysis_mode: 'summary',
      prediction,
    })

    aiSummaryTitleEl.textContent = analysis.title
    aiSummaryTextEl.textContent = analysis.summary
    setAiSummaryStatus(`AI summary ready at ${new Date(analysis.generated_at).toLocaleString()}.`, 'success')
    renderAnalysisSections(aiSummarySectionsEl, analysis.sections)
  } catch (error) {
    aiSummaryTitleEl.textContent = 'AI summary unavailable'
    aiSummaryTextEl.textContent =
      'The prediction succeeded, but the AI summary could not be generated right now. You can still open the full insights page and try again later.'
    setAiSummaryStatus(error.message, 'error')
    renderAnalysisSections(aiSummarySectionsEl, [])
  }
}

async function runPrediction(event) {
  event.preventDefault()

  const formData = new FormData(form)
  const payload = {
    symbol: String(formData.get('symbol') || '').trim().toUpperCase(),
    history_window: Number(formData.get('history_window')),
    forecast_steps: Number(formData.get('forecast_steps')),
  }

  const submitBtn = document.querySelector('#submit-btn')
  submitBtn.disabled = true
  setStatus('Running forecast against backend model...', 'loading')
  valuesEl.textContent = 'Waiting for backend response...'
  resetAiSummary()

  try {
    const data = await postJson('/predict', payload)

    saveLatestPrediction(data)
    setInsightsLinkEnabled(true)

    updateMetric(symbolMetric, data.symbol)
    updateMetric(maeMetric, data.metrics.mae)
    updateMetric(rmseMetric, data.metrics.rmse)
    updateMetric(horizonMetric, `${data.forecast_steps} days`)

    summaryEl.textContent =
      `${data.symbol} returned ${data.forecast_steps} forward points with ` +
      `MAE ${data.metrics.mae} and RMSE ${data.metrics.rmse}.`
    valuesEl.textContent = data.predictions.join(', ')
    setStatus(`Forecast complete for ${data.symbol}.`, 'success')
    chartState = {
      historical: data.historical_tail,
      predictions: data.predictions,
    }
    drawChart(data.historical_tail, data.predictions)
    generateAiSummary(data)
  } catch (error) {
    resetMetrics()
    resetAiSummary()
    const message =
      error instanceof TypeError
        ? `Forecast failed: backend unreachable at ${API_BASE}`
        : `Forecast failed: ${error.message}`
    setStatus(message, 'error')
    drawChart(chartState.historical, chartState.predictions)
  } finally {
    submitBtn.disabled = false
  }
}

window.addEventListener('resize', () => {
  if (ctx) {
    drawChart(chartState.historical, chartState.predictions)
  }
})

try {
  if (!app) {
    throw new Error('Missing #app mount node')
  }

  app.innerHTML = `
    ${createHeader({ activePage: 'lab' })}
    <main>
      ${createHero()}
      ${createFeatures()}
      ${createModels()}
      ${createPredictor()}
      ${createResults()}
    </main>
    ${createFooter()}
  `

  form = document.querySelector('#predict-form')
  statusEl = document.querySelector('#status')
  symbolMetric = document.querySelector('#metric-symbol')
  maeMetric = document.querySelector('#metric-mae')
  rmseMetric = document.querySelector('#metric-rmse')
  horizonMetric = document.querySelector('#metric-horizon')
  summaryEl = document.querySelector('#prediction-summary')
  valuesEl = document.querySelector('#prediction-values')
  apiLabelEl = document.querySelector('#api-base-label')
  canvas = document.querySelector('#result-chart')
  aiSummaryTitleEl = document.querySelector('#ai-summary-title')
  aiSummaryStatusEl = document.querySelector('#ai-summary-status')
  aiSummaryTextEl = document.querySelector('#ai-summary-text')
  aiSummarySectionsEl = document.querySelector('#ai-summary-sections')
  viewInsightsLinkEl = document.querySelector('#view-insights-link')
  ctx = canvas?.getContext('2d')

  if (
    !form ||
    !statusEl ||
    !symbolMetric ||
    !maeMetric ||
    !rmseMetric ||
    !horizonMetric ||
    !summaryEl ||
    !valuesEl ||
    !apiLabelEl ||
    !canvas ||
    !ctx ||
    !aiSummaryTitleEl ||
    !aiSummaryStatusEl ||
    !aiSummaryTextEl ||
    !aiSummarySectionsEl ||
    !viewInsightsLinkEl
  ) {
    throw new Error('One or more required UI nodes failed to mount')
  }

  apiLabelEl.textContent = `API: ${API_BASE}`
  resetMetrics()
  resetAiSummary()
  setStatus('Ready to request a forecast.', 'neutral')
  drawChart(chartState.historical, chartState.predictions)
  setupScrollAnimations()
  form.addEventListener('submit', runPrediction)
} catch (error) {
  console.error(error)
  renderCrash(error)
}
