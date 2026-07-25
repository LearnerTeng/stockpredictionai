import type {
  AnalysisResult,
  DashboardData,
  PaperOrder,
  Portfolio,
  PredictionResult,
  PriceBar,
  Recommendation,
} from './types'

const defaultBase = `${window.location.protocol}//${window.location.hostname || 'localhost'}:8000`
export const API_BASE = import.meta.env.VITE_API_BASE_URL || defaultBase

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new Error(`接口 ${path} 返回了无效数据`)
  }
  if (!response.ok) {
    const message = typeof payload === 'object' && payload && 'error' in payload
      ? String((payload as { error: unknown }).error)
      : `接口请求失败 (${response.status})`
    throw new Error(message)
  }
  return payload as T
}

export const api = {
  dashboard: () => request<DashboardData>('/dashboard'),
  recommendations: () => request<{ items: Recommendation[]; data_mode: string }>('/recommendations'),
  recommendation: (symbol: string) => request<Recommendation>(`/recommendations/${encodeURIComponent(symbol)}`),
  portfolio: () => request<Portfolio>('/portfolio'),
  performance: () => request<{ points: DashboardData['performance']['points'] }>('/portfolio/performance'),
  bars: (symbol: string) => request<{ items: PriceBar[] }>(`/data/prices/${encodeURIComponent(symbol)}?limit=180`),
  orders: () => request<{ items: PaperOrder[]; mode: 'paper' }>('/trading/orders'),
  createOrder: (payload: Record<string, unknown>) => request<PaperOrder>('/trading/orders', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify(payload),
  }),
  confirmOrder: (id: string) => request<PaperOrder>(`/trading/orders/${id}/confirm`, { method: 'POST' }),
  refreshRecommendations: (symbols: string[]) => request<{ items: unknown[]; errors: unknown[] }>('/monitor/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbols, range: '1y' }),
  }),
  predict: (symbol: string) => request<PredictionResult>('/predict', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, history_window: 60, forecast_steps: 5 }),
  }),
  analyze: (prediction: PredictionResult) => request<AnalysisResult>('/ai/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ analysis_mode: 'full', prediction }),
  }),
  analyzeImage: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    body.append('algorithm', 'baseline')
    body.append('options', '{}')
    return request<Record<string, unknown>>('/image/analyze', { method: 'POST', body })
  },
}
