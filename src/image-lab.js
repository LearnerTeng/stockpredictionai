import './style.css'
import { createFooter } from './components/footer'
import { createHeader } from './components/header'
import {
  IMAGE_ALGORITHMS,
  analyzeImage,
  createImageJob,
  fetchImageHistory,
  fetchImageJob,
  renderImageResult,
} from './lib/image-api'
import { API_BASE } from './lib/api'

const app = document.querySelector('#app')
const defaultOptionsText = JSON.stringify(
  {
    sensitivity: 0.6,
    overlay: 'insight-card',
    target: 'chart-patterns',
  },
  null,
  2
)

let previewUrl = null
let pollTimer = 0
let currentJob = null
let form
let fileInput
let algorithmSelect
let optionsInput
let generateImageInput
let syncButton
let asyncButton
let renderButton
let historyButton
let previewImage
let previewEmpty
let inputImage
let inputEmpty
let outputImage
let outputEmpty
let imageStatus
let historyStatus
let historyList
let jobIdEl
let jobStatusEl
let jobTypeEl
let jobAlgorithmEl
let analysisSummaryEl
let analysisLabelsEl
let analysisMetricsEl

function renderShell() {
  app.innerHTML = `
    ${createHeader({
      activePage: 'image-lab',
      ctaHref: '/image-lab.html',
      ctaLabel: 'Image Lab',
    })}
    <main class="image-lab-page">
      <section class="image-lab-hero">
        <div class="container">
          <div class="page-shell animate-on-scroll">
            <p class="eyebrow">Image Lab</p>
            <h1>Route image algorithms through Python without coupling the frontend to model internals.</h1>
            <p class="page-lead">
              Upload chart screenshots or other reference images, run a synchronous inspection, queue an
              asynchronous task, and generate rendered result images through the shared backend gateway.
            </p>
            <div class="hero-buttons">
              <a href="/#predictor" class="btn-secondary">Back to Prediction Lab</a>
              <div class="api-pill">
                <span class="api-dot"></span>
                <span>Gateway: ${API_BASE}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="image-lab-body">
        <div class="container">
          <div class="image-lab-layout">
            <aside class="image-form-card animate-on-scroll">
              <div class="analysis-detail-header">
                <div>
                  <p class="eyebrow">Upload Console</p>
                  <h2>Submit an image analysis request</h2>
                </div>
              </div>

              <form id="image-request-form" class="image-form">
                <label class="input-stack">
                  Source Image
                  <input id="image-file" name="file" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" required />
                </label>

                <label class="input-stack">
                  Algorithm
                  <select id="image-algorithm" name="algorithm">
                    ${IMAGE_ALGORITHMS.map(
                      (algorithm) => `<option value="${algorithm.value}">${algorithm.label}</option>`
                    ).join('')}
                  </select>
                </label>

                <label class="input-stack">
                  Options JSON
                  <textarea id="image-options" name="options" class="json-editor" spellcheck="false">${defaultOptionsText}</textarea>
                </label>

                <label class="checkbox-row">
                  <input id="generate-image" type="checkbox" checked />
                  Generate a rendered output image during analysis
                </label>

                <div class="stacked-actions">
                  <button id="sync-submit" type="submit" data-mode="sync" class="btn-primary">Run Sync Analysis</button>
                  <button id="async-submit" type="submit" data-mode="async" class="btn-secondary">Create Async Job</button>
                </div>
              </form>

              <p id="image-status" class="status-banner">Ready to analyze a PNG or JPG image.</p>

              <div class="image-preview-shell">
                <div class="chart-card-header">
                  <div>
                    <h3>Preview</h3>
                    <p class="field-hint">The selected source image stays client-side until you submit the form.</p>
                  </div>
                </div>
                <div class="image-preview-frame">
                  <img id="preview-image" class="hidden" alt="Selected preview" />
                  <p id="preview-empty" class="image-placeholder">Choose an image to preview it here.</p>
                </div>
              </div>
            </aside>

            <section class="image-results-card animate-on-scroll">
              <div class="analysis-detail-header">
                <div>
                  <p class="eyebrow">Result Surface</p>
                  <h2>Inspect the latest job payload</h2>
                </div>
                <button id="render-output" type="button" class="btn-secondary">Generate Result Image</button>
              </div>

              <div class="job-meta-grid">
                <article class="metric-card">
                  <span>Job ID</span>
                  <strong id="job-id">--</strong>
                </article>
                <article class="metric-card">
                  <span>Status</span>
                  <strong id="job-status">idle</strong>
                </article>
                <article class="metric-card">
                  <span>Mode</span>
                  <strong id="job-type">--</strong>
                </article>
                <article class="metric-card">
                  <span>Algorithm</span>
                  <strong id="job-algorithm">--</strong>
                </article>
              </div>

              <div class="image-output-grid">
                <article class="image-surface">
                  <span>Input Asset</span>
                  <div class="image-preview-frame">
                    <img id="input-image" class="hidden" alt="Uploaded input" />
                    <p id="input-empty" class="image-placeholder">The backend-backed source image will appear here after a request succeeds.</p>
                  </div>
                </article>
                <article class="image-surface">
                  <span>Generated Output</span>
                  <div class="image-preview-frame">
                    <img id="output-image" class="hidden" alt="Generated output" />
                    <p id="output-empty" class="image-placeholder">Rendered output images will appear here after generation completes.</p>
                  </div>
                </article>
              </div>

              <article class="analysis-section-card">
                <h3>Summary</h3>
                <p id="analysis-summary" class="analysis-summary-copy">
                  Submit a request to populate the structured analysis payload.
                </p>
              </article>

              <article class="analysis-section-card">
                <h3>Labels</h3>
                <div id="analysis-labels" class="pill-list">
                  <span class="pill muted">No labels yet</span>
                </div>
              </article>

              <article class="analysis-section-card">
                <h3>Metrics</h3>
                <div id="analysis-metrics" class="metric-list">
                  <article class="metric-list-item">
                    <span>Awaiting analysis response</span>
                  </article>
                </div>
              </article>
            </section>
          </div>

          <section class="image-history-card animate-on-scroll">
            <div class="analysis-detail-header">
              <div>
                <p class="eyebrow">History</p>
                <h2>Recent image jobs</h2>
              </div>
              <button id="refresh-history" type="button" class="btn-secondary">Refresh History</button>
            </div>
            <p id="history-status" class="status-banner">Loading recent image jobs from the backend.</p>
            <div id="history-list" class="history-list"></div>
          </section>
        </div>
      </section>
    </main>
    ${createFooter({ imageLabHref: '/image-lab.html' })}
  `
}

