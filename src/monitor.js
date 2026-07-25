import './style.css'
import { createFooter } from './components/footer'
import { createHeader } from './components/header'
import { API_BASE, getJson, postJson } from './lib/api'

const app = document.querySelector('#app')

let form
let statusEl
let generatedAtEl
let cardsEl
let errorsEl
let canvas
let ctx
let latestItems = []

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '--'
  }
  return Number(value).toFixed(digits)
}

function setStatus(message, tone = 'neutral') {
  statusEl.textContent = message
  statusEl.dataset.tone = tone
}

function stanceLabel(stance) {
  if (stance === 'watch-positive') return 'Positive Watch'
  if (stance === 'watch-risk') return 'Risk Watch'
  return 'Neutral'
}

function renderErrors(errors = []) {
  if (!errors.length) {
    errorsEl.innerHTML = ''
    return
  }

  errorsEl.innerHTML = errors
    .map(
      (item) => `
        <article class="monitor-error">
          <strong>${item.symbol}</strong>
          <span>${item.error}</span>
        </article>
      `
    )
    .join('')
}

function renderCards(items = []) {
  if (!items.length) {
    cardsEl.innerHTML = `
      <article class="monitor-empty">
        <h2>No monitor data yet</h2>
        <p>Refresh the watchlist to fetch market bars, compute indicators, and generate local monitor signals.</p>
      </article>
    `
    drawOverview([])
    return
  }

  cardsEl.innerHTML = items
    .map((item) => {
      const indicators = item.indicators || {}
      const forecast = item.forecast || {}
      return `
        <article class="monitor-card" data-stance="${item.stance}">
          <div class="monitor-card-top">
            <div>
              <span>${item.trade_date || '--'}</span>
              <h2>${item.symbol}</h2>
            </div>
            <strong>${formatNumber(item.score, 1)}</strong>
          </div>
          <div class="monitor-price-row">
            <span>Close</span>
            <strong>${formatNumber(item.latest_close, 2)}</strong>
            <em>${formatNumber(item.change_pct, 2)}%</em>
          </div>
          <div class="monitor-stance">${stanceLabel(item.stance)}</div>
          <dl class="monitor-indicators">
            <div><dt>SMA 7 / 21</dt><dd>${formatNumber(indicators.sma_7)} / ${formatNumber(indicators.sma_21)}</dd></div>
            <div><dt>EMA 12 / 26</dt><dd>${formatNumber(indicators.ema_12)} / ${formatNumber(indicators.ema_26)}</dd></div>
            <div><dt>RSI 14</dt><dd>${formatNumber(indicators.rsi_14)}</dd></div>
            <div><dt>Vol 30D</dt><dd>${formatNumber((indicators.volatility_30d_annualized || 0) * 100, 1)}%</dd></div>
            <div><dt>Fourier Trend</dt><dd>${indicators.fourier_trend?.direction || '--'} (${formatNumber(indicators.fourier_trend?.strength, 2)})</dd></div>
            <div><dt>Forecast</dt><dd>${formatNumber(forecast.delta_pct, 2)}%, MAE ${formatNumber(forecast.mae)}</dd></div>
          </dl>
          <div class="monitor-alerts">
            ${(item.alerts || []).map((alert) => `<p>${alert}</p>`).join('')}
          </div>
        </article>
      `
    })
    .join('')
  drawOverview(items)
}

function drawOverview(items = []) {
  if (!ctx || !canvas) return

  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  const width = Math.max(rect.width, 320)
  const height = rect.height || 320
  canvas.width = Math.round(width * dpr)
  canvas.height = Math.round(height * dpr)
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, width, height)
  ctx.fillStyle = '#08111f'
  ctx.fillRect(0, 0, width, height)

  const padding = { top: 26, right: 20, bottom: 48, left: 46 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom

  ctx.strokeStyle = 'rgba(148, 163, 184, 0.16)'
  ctx.lineWidth = 1
  for (let step = 0; step <= 4; step += 1) {
    const y = padding.top + (chartHeight / 4) * step
    ctx.beginPath()
    ctx.moveTo(padding.left, y)
    ctx.lineTo(padding.left + chartWidth, y)
    ctx.stroke()
  }

  ctx.fillStyle = '#94a3b8'
  ctx.font = '12px Inter, sans-serif'
  ctx.fillText('100', 12, padding.top + 4)
  ctx.fillText('0', 22, padding.top + chartHeight)

  if (!items.length) {
    ctx.fillStyle = '#cbd5e1'
    ctx.fillText('Refresh monitor to draw scores.', padding.left, padding.top + 32)
    return
  }

  const barGap = 14
  const barWidth = Math.max((chartWidth - barGap * (items.length - 1)) / items.length, 18)
  items.forEach((item, index) => {
    const score = Math.min(Math.max(Number(item.score || 0), 0), 100)
    const x = padding.left + index * (barWidth + barGap)
    const barHeight = (score / 100) * chartHeight
    const y = padding.top + chartHeight - barHeight
    ctx.fillStyle = item.stance === 'watch-positive' ? '#22c55e' : item.stance === 'watch-risk' ? '#fb7185' : '#38bdf8'
    ctx.fillRect(x, y, barWidth, barHeight)
    ctx.fillStyle = '#e2e8f0'
    ctx.fillText(item.symbol, x, padding.top + chartHeight + 22)
  })
}

