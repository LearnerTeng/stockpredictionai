import './style.css'
import { createFooter } from './components/footer'
import { createHeader } from './components/header'
import { renderAnalysisSections } from './lib/analysis-render'
import { API_BASE, postJson } from './lib/api'
import { loadLatestPrediction } from './lib/prediction-store'

const app = document.querySelector('#app')
const prediction = loadLatestPrediction()

function renderShell() {
  app.innerHTML = `
    ${createHeader({
      activePage: 'insights',
      ctaHref: '/#predictor',
      ctaLabel: 'Back to Lab',
    })}
    <main class="insights-page">
      <section class="insights-hero">
        <div class="container">
          <div class="page-shell">
            <p class="eyebrow">AI Insights</p>
            <h1>Detailed interpretation for the latest forecast run.</h1>
            <p class="page-lead">
              This page expands the prediction into a structured AI readout. It uses the existing
              forecast response only and does not fetch extra market context.
            </p>
          </div>
        </div>
      </section>

      <section class="insights-body">
        <div class="container">
          <div class="insights-layout">
            <aside class="insights-sidebar">
              <article class="meta-card">
                <span>Prediction Context</span>
                <strong id="meta-symbol">--</strong>
                <p id="meta-window">History window: --</p>
                <p id="meta-horizon">Forecast steps: --</p>
                <p id="meta-metrics">Metrics: --</p>
              </article>
              <article class="meta-card">
                <span>API Endpoint</span>
                <strong>POST /ai/analyze</strong>
                <p id="meta-api">Backend: ${API_BASE}</p>
              </article>
            </aside>

            <section class="insights-main">
              <article id="analysis-empty" class="analysis-empty hidden">
                <h2>No prediction is available</h2>
                <p>Run a forecast from the lab page first. The latest prediction is passed here through session storage.</p>
                <a href="/#predictor" class="btn-primary">Return to Prediction Lab</a>
              </article>

              <article id="analysis-card" class="analysis-detail-card hidden">
                <div class="analysis-detail-header">
                  <div>
                    <p class="eyebrow">Full Analysis</p>
                    <h2 id="analysis-title">Preparing analysis...</h2>
                  </div>
                  <a href="/#predictor" class="btn-secondary ghost-link">Run another forecast</a>
                </div>
                <p id="analysis-status" class="status-banner" data-tone="loading">Requesting full AI analysis...</p>
                <p id="analysis-summary" class="analysis-summary-copy"></p>
                <div id="analysis-sections" class="analysis-sections detail-mode"></div>
                <div class="analysis-detail-footer">
                  <p id="analysis-disclaimer" class="analysis-disclaimer"></p>
                  <p id="analysis-generated-at" class="analysis-generated-at"></p>
                </div>
              </article>
            </section>
          </div>
        </div>
      </section>
    </main>
    ${createFooter()}
  `
}

function fillMeta() {
  document.querySelector('#meta-symbol').textContent = prediction.symbol
  document.querySelector('#meta-window').textContent = `History window: ${prediction.history_window}`
  document.querySelector('#meta-horizon').textContent = `Forecast steps: ${prediction.forecast_steps}`
  document.querySelector('#meta-metrics').textContent = `Metrics: MAE ${prediction.metrics.mae}, RMSE ${prediction.metrics.rmse}`
}

async function loadFullAnalysis() {
  const emptyState = document.querySelector('#analysis-empty')
  const analysisCard = document.querySelector('#analysis-card')

  if (!prediction) {
    emptyState.classList.remove('hidden')
    return
  }

  analysisCard.classList.remove('hidden')
  fillMeta()

  const titleEl = document.querySelector('#analysis-title')
  const statusEl = document.querySelector('#analysis-status')
  const summaryEl = document.querySelector('#analysis-summary')
  const sectionsEl = document.querySelector('#analysis-sections')
  const disclaimerEl = document.querySelector('#analysis-disclaimer')
  const generatedAtEl = document.querySelector('#analysis-generated-at')

  try {
    const analysis = await postJson('/ai/analyze', {
      analysis_mode: 'full',
      prediction,
    })

    titleEl.textContent = analysis.title
    statusEl.textContent = 'Full AI analysis is ready.'
    statusEl.dataset.tone = 'success'
    summaryEl.textContent = analysis.summary
    disclaimerEl.textContent = analysis.disclaimer
    generatedAtEl.textContent = `Generated at ${new Date(analysis.generated_at).toLocaleString()}`
    renderAnalysisSections(sectionsEl, analysis.sections)
  } catch (error) {
    titleEl.textContent = 'Unable to generate full analysis'
    statusEl.textContent = error.message
    statusEl.dataset.tone = 'error'
    summaryEl.textContent =
      'The latest prediction is still available, but the backend could not produce the detailed AI interpretation right now.'
    disclaimerEl.textContent = 'You can retry by refreshing this page after the backend OpenAI configuration is available.'
    generatedAtEl.textContent = ''
    renderAnalysisSections(sectionsEl, [])
  }
}

renderShell()
loadFullAnalysis()