function setStatus(element, message, tone = 'neutral') {
  element.textContent = message
  element.dataset.tone = tone
}

function formatDate(value) {
  if (!value) {
    return '--'
  }
  return new Date(value).toLocaleString()
}

function parseOptions() {
  const raw = optionsInput.value.trim()
  if (!raw) {
    return {}
  }

  try {
    const parsed = JSON.parse(raw)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error('Options must be a JSON object')
    }
    return parsed
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : 'Options must be valid JSON')
  }
}

function resolveAssetUrl(relativeUrl) {
  return relativeUrl ? `${API_BASE}${relativeUrl}` : ''
}

function updatePreview(file) {
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl)
  }

  if (!file) {
    previewUrl = null
    previewImage.removeAttribute('src')
    previewImage.classList.add('hidden')
    previewEmpty.classList.remove('hidden')
    return
  }

  previewUrl = URL.createObjectURL(file)
  previewImage.src = previewUrl
  previewImage.classList.remove('hidden')
  previewEmpty.classList.add('hidden')
}

function updateImageSurface(imageEl, emptyEl, relativeUrl) {
  if (!relativeUrl) {
    imageEl.removeAttribute('src')
    imageEl.classList.add('hidden')
    emptyEl.classList.remove('hidden')
    return
  }

  imageEl.src = resolveAssetUrl(relativeUrl)
  imageEl.classList.remove('hidden')
  emptyEl.classList.add('hidden')
}

function renderLabels(labels) {
  if (!labels?.length) {
    analysisLabelsEl.innerHTML = '<span class="pill muted">No labels returned</span>'
    return
  }

  analysisLabelsEl.innerHTML = labels
    .map((label) => `<span class="pill">${label}</span>`)
    .join('')
}

function renderMetrics(metrics) {
  if (!metrics) {
    analysisMetricsEl.innerHTML = '<article class="metric-list-item"><span>No metrics returned</span></article>'
    return
  }

  const items = [
    ['Resolution', `${metrics.width} x ${metrics.height}`],
    ['Aspect Ratio', metrics.aspect_ratio],
    ['Brightness', metrics.brightness],
    ['Contrast Score', metrics.contrast_score],
    ['Average RGB', `${metrics.average_rgb.r} / ${metrics.average_rgb.g} / ${metrics.average_rgb.b}`],
  ]

  analysisMetricsEl.innerHTML = items
    .map(
      ([label, value]) => `
        <article class="metric-list-item">
          <span>${label}</span>
          <strong>${value}</strong>
        </article>
      `
    )
    .join('')
}