async function loadLocalStatus() {
  setStatus('Loading local monitor cache...', 'loading')
  try {
    const data = await getJson('/monitor/status')
    latestItems = data.items || []
    generatedAtEl.textContent = data.generated_at ? `Local cache: ${new Date(data.generated_at).toLocaleString()}` : ''
    renderCards(latestItems)
    renderErrors(data.errors || [])
    setStatus(latestItems.length ? 'Loaded local monitor cache.' : 'No local market data cache yet.', latestItems.length ? 'success' : 'neutral')
  } catch (error) {
    setStatus(`Local cache unavailable: ${error.message}`, 'error')
    renderCards([])
  }
}

async function refreshMonitor(event) {
  event.preventDefault()
  const formData = new FormData(form)
  const symbols = String(formData.get('symbols') || '')
    .split(',')
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean)
  const range = String(formData.get('range') || '1y')
  const submitBtn = form.querySelector('button')

  submitBtn.disabled = true
  setStatus('Fetching market bars and recomputing monitor signals...', 'loading')
  try {
    const data = await postJson('/monitor/run', { symbols, range })
    latestItems = data.items || []
    generatedAtEl.textContent = data.generated_at ? `Generated: ${new Date(data.generated_at).toLocaleString()}` : ''
    renderCards(latestItems)
    renderErrors(data.errors || [])
    setStatus(`Monitor refresh complete for ${latestItems.length} symbols.`, latestItems.length ? 'success' : 'error')
  } catch (error) {
    setStatus(`Monitor refresh failed: ${error.message}`, 'error')
  } finally {
    submitBtn.disabled = false
  }
}

function renderShell() {
  app.innerHTML = `
    ${createHeader({
      activePage: 'monitor',
      ctaHref: '/monitor.html',
      ctaLabel: 'Monitor',
    })}
    <main class="monitor-page">
      <section class="monitor-hero">
        <div class="container">
          <div class="monitor-hero-grid">
            <div>
              <p class="eyebrow">Local Market Monitor</p>
              <h1>README research concepts converted into a runnable watchlist system.</h1>
              <p class="page-lead">
                Fetch daily bars, persist them locally, compute technical indicators, Fourier trend strength,
                volatility, short-horizon forecast error, and threshold alerts.
              </p>
            </div>
            <form id="monitor-form" class="monitor-form">
              <label>
                Symbols
                <input name="symbols" value="AAPL,MSFT,NVDA,GS,SPY" />
              </label>
              <label>
                Range
                <select name="range">
                  <option value="1y">1 year</option>
                  <option value="6mo">6 months</option>
                  <option value="2y">2 years</option>
                  <option value="5y">5 years</option>
                </select>
              </label>
              <button class="btn-primary" type="submit">Refresh Monitor</button>
              <p class="monitor-api">Backend: ${API_BASE}</p>
            </form>
          </div>
        </div>
      </section>

      <section class="monitor-body">
        <div class="container">
          <div class="monitor-toolbar">
            <p id="monitor-status" class="status-banner" data-tone="neutral">Preparing monitor...</p>
            <p id="monitor-generated-at"></p>
          </div>
          <div class="monitor-overview">
            <div>
              <p class="eyebrow">Signal Scores</p>
              <h2>Watchlist overview</h2>
            </div>
            <canvas id="monitor-chart" width="980" height="320"></canvas>
          </div>
          <div id="monitor-errors" class="monitor-errors"></div>
          <div id="monitor-cards" class="monitor-cards"></div>
        </div>
      </section>
    </main>
    ${createFooter()}
  `
}

window.addEventListener('resize', () => drawOverview(latestItems))

if (!app) {
  throw new Error('Missing #app mount node')
}

renderShell()
form = document.querySelector('#monitor-form')
statusEl = document.querySelector('#monitor-status')
generatedAtEl = document.querySelector('#monitor-generated-at')
cardsEl = document.querySelector('#monitor-cards')
errorsEl = document.querySelector('#monitor-errors')
canvas = document.querySelector('#monitor-chart')
ctx = canvas?.getContext('2d')

form.addEventListener('submit', refreshMonitor)
loadLocalStatus()
