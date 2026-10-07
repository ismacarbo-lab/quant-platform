// Typed client for the local dashboard API. All calls are same-origin.

export type Metrics = {
  sessions: number;
  years: number | null;
  total_return: number | null;
  cagr: number | null;
  annual_volatility: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  calmar: number | null;
  best_day: number | null;
  worst_day: number | null;
  positive_months: number | null;
  best_month: number | null;
  worst_month: number | null;
  annual_turnover: number | null;
  total_costs: number | null;
  average_exposure: number | null;
  final_equity: number | null;
  start: string | null;
  end: string | null;
};

export type Promotion = {
  eligible: boolean;
  reasons: string[];
  strategy_sharpe: number | null;
  benchmark_sharpe: number | null;
  strategy_max_drawdown: number | null;
  benchmark_max_drawdown: number | null;
  strategy_cagr: number | null;
};

export type BacktestSummary = {
  id: string;
  created_at: string;
  strategy_name: string;
  strategy_title: string;
  params: Record<string, unknown>;
  benchmark_name: string;
  source_name: string;
  symbols: string[];
  start_date: string;
  end_date: string;
  rebalance: string;
  commission_bps: number;
  slippage_bps: number;
  initial_cash: number;
  session_count: number;
  rebalance_count: number;
  metrics: Metrics;
  benchmark_metrics: Metrics;
  relative_metrics: { beta: number | null; correlation: number | null; excess_cagr: number | null };
  promotion: Promotion | null;
  promotion_eligible: boolean | null;
  walk_forward_oos_metrics: Metrics | null;
  latest_weights: Record<string, number>;
  data_hash: string;
  result_hash: string;
};

export type WalkForwardFold = {
  is_start: string;
  is_end: string;
  oos_start: string;
  oos_end: string;
  chosen_params: Record<string, unknown>;
  is_metric: number | null;
  oos_metrics: Metrics;
  candidates: number;
};

export type WalkForward = {
  strategy_name: string;
  fold_count: number;
  oos_start: string | null;
  oos_end: string | null;
  oos_metrics: Metrics;
  default_params_oos_metrics: Metrics;
  param_stability: Record<string, { distinct_values: string[]; most_common: string; most_common_share: number }>;
  folds: WalkForwardFold[];
};

export type BacktestDetail = BacktestSummary & {
  walk_forward: WalkForward | null;
  equity_curve: { date: string; equity: number; benchmark: number | null }[];
  monthly_returns: { year: number; month: number; return: number | null }[];
};

export type StrategySpec = {
  name: string;
  title: string;
  description: string;
  evidence: string;
  default_params: Record<string, unknown>;
  is_benchmark: boolean;
  param_grid: Record<string, unknown[]>;
};

export type PaperAccount = {
  id: string;
  name: string;
  strategy_name: string;
  params: Record<string, unknown>;
  status: string;
  currency: string;
  rebalance: string;
  commission_bps: number;
  slippage_bps: number;
  benchmark_symbol: string;
  initial_cash: number;
  cash: number;
  equity: number | null;
  positions_value: number | null;
  total_return: number | null;
  benchmark_equity: number | null;
  benchmark_return: number | null;
  max_drawdown: number | null;
  started_on: string | null;
  first_session: string | null;
  last_run_date: string | null;
  snapshot_count: number;
  replayed_snapshots: number;
  fill_count: number;
  weights: Record<string, string>;
  notes: string | null;
};

export type EquityPoint = {
  date: string;
  equity: number;
  cash: number;
  benchmark: number | null;
  daily_return: number | null;
  replayed: boolean;
};

export type PaperDetail = {
  account: PaperAccount;
  positions: { symbol: string; quantity: number; average_cost: number; updated_at: string }[];
  orders: {
    id: string;
    session_date: string;
    symbol: string;
    side: string;
    quantity: number;
    status: string;
    target_weight: number;
    reference_price: number;
    reason: string | null;
  }[];
  fills: {
    id: string;
    fill_date: string;
    symbol: string;
    side: string;
    quantity: number;
    price: number;
    reference_price: number;
    commission: number;
    slippage_cost: number;
    broker: string;
  }[];
  runs: {
    session_date: string;
    status: string;
    replayed: boolean;
    rebalanced: boolean;
    orders_created: number;
    fills_executed: number;
    dividends_credited: number;
    message: string | null;
    created_at: string;
  }[];
};

export type Status = {
  service: string;
  version: string;
  mode: string;
  paper_enabled: boolean;
  live_trading: string;
  real_money: boolean;
  alembic_head_expected: string;
  universe: UniverseInstrument[];
  optional_universe: UniverseInstrument[];
  capabilities: { enabled: string[]; disabled: string[] };
  database: {
    reachable: boolean;
    market_data_source?: string;
    market_data_present?: boolean;
    last_session?: string | null;
    bar_count?: number;
    symbol_count?: number;
    instrument_count?: number;
    backtest_count?: number;
    paper_account_count?: number;
    error?: string;
  };
  disclaimer: string;
};

export type UniverseInstrument = {
  symbol: string;
  name: string;
  asset_class: string;
  role: string;
  category: string;
  currency: string;
  optional?: boolean;
  coverage?: {
    first_session?: string | null;
    last_session?: string | null;
    bar_count?: number;
    dividend_count?: number;
  } | null;
};

export type Bar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  adjusted_close: number | null;
};

export type Job = {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  params: Record<string, unknown>;
  result?: unknown;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      // keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  status: () => request<Status>("/api/status"),
  universe: () =>
    request<{ source_name: string; source_present: boolean; instruments: UniverseInstrument[] }>(
      "/api/market/universe",
    ),
  bars: (symbol: string, limit = 1500) =>
    request<{ symbol: string; count: number; bars: Bar[] }>(
      `/api/market/bars/${encodeURIComponent(symbol)}?limit=${limit}`,
    ),
  fetchMarketData: (body: { include_crypto?: boolean; full_refresh?: boolean; dry_run?: boolean }) =>
    request<Job>("/api/market/fetch", { method: "POST", body: JSON.stringify(body) }),
  strategies: () => request<{ strategies: StrategySpec[] }>("/api/strategies"),
  ranking: () => request<{ ranking: BacktestSummary[] }>("/api/backtests/ranking"),
  backtests: (limit = 50) => request<{ backtests: BacktestSummary[] }>(`/api/backtests?limit=${limit}`),
  backtest: (id: string) => request<BacktestDetail>(`/api/backtests/${id}`),
  runBacktests: (body: Record<string, unknown>) =>
    request<Job>("/api/backtests/run", { method: "POST", body: JSON.stringify(body) }),
  paperAccounts: () => request<{ paper_enabled: boolean; accounts: PaperAccount[] }>("/api/paper/accounts"),
  paperAccount: (name: string) => request<PaperDetail>(`/api/paper/accounts/${encodeURIComponent(name)}`),
  paperEquity: (name: string) =>
    request<{ name: string; equity: EquityPoint[] }>(`/api/paper/accounts/${encodeURIComponent(name)}/equity`),
  runPaper: (body: { fetch?: boolean; replay_from?: string | null; accounts?: string[] | null }) =>
    request<Job>("/api/paper/run", { method: "POST", body: JSON.stringify(body) }),
  setAccountStatus: (name: string, status: "active" | "paused") =>
    request<PaperAccount>(`/api/paper/accounts/${encodeURIComponent(name)}/status?status=${status}`, {
      method: "POST",
    }),
  jobs: () => request<{ jobs: Job[] }>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
};
