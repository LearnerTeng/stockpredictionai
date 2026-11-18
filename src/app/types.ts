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
  currency: 'USD' | 'JPY' | 'HKD'
  account_bucket: string | null
  quantity: number
  average_cost: number
  last_price: number
  price_scale: number
  source: string | null
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  weight_pct: number
}

export interface Portfolio {
  id: string
  name: string
  mode: 'paper' | 'live' | 'read_only'
  currency: 'USD' | 'JPY' | 'HKD'
  account_type: 'paper' | 'live' | 'external' | 'nisa'
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

export interface PortfolioListItem {
  id: string
  name: string
  mode: Portfolio['mode']
  currency: Portfolio['currency']
  account_type: Portfolio['account_type']
  updated_at: string
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
  model?: string
  forecast_mode?: 'historical-holdout'
  future_forecast?: { predictions: number[]; delta_pct: number; as_of: string; reference_price: number; price_field: string }
  quant_forecast?: {
    status: 'ok' | 'fallback'
    model_id: string
    fallback_used: boolean
    fallback_reason: string | null
    trained_until: string | null
    dataset_version: string
    benchmark_error?: string
    data_stale?: boolean
    data_cutoff?: string
    model_run_id?: string
    objective: {
      horizons: number[]
      benchmark: string
      price_field: string
      target: string
      calendar: string
    }
    forecasts: Array<{
      horizon_days: number
      excess_return_pct: number
      direction: 'up' | 'down' | 'flat'
      training_samples: number
      training_mae_pct: number | null
    }>
  }
  sentiment_context?: SentimentSnapshot | null
  sentiment_shadow?: SentimentShadow
}

export interface SentimentSnapshot {
  symbol: string
  score_1d: number | null
  score_3d: number | null
  score_7d: number | null
  negative_share: number | null
  dispersion: number | null
  news_count: number
  source_count: number
  score_change_7d: number | null
  negative_shock: boolean
  calculated_at: string
  version: string
}

export interface SentimentShadow {
  status: 'shadow' | 'insufficient_data' | 'unavailable'
  model_id?: string
  production_eligible: false
  method?: string
  error?: string
  features?: SentimentSnapshot
  forecasts?: Array<{
    horizon_days: number
    baseline_excess_return_pct: number
    sentiment_adjustment_pct: number
    shadow_excess_return_pct: number
  }>
}

export interface SentimentArticle {
  id: string
  symbol: string
  name: string | null
  market: 'US' | 'JP'
  title: string
  summary: string | null
  url: string | null
  source: string
  source_domain: string | null
  source_tier: 'primary' | 'secondary'
  language: string | null
  published_at: string
  sentiment_label: 'positive' | 'neutral' | 'negative' | null
  sentiment_score: number | null
  relevance_score: number
  event_type: string | null
  impact_direction: 'up' | 'down' | 'neutral' | null
  analysis_status: 'pending' | 'analyzed'
  explanation: string | null
}

export interface NewsCoverage {
  provider: string
  symbol: string
  coverage_start: string | null
  coverage_end: string | null
  article_count: number
  status: string
  gaps: Array<Record<string, unknown>>
  last_error: string | null
  last_fetched_at: string | null
}

export interface SentimentOverview {
  window: '24h' | '3d' | '7d'
  market: 'all' | 'US' | 'JP'
  summary: {
    score: number | null
    positive: number
    neutral: number
    negative: number
    articles: number
    symbols: number
    negative_shocks: number
  }
  symbols: SentimentSnapshot[]
  articles: SentimentArticle[]
  total: number
  page: number
  page_size: number
  pages: number
  coverage: NewsCoverage[]
  trend: Array<{ date: string; score: number }>
  generated_at: string
}

export interface SentimentStockDetail {
  symbol: string
  window: '24h' | '3d' | '7d'
  snapshot: SentimentSnapshot
  articles: SentimentArticle[]
  total: number
  coverage: NewsCoverage[]
  generated_at: string
}

export interface SentimentSettings {
  enabled: boolean
  interval_minutes: number
  markets: Array<'US' | 'JP'>
  primary_domains: string[]
  email_enabled: boolean
  email_recipients: string[]
  notification_language: UiLanguage
  digest_time: string
  smtp_configured: boolean
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
  sentiment: SentimentSnapshot | null
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

export interface CorrelationMatrix {
  symbols: string[]
  values: number[][]
}

export interface RiskMetric {
  var_95_pct: number | null
  es_95_pct: number | null
  beta: number | null
  tracking_error_pct: number | null
  annualized_vol_pct: number | null
  sharpe: number | null
  max_drawdown_pct: number | null
  hhi: number | null
  effective_n: number | null
}

export interface ResearchEvidence {
  id: string
  title: string
  text: string
  url: string | null
  source: string
  revision: number
  available_at: string
}

export interface ResearchAnswer {
  id: string
  status: 'answered' | 'insufficient-evidence' | 'evidence-only'
  claims: Array<{ text: string; evidence_id: string; quote: string }>
  evidence: { items: ResearchEvidence[]; as_of: string; mode: string; query_tokens: number }
  model: string | null
}

export interface RiskContribution {
  symbol: string
  weight_pct: number
  contribution_pct: number | null
}

export interface SuggestedWeight {
  symbol: string
  weight_pct: number
}

export interface PortfolioRisk {
  status: 'ok' | 'no-positions' | 'insufficient-history'
  generated_at: string
  window_days: number | null
  symbols: string[]
  weights: Record<string, number>
  correlation_matrix: CorrelationMatrix | null
  portfolio: RiskMetric | null
  suggested_weights: SuggestedWeight[]
  contributions: RiskContribution[]
  warnings: string[]
}

export interface MonitorRefreshResult {
  generated_at: string
  refreshed: Array<{ symbol: string; bars: number; score: number | null }>
  errors: Array<{ symbol: string; error: string }>
  items: MonitorStock[]
}

export interface IngestionJob {
  id: string
  status: 'planned' | 'queued' | 'running' | 'retrying' | 'completed' | 'partial' | 'failed'
  requested_symbols: string[]
  imported_symbols: string[]
  records_inserted: number
  attempts: number
  max_attempts: number
  errors: Array<{ symbol: string; error: string; attempts?: number }>
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
}
export type NewsLine = 'deepseek' | 'ultra' | 'experiment' | 'holdings'
export interface NewsComparison {
  id: string; recipe: string; selected: NewsLine[]; initial_capital: number
  model_pins?: Record<string, {model: string; provider: string; version: string}>
  period?: [string, string]; snapshot_as_of?: string
  results: Partial<Record<NewsLine, { status: string; reason?: string; replay?: {
    equity_curve: { date: string; equity: number }[]; metrics: { return_pct: number; max_drawdown_pct: number; commission: number; slippage: number }
  } }>>
}
export interface NewsLineStatus {
  models: Record<string, { configured: boolean; model: string; jobs: Record<string, number> }>
  enabled: NewsLine[]; comparisons: NewsComparison[]
}

export type SbiStatus = {
  enabled: boolean
  snapshot: { through: string; confirmed_through: string } | null
  files: { id: string; file: string; status: string; rows?: number; error?: string; fingerprint?: string;
    overlaps?: {key: string; symbol: string; date: string; side: string; units: string; settlement_jpy: string; existing: number; exported: number}[] }[]
  valuations: { id: string; symbol: string; day: string; nav: string; available_at: string }[]
  alerts: { id: string; symbol: string; nav_date: string; change_pct: number; delivery: string; error?: string;
    news: {title: string; url?: string; available_at: string}[] }[]
}

export type RuntimeStatus = {
  status: string
  services: Record<string, {status: string; pid?: number; last_success?: string; last_ingestion?: string;
    retry_in_seconds: number; error?: string; ingestion_in_progress?: boolean}>
}

export type SentimentEvaluationInput = {
  start: string
  end: string
  symbols: string[]
  line: 'deepseek' | 'ultra'
  as_of?: string
  model_pins?: Record<string, { provider: string; model: string; version: string }>
}

export type SentimentEvaluation = {
  id: string
  inputs: SentimentEvaluationInput
  benchmarks: Record<'US' | 'JP', string>
  metrics: Record<'US' | 'JP', {horizon: number; samples: number; status: string;
    baseline: {mae_pct: number; direction_accuracy: number} | null;
    sentiment: {mae_pct: number; direction_accuracy: number} | null}[]>
  coverage: Record<string, {market: string; stock_bars: number; benchmark_bars: number; sessions_with_news: number; exchange_sessions: number}>
}

export type SbiFundHolding = {
  quantity: number
  last_price: number
  average_cost: number
  reported_market_value: number
  reported_cost_basis: number
}
export type SbiFundDaily = {
  code: string
  bucket: string
  value: number
  return_jpy: number
  holdings: SbiFundHolding | null
}
export type SbiFundReturn = SbiFundDaily & {
  name: string
  symbol: string | null
  held: boolean
  sold: number
  distributions: number
  purchases: number
  fees: number
  return_pct: number
}
export type SbiReturnTotals = Omit<SbiFundReturn, 'code' | 'bucket' | 'holdings' | 'name' | 'symbol' | 'held' | 'return_pct'> & {return_pct: number | null}
export type SbiReturns = {
  latest: {as_of: string; holdings_observed_at: string | null; totals: SbiReturnTotals; funds: SbiFundReturn[]} | null
  history: {as_of: string; holdings_observed_at: string | null; totals: SbiReturnTotals; funds: SbiFundDaily[]}[]
}
export type SbiFundHistory = {
  code: string
  as_of?: string
  events: {day: string; action: string; bucket: string; units: number; amount: number; fee: number;
    ordinary: number; special: number; holding_units: number; nav: number; value: number; principal: number}[]
}
