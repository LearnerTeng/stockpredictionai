import { API_BASE } from './api'

/**
 * @typedef {Object} ImageAnalysisResult
 * @property {string} summary
 * @property {string[]} labels
 * @property {{ width: number, height: number, aspect_ratio: number, average_rgb: { r: number, g: number, b: number }, brightness: number, contrast_score: number }} metrics
 * @property {Record<string, unknown>} options_applied
 */

/**
 * @typedef {Object} ImageJobSummary
 * @property {string} id
 * @property {string} job_type
 * @property {string} status
 * @property {string} algorithm
 * @property {string} input_url
 * @property {string | null} output_url
 * @property {string | null} summary
 * @property {string | null} error_message
 * @property {string} created_at
 * @property {string} updated_at
 * @property {string | null} finished_at
 */

/**
 * @typedef {ImageJobSummary & { job_id: string, result: { analysis: ImageAnalysisResult, input_url: string, output_url: string | null } | null }} ImageJobDetail
 */

/**
 * @typedef {Object} ImageRenderResult
 * @property {string} input_url
 * @property {string} output_url
 * @property {string} output_path
 */

export const IMAGE_ALGORITHMS = [
  { value: 'baseline-inspector', label: 'Baseline Inspector' },
  { value: 'chart-vision-lite', label: 'Chart Vision Lite' },
  { value: 'edge-focus', label: 'Edge Focus' },
]

async function parseJson(response, path) {
  try {
    return await response.json()
  } catch {
    throw new Error(`Invalid JSON response from ${path}`)
  }
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  const data = await parseJson(response, path)
  if (!response.ok) {
    throw new Error(data.error || data.detail || `${path} request failed`)
  }
  return data
}

function buildImageFormPayload({ file, algorithm, options, generateImage }) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('algorithm', algorithm)
  formData.append('options', JSON.stringify(options))
  formData.append('generate_image', String(generateImage))
  return formData
}

export function analyzeImage(payload) {
  return requestJson('/image/analyze', {
    method: 'POST',
    body: buildImageFormPayload(payload),
  })
}

export function createImageJob(payload) {
  return requestJson('/image/jobs', {
    method: 'POST',
    body: buildImageFormPayload(payload),
  })
}

export function fetchImageJob(jobId) {
  return requestJson(`/image/jobs/${jobId}`)
}

export function fetchImageHistory(page = 1, pageSize = 8) {
  return requestJson(`/image/history?page=${page}&page_size=${pageSize}`)
}

export function renderImageResult(payload) {
  return requestJson('/image/render', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
