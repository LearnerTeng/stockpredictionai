export function createHeader(options = {}) {
  const {
    homeHref = '/',
    featuresHref = '/#features',
    modelsHref = '/#models',
    labHref = '/#predictor',
    imageLabHref = '/image-lab.html',
    insightsHref = '/insights.html',
    contactHref = '/#contact',
    ctaHref = '/#predictor',
    ctaLabel = 'Launch Lab',
    activePage = 'lab',
  } = options

  const insightsClass = activePage === 'insights' ? 'is-active' : ''
  const labClass = activePage === 'lab' ? 'is-active' : ''
  const imageLabClass = activePage === 'image-lab' ? 'is-active' : ''

  return `
    <header class="header">
      <div class="container">
        <div class="header-content">
          <a href="${homeHref}" class="logo">
            <i class="fas fa-chart-line"></i>
            TradingAI Pro
          </a>
          <nav>
            <ul class="nav">
              <li><a href="${featuresHref}">Features</a></li>
              <li><a href="${modelsHref}">Models</a></li>
              <li><a href="${labHref}" class="${labClass}">Lab</a></li>
              <li><a href="${imageLabHref}" class="${imageLabClass}">Image Lab</a></li>
              <li><a href="${insightsHref}" class="${insightsClass}">Insights</a></li>
              <li><a href="${contactHref}">Contact</a></li>
            </ul>
          </nav>
          <a href="${ctaHref}" class="cta-button">${ctaLabel}</a>
        </div>
      </div>
    </header>
  `
}
