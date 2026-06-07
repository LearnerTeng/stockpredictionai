const PREDICTION_STORAGE_KEY = 'trading-ai-pro:last-prediction'

export function saveLatestPrediction(prediction) {
  sessionStorage.setItem(PREDICTION_STORAGE_KEY, JSON.stringify(prediction))
}

export function loadLatestPrediction() {
  const raw = sessionStorage.getItem(PREDICTION_STORAGE_KEY)
  if (!raw) {
    return null
  }

  try {
    return JSON.parse(raw)
  } catch {
    sessionStorage.removeItem(PREDICTION_STORAGE_KEY)
    return null
  }
}
