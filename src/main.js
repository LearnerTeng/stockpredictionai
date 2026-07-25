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
const dashboardState = {
  recommendations: [
    {
      symbol: 'NVDA',
      company: 'NVIDIA',
      score: 92,
      stance: 'Strong Buy',
      momentum: '+6.8%',
      thesis: 'AI infrastructure demand remains the highest-conviction growth theme in the book.',
    },
    {
      symbol: 'MSFT',
      company: 'Microsoft',
      score: 88,
      stance: 'Accumulate',
      momentum: '+4.1%',
      thesis: 'Cloud cash flow and platform breadth keep quality high with lower drawdown risk.',
    },
    {
      symbol: 'AMZN',
      company: 'Amazon',
      score: 81,
      stance: 'Watch Positive',
      momentum: '+3.4%',
      thesis: 'Margin expansion remains intact, but entry quality improves on softer pullbacks.',
    },
    {
      symbol: 'AAPL',
      company: 'Apple',
      score: 74,
      stance: 'Neutral Positive',
      momentum: '+1.9%',
      thesis: 'Defensive megacap exposure offsets volatility, though upside is less explosive.',
    },
  ],
  holdings: [
    { symbol: 'NVDA', shares: 60, avgCost: 118.2, currentPrice: 132.4 },
    { symbol: 'MSFT', shares: 40, avgCost: 412.6, currentPrice: 438.15 },
    { symbol: 'SPY', shares: 55, avgCost: 531.4, currentPrice: 548.2 },
    { symbol: 'TSLA', shares: 24, avgCost: 211.8, currentPrice: 198.65 },
  ],
  marketCurve: {
    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Mon', 'Tue', 'Wed'],
    values: [5720, 5768, 5742, 5790, 5815, 5848, 5866, 5892],
  },
  profitCurve: {
    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'],
    values: [0, 2.4, 5.8, 8.6, 11.3, 15.1, 18.42],
  },
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
let recommendationListEl
let holdingsListEl
let marketCurveCanvas
let marketCurveCtx
let profitCurveCanvas
let profitCurveCtx
let topPickSymbolEl
let topPickScoreEl
let portfolioValueEl
let portfolioDailyChangeEl
let portfolioReturnEl
let portfolioReturnCopyEl
let riskPostureEl
let riskCopyEl

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

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

function formatMoney(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value)
}

