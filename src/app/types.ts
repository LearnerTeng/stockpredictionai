export interface RecommendationComponents {
  trend: number
  fundamental: number
  model: number
  market: number
  risk: number
}

export interface Recommendation {
  symbol: string
  name: string
  score: number
  stance: string
  horizon: string
  latest_price: number
  projected_return_pct: number
  components: RecommendationComponents
  thesis: string
  risks: string[]
  source: string
  generated_at: string
}

export interface Position {
  symbol: string
  name: string
  quantity: number
  average_cost: number
  last_price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  weight_pct: number
}

export interface Portfolio {
  id: string
  name: string
  mode: 'paper' | 'live'
  cash: number
  market_value: number
  equity: number
  cost_basis: number
  unrealized_pnl: number
  benchmark_symbol: string
  positions: Position[]
  updated_at: string
  data_mode: string
}

export interface PerformancePoint {
  date: string
  portfolio_value: number
  portfolio_return_pct: number
  benchmark_return_pct: number
}

export interface DashboardData {
  portfolio: Portfolio
  recommendations: Recommendation[]
  performance: { portfolio_id: string; points: PerformancePoint[]; data_mode: string }
  summary: {
    top_pick: Recommendation | null
    portfolio_return_pct: number
    benchmark_return_pct: number
    alpha_pct: number
    risk_posture: string
  }
  generated_at: string
  data_mode: string
}

export interface RiskCheck {
  code: string
  passed: boolean
  message: string
}

export interface PaperOrder {
  id: string
  client_order_id: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  order_type: 'market' | 'limit'
  limit_price: number | null
  estimated_price: number
  estimated_notional: number
  status: string
  risk_result: { approved: boolean; checks: RiskCheck[]; policy_version: string }
  filled_price: number | null
  created_at: string
  confirmed_at: string | null
  mode: 'paper'
}

export interface PriceBar {
  symbol: string
  trade_date: string
  open: number | null
  high: number | null
  low: number | null
  close: number
  volume: number | null
}

export interface PredictionResult {
  symbol: string
  history_window: number
  forecast_steps: number
  predictions: number[]
  actuals: number[]
  historical_tail: number[]
  metrics: { mae: number; rmse: number }
}

export interface AnalysisResult {
  analysis_mode: 'summary' | 'full'
  language: UiLanguage
  title: string
  summary: string
  sections: Array<{ heading: string; bullets: string[] }>
  disclaimer: string
  generated_at: string
}

export type UiLanguage = 'zh-CN' | 'en' | 'ja'

export interface SimulationPoint {
  trade_date: string
  close: number
  value: number
  pnl: number
  pnl_pct: number
  projected: boolean
}

export interface PositionScenario {
  id: 'manual' | 'ai_timing'
  label: string
  quantity: number
  entry_date: string
  entry_price: number
  cost_basis: number
  latest_value: number
  pnl: number
  pnl_pct: number
  max_drawdown_pct: number
  points: SimulationPoint[]
  assessment: string[]
}

export interface PositionSimulation {
  symbol: string
  latest_bar: PriceBar & { projected?: boolean }
  forecast_bars: Array<PriceBar & { projected: boolean }>
  ai_entry: {
    symbol: string
    trade_date: string
    price: number
    score: number
    stance: string
    reason: string
  }
  scenarios: PositionScenario[]
  engine: {
    forecast_model: string
    signal_model: string
    forecast_steps: number
  }
  disclaimer: string
}

export type MarketCode = 'US' | 'JP' | 'HK'
export type MonitorStatus = 'holding' | 'wanted' | 'ai_suggested' | 'monitoring'
export type MonitorView = 'all' | 'wanted' | 'holding' | 'ai'

export interface MonitorStock {
  symbol: string
  name: string
  market: MarketCode
  exchange: string | null
  sector: string | null
  statuses: MonitorStatus[]
  wanted: boolean
  latest_price: number | null
  day_change_pct: number | null
  ai_score: number | null
  projected_return_pct: number | null
  market_value: number | null
  holding_pnl_pct: number | null
  latest_trade_date: string | null
  last_refreshed_at: string | null
  updated_at: string | null
  holding: Position | null
  recommendation: Recommendation | null
}

export interface MonitorFacets {
  markets: Record<string, number>
  statuses: Record<MonitorView, number>
  sectors: Record<string, number>
  exchanges: Record<string, number>
}

export interface MonitorStocksResponse {
  items: MonitorStock[]
  total: number
  page: number
  page_size: number
  pages: number
  facets: MonitorFacets
  generated_at: string
  data_mode: string
}

export interface MonitorSettings {
  auto_refresh_enabled: boolean
  interval_minutes: number
  updated_at: string | null
}

export interface MonitorRefreshResult {
  generated_at: string
  refreshed: Array<{ symbol: string; bars: number; score: number | null }>
  errors: Array<{ symbol: string; error: string }>
  items: MonitorStock[]
}
