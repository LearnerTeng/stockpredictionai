export function createFooter(options = {}) {
  const {
    modelsHref = '/#models',
    featuresHref = '/#features',
    imageLabHref = '/image-lab.html',
    resultsHref = '/#results',
    contactHref = '/#contact',
  } = options

  return `
    <footer class="footer" id="contact">
      <div class="container">
        <div class="footer-content">
          <div class="footer-section">
            <h3>TradingAI Pro</h3>
            <p>Revolutionizing trading with advanced machine learning and artificial intelligence. Join thousands of traders who trust our AI-powered platform.</p>
          </div>
          <div class="footer-section">
            <h3>Models</h3>
            <p><a href="${modelsHref}">Generative Adversarial Networks</a></p>
            <p><a href="${modelsHref}">Variational Autoencoders</a></p>
            <p><a href="${modelsHref}">Convolutional Neural Networks</a></p>
            <p><a href="${modelsHref}">Bayesian Networks</a></p>
          </div>
          <div class="footer-section">
            <h3>Resources</h3>
            <p><a href="${featuresHref}">Documentation</a></p>
            <p><a href="${imageLabHref}">Image Lab</a></p>
            <p><a href="${resultsHref}">Performance Reports</a></p>
            <p><a href="${contactHref}">API Reference</a></p>
            <p><a href="${contactHref}">Support Center</a></p>
          </div>
          <div class="footer-section">
            <h3>Contact</h3>
            <p>Email: info@tradingaipro.com</p>
            <p>Phone: +1 (555) 123-4567</p>
            <p>Address: 123 AI Street, Tech City, TC 12345</p>
          </div>
        </div>
        <div class="footer-bottom">
          <p>&copy; 2025 TradingAI Pro. All rights reserved. Built with cutting-edge machine learning technology.</p>
        </div>
      </div>
    </footer>
  `
}