function renderJob(job) {
  currentJob = job
  const analysis = job.result?.analysis || null
  jobIdEl.textContent = job.job_id || job.id || '--'
  jobStatusEl.textContent = job.status || '--'
  jobTypeEl.textContent = job.job_type || '--'
  jobAlgorithmEl.textContent = job.algorithm || '--'
  analysisSummaryEl.textContent = analysis?.summary || job.error_message || 'No analysis summary returned yet.'
  renderLabels(analysis?.labels || [])
  renderMetrics(analysis?.metrics || null)
  updateImageSurface(inputImage, inputEmpty, job.input_url || job.result?.input_url || null)
  updateImageSurface(outputImage, outputEmpty, job.output_url || job.result?.output_url || null)
  renderButton.disabled = job.status !== 'succeeded'

  if (job.status === 'succeeded') {
    setStatus(imageStatus, `Job ${job.job_id || job.id} completed at ${formatDate(job.finished_at)}.`, 'success')
  } else if (job.status === 'failed') {
    setStatus(imageStatus, job.error_message || 'Image job failed.', 'error')
  } else {
    setStatus(imageStatus, `Job ${job.job_id || job.id} is ${job.status}. Polling for updates...`, 'loading')
  }
}

function renderHistory(items) {
  if (!items.length) {
    historyList.innerHTML = '<article class="history-item"><p>No image jobs recorded yet.</p></article>'
    return
  }

  historyList.innerHTML = items
    .map(
      (item) => `
        <article class="history-item">
          <div class="history-item-copy">
            <p class="eyebrow">Job ${item.id.slice(0, 8)}</p>
            <h3>${item.algorithm}</h3>
            <p>${item.summary || item.error_message || 'Result pending.'}</p>
          </div>
          <div class="history-item-meta">
            <span>${item.status}</span>
            <span>${item.job_type}</span>
            <span>${formatDate(item.created_at)}</span>
          </div>
          <div class="stacked-actions compact">
            <button type="button" class="btn-secondary" data-job-id="${item.id}">Load Job</button>
            ${
              item.output_url
                ? `<a class="btn-secondary" href="${resolveAssetUrl(item.output_url)}" target="_blank" rel="noreferrer">Open Output</a>`
                : ''
            }
          </div>
        </article>
      `
    )
    .join('')
}

function stopPolling() {
  if (pollTimer) {
    window.clearTimeout(pollTimer)
    pollTimer = 0
  }
}

async function refreshHistory() {
  setStatus(historyStatus, 'Refreshing image job history...', 'loading')
  try {
    const history = await fetchImageHistory(1, 8)
    renderHistory(history.items || [])
    setStatus(historyStatus, `Loaded ${history.items?.length || 0} recent image jobs.`, 'success')
  } catch (error) {
    setStatus(historyStatus, error.message, 'error')
  }
}

function schedulePoll(jobId) {
  stopPolling()

  const poll = async () => {
    try {
      const job = await fetchImageJob(jobId)
      renderJob(job)
      if (job.status === 'queued' || job.status === 'running') {
        pollTimer = window.setTimeout(poll, 2000)
        return
      }

      await refreshHistory()
    } catch (error) {
      setStatus(imageStatus, `Polling failed: ${error.message}`, 'error')
    }
  }

  pollTimer = window.setTimeout(poll, 2000)
}

async function handleSubmit(event) {
  event.preventDefault()

  const file = fileInput.files?.[0]
  if (!file) {
    setStatus(imageStatus, 'Please select a PNG or JPG image first.', 'error')
    return
  }

  let options
  try {
    options = parseOptions()
  } catch (error) {
    setStatus(imageStatus, error.message, 'error')
    return
  }

  const submitter = event.submitter
  const mode = submitter?.dataset.mode || 'sync'
  const payload = {
    file,
    algorithm: algorithmSelect.value,
    options,
    generateImage: generateImageInput.checked,
  }

  syncButton.disabled = true
  asyncButton.disabled = true
  renderButton.disabled = true
  stopPolling()
  setStatus(
    imageStatus,
    mode === 'sync' ? 'Running sync image analysis...' : 'Creating async image job...',
    'loading'
  )

  try {
    const job = mode === 'sync' ? await analyzeImage(payload) : await createImageJob(payload)
    renderJob(job)
    await refreshHistory()

    if (mode === 'async' && (job.status === 'queued' || job.status === 'running')) {
      schedulePoll(job.job_id)
    }
  } catch (error) {
    setStatus(imageStatus, error.message, 'error')
  } finally {
    syncButton.disabled = false
    asyncButton.disabled = false
    renderButton.disabled = currentJob?.status !== 'succeeded'
  }
}