function formatCompactMoney(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

function formatSignedPercent(value) {
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
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

function drawLinePanel(canvasEl, context, config) {
  const dpr = window.devicePixelRatio || 1
  const rect = canvasEl.getBoundingClientRect()
  const displayWidth = Math.max(rect.width, 320)
  const displayHeight = rect.height || 320

  canvasEl.width = Math.round(displayWidth * dpr)
  canvasEl.height = Math.round(displayHeight * dpr)
  context.setTransform(1, 0, 0, 1, 0, 0)
  context.scale(dpr, dpr)
  context.clearRect(0, 0, displayWidth, displayHeight)

  const padding = { top: 24, right: 18, bottom: 40, left: 48 }
  const width = displayWidth - padding.left - padding.right
  const height = displayHeight - padding.top - padding.bottom
  const values = config.values
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = Math.max(max - min, 1)
  const toX = (index) => padding.left + (index / Math.max(values.length - 1, 1)) * width
  const toY = (value) => padding.top + (1 - (value - min) / range) * height

  context.fillStyle = '#08111f'
  context.fillRect(0, 0, displayWidth, displayHeight)

  context.strokeStyle = 'rgba(148, 163, 184, 0.1)'
  context.lineWidth = 1
  for (let step = 0; step <= 4; step += 1) {
    const y = padding.top + (height / 4) * step
    context.beginPath()
    context.moveTo(padding.left, y)
    context.lineTo(padding.left + width, y)
    context.stroke()
  }

  const gradient = context.createLinearGradient(0, padding.top, 0, padding.top + height)
  gradient.addColorStop(0, config.fillTop)
  gradient.addColorStop(1, 'rgba(8, 17, 31, 0)')

  context.beginPath()
  values.forEach((value, index) => {
    const x = toX(index)
    const y = toY(value)
    if (index === 0) {
      context.moveTo(x, y)
    } else {
      context.lineTo(x, y)
    }
  })
  context.lineTo(padding.left + width, padding.top + height)
  context.lineTo(padding.left, padding.top + height)
  context.closePath()
  context.fillStyle = gradient
  context.fill()

  context.strokeStyle = config.stroke
  context.lineWidth = 3
  context.beginPath()
  values.forEach((value, index) => {
    const x = toX(index)
    const y = toY(value)
    if (index === 0) {
      context.moveTo(x, y)
    } else {
      context.lineTo(x, y)
    }
  })
  context.stroke()

  context.fillStyle = '#94a3b8'
  context.font = '12px Inter, sans-serif'
  context.fillText(max.toFixed(config.decimals ?? 0), 8, padding.top + 4)
  context.fillText(min.toFixed(config.decimals ?? 0), 8, padding.top + height)

  context.textAlign = 'center'
  config.labels.forEach((label, index) => {
    context.fillText(label, toX(index), padding.top + height + 22)
  })
  context.textAlign = 'start'
}

function renderRecommendationList() {
  recommendationListEl.innerHTML = dashboardState.recommendations
    .map(
      (item, index) => `
        <article class="recommendation-item" data-rank="${index + 1}">
          <div class="recommendation-head">
            <div>
              <span class="recommendation-rank">#${index + 1}</span>
              <h4>${item.symbol}</h4>
              <p>${item.company}</p>
            </div>
            <div class="score-orb">${item.score}</div>
          </div>
          <div class="recommendation-meta">
            <span>${item.stance}</span>
            <strong>${item.momentum}</strong>
          </div>
          <div class="score-track">
            <span style="width:${item.score}%"></span>
          </div>
          <p class="recommendation-thesis">${item.thesis}</p>
        </article>
      `
    )
    .join('')
}

function renderHoldingsList() {
  holdingsListEl.innerHTML = dashboardState.holdings
    .map((holding) => {
      const marketValue = holding.shares * holding.currentPrice
      const pnl = (holding.currentPrice - holding.avgCost) * holding.shares
      const pnlPct = holding.avgCost ? ((holding.currentPrice - holding.avgCost) / holding.avgCost) * 100 : 0
      const pnlClass = pnl >= 0 ? 'is-profit' : 'is-loss'
      return `
        <article class="holding-row">
          <div class="holding-symbol">
            <strong>${holding.symbol}</strong>
            <span>${holding.shares} shares</span>
          </div>
          <div class="holding-stat">
            <span>Avg Cost</span>
            <strong>${formatMoney(holding.avgCost)}</strong>
          </div>
          <div class="holding-stat">
            <span>Current</span>
            <strong>${formatMoney(holding.currentPrice)}</strong>
          </div>
          <div class="holding-stat">
            <span>Market Value</span>
            <strong>${formatCompactMoney(marketValue)}</strong>
          </div>
          <div class="holding-stat ${pnlClass}">
            <span>P/L</span>
            <strong>${formatCompactMoney(pnl)} · ${formatSignedPercent(pnlPct)}</strong>
          </div>
        </article>
      `
    })
    .join('')
}

function renderPortfolioSummary() {
  const sortedRecommendations = [...dashboardState.recommendations].sort((left, right) => right.score - left.score)
  const topPick = sortedRecommendations[0]
  const portfolioValue = dashboardState.holdings.reduce(
    (sum, holding) => sum + holding.shares * holding.currentPrice,
    0
  )
  const costBasis = dashboardState.holdings.reduce((sum, holding) => sum + holding.shares * holding.avgCost, 0)
  const totalReturnPct = costBasis ? ((portfolioValue - costBasis) / costBasis) * 100 : 0
  const equitySeries = dashboardState.profitCurve.values
  const lastStep = equitySeries[equitySeries.length - 1]
  const previousStep = equitySeries[equitySeries.length - 2] ?? lastStep
  const sessionChange = lastStep - previousStep
  const profitableCount = dashboardState.holdings.filter((holding) => holding.currentPrice >= holding.avgCost).length

  topPickSymbolEl.textContent = topPick?.symbol || '--'
  topPickScoreEl.textContent = topPick ? `${topPick.score} / 100 conviction` : 'No signals'
  portfolioValueEl.textContent = formatCompactMoney(portfolioValue)
  portfolioDailyChangeEl.textContent = `${formatSignedPercent(sessionChange)} latest step`
  portfolioReturnEl.textContent = formatSignedPercent(totalReturnPct)
  portfolioReturnCopyEl.textContent = 'Marked against current average cost across held positions'
  riskPostureEl.textContent = profitableCount >= 3 ? 'Balanced Growth' : 'Selective Risk'
  riskCopyEl.textContent = `${profitableCount}/${dashboardState.holdings.length} positions are above cost basis`
}

function drawDashboardCharts() {
  drawLinePanel(marketCurveCanvas, marketCurveCtx, {
    labels: dashboardState.marketCurve.labels,
    values: dashboardState.marketCurve.values,
    stroke: '#38bdf8',
    fillTop: 'rgba(56, 189, 248, 0.24)',
    decimals: 0,
  })

  drawLinePanel(profitCurveCanvas, profitCurveCtx, {
    labels: dashboardState.profitCurve.labels,
    values: dashboardState.profitCurve.values,
    stroke: '#22c55e',
    fillTop: 'rgba(34, 197, 94, 0.24)',
    decimals: 1,
  })
}

function renderPortfolioDeck() {
  renderRecommendationList()
  renderHoldingsList()
  renderPortfolioSummary()
  drawDashboardCharts()
}

function syncRecommendationFromPrediction(prediction) {
  const latestClose = prediction.historical_tail[prediction.historical_tail.length - 1] || 0
  const avgPrediction =
    prediction.predictions.reduce((sum, value) => sum + value, 0) / Math.max(prediction.predictions.length, 1)
  const projectedMovePct = latestClose ? ((avgPrediction - latestClose) / latestClose) * 100 : 0
  const conviction = clamp(Math.round(72 + projectedMovePct * 4 - prediction.metrics.rmse * 0.25), 36, 97)
  const stance =
    projectedMovePct >= 4 ? 'High Momentum' : projectedMovePct >= 1 ? 'Constructive' : projectedMovePct >= -1 ? 'Watch' : 'Defensive'
  const thesis =
    projectedMovePct >= 0
      ? `Model projects an average ${projectedMovePct.toFixed(2)}% move above the latest close over ${prediction.forecast_steps} sessions.`
      : `Model flags a softer path, projecting ${Math.abs(projectedMovePct).toFixed(2)}% downside over ${prediction.forecast_steps} sessions.`

  const existingIndex = dashboardState.recommendations.findIndex((item) => item.symbol === prediction.symbol)
  const nextEntry = {
    symbol: prediction.symbol,
    company: `${prediction.symbol} signal`,
    score: conviction,
    stance,
    momentum: formatSignedPercent(projectedMovePct),
    thesis,
  }

  if (existingIndex >= 0) {
    dashboardState.recommendations[existingIndex] = {
      ...dashboardState.recommendations[existingIndex],
      ...nextEntry,
    }
  } else {
    dashboardState.recommendations.unshift(nextEntry)
    dashboardState.recommendations = dashboardState.recommendations.slice(0, 5)
  }

  dashboardState.recommendations.sort((left, right) => right.score - left.score)
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
    syncRecommendationFromPrediction(data)
    renderPortfolioDeck()
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
  if (marketCurveCtx && profitCurveCtx) {
    drawDashboardCharts()
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
  recommendationListEl = document.querySelector('#recommendation-list')
  holdingsListEl = document.querySelector('#holdings-list')
  marketCurveCanvas = document.querySelector('#market-curve-chart')
  profitCurveCanvas = document.querySelector('#profit-curve-chart')
  topPickSymbolEl = document.querySelector('#top-pick-symbol')
  topPickScoreEl = document.querySelector('#top-pick-score')
  portfolioValueEl = document.querySelector('#portfolio-value')
  portfolioDailyChangeEl = document.querySelector('#portfolio-daily-change')
  portfolioReturnEl = document.querySelector('#portfolio-return')
  portfolioReturnCopyEl = document.querySelector('#portfolio-return-copy')
  riskPostureEl = document.querySelector('#risk-posture')
  riskCopyEl = document.querySelector('#risk-copy')
  ctx = canvas?.getContext('2d')
  marketCurveCtx = marketCurveCanvas?.getContext('2d')
  profitCurveCtx = profitCurveCanvas?.getContext('2d')

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
    !viewInsightsLinkEl ||
    !recommendationListEl ||
    !holdingsListEl ||
    !marketCurveCanvas ||
    !profitCurveCanvas ||
    !topPickSymbolEl ||
    !topPickScoreEl ||
    !portfolioValueEl ||
    !portfolioDailyChangeEl ||
    !portfolioReturnEl ||
    !portfolioReturnCopyEl ||
    !riskPostureEl ||
    !riskCopyEl ||
    !marketCurveCtx ||
    !profitCurveCtx
  ) {
    throw new Error('One or more required UI nodes failed to mount')
  }

  apiLabelEl.textContent = `API: ${API_BASE}`
  resetMetrics()
  resetAiSummary()
  setStatus('Ready to request a forecast.', 'neutral')
  drawChart(chartState.historical, chartState.predictions)
  renderPortfolioDeck()
  setupScrollAnimations()
  form.addEventListener('submit', runPrediction)
} catch (error) {
  console.error(error)
  renderCrash(error)
}
