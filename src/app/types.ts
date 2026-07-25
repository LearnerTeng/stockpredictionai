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
  title: string
  summary: string
  sections: Array<{ heading: string; bullets: string[] }>
  disclaimer: string
  generated_at: string
}