async function handleHistoryClick(event) {
  const button = event.target.closest('[data-job-id]')
  if (!button) {
    return
  }

  const { jobId } = button.dataset
  setStatus(imageStatus, `Loading job ${jobId}...`, 'loading')

  try {
    const job = await fetchImageJob(jobId)
    renderJob(job)
    if (job.status === 'queued' || job.status === 'running') {
      schedulePoll(jobId)
    }
  } catch (error) {
    setStatus(imageStatus, error.message, 'error')
  }
}

async function handleRenderOutput() {
  if (!currentJob?.job_id) {
    setStatus(imageStatus, 'Run or load a completed job before generating a result image.', 'error')
    return
  }

  renderButton.disabled = true
  setStatus(imageStatus, `Generating output image for job ${currentJob.job_id}...`, 'loading')

  try {
    await renderImageResult({ job_id: currentJob.job_id })
    const refreshed = await fetchImageJob(currentJob.job_id)
    renderJob(refreshed)
    await refreshHistory()
  } catch (error) {
    setStatus(imageStatus, error.message, 'error')
  } finally {
    renderButton.disabled = currentJob?.status !== 'succeeded'
  }
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
    { threshold: 0.14 }
  )

  animatedNodes.forEach((node) => observer.observe(node))
}

try {
  if (!app) {
    throw new Error('Missing #app mount node')
  }

  renderShell()

  form = document.querySelector('#image-request-form')
  fileInput = document.querySelector('#image-file')
  algorithmSelect = document.querySelector('#image-algorithm')
  optionsInput = document.querySelector('#image-options')
  generateImageInput = document.querySelector('#generate-image')
  syncButton = document.querySelector('#sync-submit')
  asyncButton = document.querySelector('#async-submit')
  renderButton = document.querySelector('#render-output')
  historyButton = document.querySelector('#refresh-history')
  previewImage = document.querySelector('#preview-image')
  previewEmpty = document.querySelector('#preview-empty')
  inputImage = document.querySelector('#input-image')
  inputEmpty = document.querySelector('#input-empty')
  outputImage = document.querySelector('#output-image')
  outputEmpty = document.querySelector('#output-empty')
  imageStatus = document.querySelector('#image-status')
  historyStatus = document.querySelector('#history-status')
  historyList = document.querySelector('#history-list')
  jobIdEl = document.querySelector('#job-id')
  jobStatusEl = document.querySelector('#job-status')
  jobTypeEl = document.querySelector('#job-type')
  jobAlgorithmEl = document.querySelector('#job-algorithm')
  analysisSummaryEl = document.querySelector('#analysis-summary')
  analysisLabelsEl = document.querySelector('#analysis-labels')
  analysisMetricsEl = document.querySelector('#analysis-metrics')

  if (
    !form ||
    !fileInput ||
    !algorithmSelect ||
    !optionsInput ||
    !generateImageInput ||
    !syncButton ||
    !asyncButton ||
    !renderButton ||
    !historyButton ||
    !previewImage ||
    !previewEmpty ||
    !inputImage ||
    !inputEmpty ||
    !outputImage ||
    !outputEmpty ||
    !imageStatus ||
    !historyStatus ||
    !historyList ||
    !jobIdEl ||
    !jobStatusEl ||
    !jobTypeEl ||
    !jobAlgorithmEl ||
    !analysisSummaryEl ||
    !analysisLabelsEl ||
    !analysisMetricsEl
  ) {
    throw new Error('One or more required image lab UI nodes failed to mount')
  }

  renderButton.disabled = true
  fileInput.addEventListener('change', () => updatePreview(fileInput.files?.[0] || null))
  form.addEventListener('submit', handleSubmit)
  historyButton.addEventListener('click', refreshHistory)
  historyList.addEventListener('click', handleHistoryClick)
  renderButton.addEventListener('click', handleRenderOutput)
  window.addEventListener('beforeunload', stopPolling)
  setupScrollAnimations()
  refreshHistory()
} catch (error) {
  console.error(error)
  document.body.innerHTML = `
    <main style="padding:40px;font-family:Inter,system-ui,sans-serif;background:#07111f;color:#e2e8f0;min-height:100vh;">
      <section style="max-width:960px;margin:0 auto;border:1px solid rgba(251,113,133,.25);background:rgba(15,23,42,.88);border-radius:24px;padding:24px;">
        <h1 style="margin:0 0 12px;font-size:28px;">Image Lab Runtime Error</h1>
        <pre style="margin:0;white-space:pre-wrap;word-break:break-word;color:#fecdd3;">${
          error instanceof Error ? `${error.message}\n\n${error.stack || ''}` : String(error)
        }</pre>
      </section>
    </main>
  `
}
