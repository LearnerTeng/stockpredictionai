export function createPredictor() {
  return `
    <section class="predictor" id="predictor">
      <div class="container">
        <div class="predictor-shell">
          <div class="predictor-copy animate-on-scroll">
            <p class="eyebrow">Prediction Lab</p>
            <h2>Keep the original product feel, add a real forecasting workspace.</h2>
            <p class="predictor-lead">
              Use the live <code>/predict</code> API to validate symbols, compare short-horizon forecasts,
              and keep room for later modules such as strategy backtests, alert routing, and
              portfolio-level signal aggregation.
            </p>

            <div class="predictor-highlights">
              <article class="highlight-card">
                <span>Live API</span>
                <strong>Flask + XGBoost</strong>
                <p>Predictions are requested from the Python backend instead of mocked in the UI.</p>
              </article>
              <article class="highlight-card">
                <span>Expandable</span>
                <strong>Modular layout</strong>
                <p>Input panel, metrics rail, chart canvas, and insight cards are separated for future growth.</p>
              </article>
              <article class="highlight-card">
                <span>Operational</span>
                <strong>Built for iteration</strong>
                <p>Suitable for adding watchlists, saved runs, model selection, and strategy overlays later.</p>
              </article>
            </div>
          </div>

          <div class="predictor-workbench animate-on-scroll">
            <div class="workbench-header">
              <div>
                <p class="eyebrow">Forecast Console</p>
                <h3>Run a stock forecast</h3>
              </div>
              <div class="api-pill">
                <span class="api-dot"></span>
                <span id="api-base-label">API: loading...</span>
              </div>
            </div>

            <form id="predict-form" class="predict-form">
              <label>
                Stock Symbol
                <input name="symbol" value="AAPL" required maxlength="10" />
              </label>

              <label>
                History Window
                <input name="history_window" type="number" min="10" max="180" value="30" required />
              </label>

              <label>
                Forecast Steps
                <input name="forecast_steps" type="number" min="1" max="30" value="5" required />
              </label>

              <button id="submit-btn" type="submit" class="btn-primary">Run Prediction</button>
            </form>

            <p id="status" class="status-banner">Ready to request a forecast.</p>

            <div id="metrics" class="metrics-grid">
              <article class="metric-card">
                <span>Symbol</span>
                <strong id="metric-symbol">--</strong>
              </article>
              <article class="metric-card">
                <span>MAE</span>
                <strong id="metric-mae">--</strong>
              </article>
              <article class="metric-card">
                <span>RMSE</span>
                <strong id="metric-rmse">--</strong>
              </article>
              <article class="metric-card">
                <span>Horizon</span>
                <strong id="metric-horizon">--</strong>
              </article>
            </div>

            <div class="chart-card">
              <div class="chart-card-header">
                <div>
                  <h4>Historical Tail vs Forecast</h4>
                  <p>Blue shows recent prices. Orange extends the predicted path from the latest known point.</p>
                </div>
              </div>
              <canvas id="result-chart" width="920" height="360"></canvas>
            </div>

            <section class="ai-summary-card" id="ai-summary-card">
              <div class="ai-summary-header">
                <div>
                  <p class="eyebrow">AI Snapshot</p>
                  <h4 id="ai-summary-title">Generate a prediction to unlock AI interpretation.</h4>
                </div>
                <a id="view-insights-link" class="btn-secondary ghost-link is-disabled" href="/insights.html" aria-disabled="true">
                  View Full Insights
                </a>
              </div>
              <p id="ai-summary-status" class="ai-summary-status" data-tone="neutral">
                The summary is generated from the prediction output after a successful forecast.
              </p>
              <p id="ai-summary-text" class="ai-summary-text">
                This area will show an AI-generated explanation of the latest prediction, using only the current model output and historical tail returned by the backend.
              </p>
              <div id="ai-summary-sections" class="analysis-sections"></div>
            </section>

            <div class="insight-grid">
              <article class="insight-card">
                <span>Latest prediction run</span>
                <p id="prediction-summary">No prediction has been requested yet.</p>
              </article>
              <article class="insight-card">
                <span>Forecast values</span>
                <p id="prediction-values">Values will appear here after a successful API response.</p>
              </article>
            </div>
          </div>
        </div>
      </div>
    </section>
  `
}
