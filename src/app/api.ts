import type {
  AnalysisResult,
  DashboardData,
  MarketCode,
  MonitorRefreshResult,
  MonitorSettings,
  MonitorStock,
  MonitorStocksResponse,
  PaperOrder,
  Portfolio,
  PositionSimulation,
  PredictionResult,
  PriceBar,
  Recommendation,
  UiLanguage,
} from './types'
import i18n from './i18n'

const defaultBase = `${window.location.protocol}//${window.location.hostname || 'localhost'}:8000`
export const API_BASE = import.meta.env.VITE_API_BASE_URL || defaultBase

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new Error(i18n.t('invalidResponse', { path }))
  }
  if (!response.ok) {
    const message = typeof payload === 'object' && payload && 'error' in payload
      ? String((payload as { error: unknown }).error)
      : i18n.t('requestFailed', { status: response.status })
    throw new Error(message)
  }
  return payload as T
}

function queryString(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value))
  })
  const serialized = params.toString()
  return serialized ? `?${serialized}` : ''
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
  analyze: (prediction: PredictionResult, language: UiLanguage) => request<AnalysisResult>('/ai/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ analysis_mode: 'full', language, prediction }),
  }),
  simulatePosition: (payload: {
    symbol: string
    quantity: number
    entry_price?: number
    entry_date?: string
    forecast_steps?: number
  }) => request<PositionSimulation>('/simulation/position', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  monitorStocks: (filters: Record<string, string | number | undefined>) =>
    request<MonitorStocksResponse>(`/monitor/stocks${queryString(filters)}`),
  monitorStock: (symbol: string) => request<MonitorStock>(`/monitor/stocks/${encodeURIComponent(symbol)}`),
  addMonitorStock: (payload: {
    symbol: string
    market: MarketCode
    name?: string
    exchange?: string
    sector?: string
  }) => request<{ item: MonitorStock; warnings: string[] }>('/monitor/stocks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  updateMonitorStock: (symbol: string, payload: {
    name?: string
    market?: MarketCode
    exchange?: string
    sector?: string
  }) => request<MonitorStock>(`/monitor/stocks/${encodeURIComponent(symbol)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  setMonitorWanted: (symbol: string, wanted: boolean) =>
    request<MonitorStock>(`/monitor/stocks/${encodeURIComponent(symbol)}/preference`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wanted }),
    }),
  monitorSettings: () => request<MonitorSettings>('/monitor/settings'),
  updateMonitorSettings: (payload: Pick<MonitorSettings, 'auto_refresh_enabled' | 'interval_minutes'>) =>
    request<MonitorSettings>('/monitor/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  refreshMonitor: (filters: Record<string, string | number | undefined>) =>
    request<MonitorRefreshResult>('/monitor/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filters, range: '1y' }),
    }),
  analyzeImage: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    body.append('algorithm', 'baseline')
    body.append('options', '{}')
    return request<Record<string, unknown>>('/image/analyze', { method: 'POST', body })
  },
}
