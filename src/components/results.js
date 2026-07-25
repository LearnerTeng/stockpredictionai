export function createResults() {
  return `
    <section class="results portfolio-section" id="portfolio">
      <div class="container">
        <div class="section-header animate-on-scroll">
          <h2>Portfolio Command Deck</h2>
          <p>
            Combine model conviction, active positions, market context, and personal performance
            in one surface. This section is structured to swap mock data for backend portfolio data later.
          </p>
        </div>

        <div class="portfolio-kpi-grid animate-on-scroll">
          <article class="result-card kpi-card">
            <span>Top Recommendation</span>
            <strong id="top-pick-symbol">NVDA</strong>
            <p id="top-pick-score">92 / 100 conviction</p>
          </article>
          <article class="result-card kpi-card">
            <span>Portfolio Value</span>
            <strong id="portfolio-value">$184,560</strong>
            <p id="portfolio-daily-change">+2.38% today</p>
          </article>
          <article class="result-card kpi-card">
            <span>Total Return</span>
            <strong id="portfolio-return">+18.42%</strong>
            <p id="portfolio-return-copy">Trailing 6 months vs base capital</p>
          </article>
          <article class="result-card kpi-card">
            <span>Risk Posture</span>
            <strong id="risk-posture">Balanced Growth</strong>
            <p id="risk-copy">42% tech, 23% ETFs, 18% cash buffer</p>
          </article>
        </div>

        <div class="portfolio-shell">
          <article class="portfolio-panel portfolio-recommendations animate-on-scroll">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Recommended Stocks</p>
                <h3>Watchlist ranked by recommendation score</h3>
              </div>
              <span class="panel-chip">Live-ready scaffold</span>
            </div>
            <div id="recommendation-list" class="recommendation-list"></div>
          </article>

          <article class="portfolio-panel portfolio-holdings animate-on-scroll">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Current Holdings</p>
                <h3>Open positions and current profit profile</h3>
              </div>
              <span class="panel-chip">My book</span>
            </div>
            <div id="holdings-list" class="holdings-list"></div>
          </article>
        </div>

        <div class="portfolio-chart-grid">
          <article class="portfolio-panel animate-on-scroll">
            <div class="panel-header">
              <div>
                <p class="eyebrow">Market Curve</p>
                <h3>Broad market context</h3>
              </div>
              <span class="panel-chip">S&P 500 benchmark</span>
            </div>
            <p class="panel-copy" id="market-curve-copy">
              Benchmark trend across the last eight sessions, used as a macro context layer for stock recommendations.
            </p>
            <canvas id="market-curve-chart" width="920" height="320"></canvas>
          </article>

          <article class="portfolio-panel animate-on-scroll">
            <div class="panel-header">
              <div>
                <p class="eyebrow">My Return Curve</p>
                <h3>Portfolio performance</h3>
              </div>
              <span class="panel-chip">Account equity</span>
            </div>
            <p class="panel-copy" id="profit-curve-copy">
              Cumulative account return path. This is currently demo data and can later bind to imported holdings and fills.
            </p>
            <canvas id="profit-curve-chart" width="920" height="320"></canvas>
          </article>
        </div>
      </div>
    </section>
  `
}
