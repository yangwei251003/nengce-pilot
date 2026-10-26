export interface Battery {
  capacity_kwh: number;
  power_kw: number;
  min_soc: number;
  max_soc: number;
  initial_soc: number;
  charge_efficiency: number;
  discharge_efficiency: number;
  degradation_per_kwh: number;
}

export interface Tariff {
  currency: string;
  billing_identity?: string;
  offpeak: number;
  flat: number;
  peak: number;
  peak_hours: number[];
  offpeak_hours: number[];
  prices?: number[] | null;
  demand_per_kw?: number;
}

export interface Config {
  dataset_id: string;
  battery: Battery;
  tariff: Tariff;
  evaluation: { start: string; end: string };
  risk_margin_scale?: number;
  protocol_id?: string | null;
  stress?: string;
}

export interface Dataset {
  runtime_ready?: boolean;
  runtime_missing?: string[];
  dataset_id: string;
  name: string;
  rows_raw?: number;
  rows_hourly?: number;
  rows?: number;
  start: string;
  end: string;
  source_type: string;
  unit: string;
  timezone: string;
  interval_minutes?: number;
  public_data?: boolean;
  privacy?: 'public' | 'private';
  pv_available?: boolean;
  demand_eligible?: boolean;
  billing_identity?: string;
  scope?: { dispatch?: boolean; energy_billing?: boolean; demand_15min?: boolean; photovoltaic?: boolean; reason?: string };
  default_evaluation?: { train_start: string; train_end: string; validation_start: string; validation_end: string; test_start: string; test_end: string; role: string; protocol_id?: string };
  quality: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export interface Model {
  name: string;
  mae_kw: number | null;
  wape_pct: number | null;
  rmse_kw: number | null;
}

export interface Strategy {
  id: string;
  name: string;
  energy_cost: number;
  demand_cost?: number | null;
  degradation_cost: number;
  total_cost: number | null;
  known_cost_subtotal?: number;
  savings_vs_b0: number | null;
  savings_pct: number | null;
  peak_grid_kw: number;
  charge_kwh: number;
  discharge_kwh: number;
  terminal_error_kwh: number;
  max_soc_violation_kwh: number;
  simultaneous_count: number;
  grid_violation_kwh: number;
  solver: Record<string, number>;
  comparison_valid: boolean;
  clip_kwh: number;
  clip_no_export_kwh?: number;
  clip_soc_kwh?: number;
  clip_power_kwh?: number;
  throughput_kwh?: number;
  plan_replay_gap?: number | null;
  forecast_plan_cost?: number | null;
  margin_plan_failures?: number;
  fallback_count?: number;
  curtailment_kwh?: number;
  terminal_repair_kwh?: number;
  monthly_bills?: Record<string, unknown>[];
}

export interface TickStrategy {
  grid_kw: number;
  charge_kw: number;
  discharge_kw: number;
  soc_kwh: number;
  planned_charge_kw?: number;
  planned_discharge_kw?: number;
  clip_kwh?: number;
  energy_cost: number;
  cumulative_cost: number;
  curtailment_kw?: number;
  terminal_repair_kwh?: number;
  margin_relaxation_kw?: number;
}

export interface Tick {
  timestamp: string;
  actual_kw: number;
  forecast_kw: number;
  hgb_kw?: number;
  daily_naive_kw?: number;
  weekly_naive_kw?: number;
  pv_kw?: number;
  pv_forecast_kw?: number;
  pv_lower_kw?: number;
  pv_upper_kw?: number;
  interval_hours?: number;
  price: number;
  strategies: Record<string, TickStrategy>;
}

export interface Ablation {
  baseline: string;
  candidate: string;
  incremental_savings: number | null;
  incremental_savings_pct: number | null;
  comparison_valid: boolean;
  conclusion: string;
}

export interface RiskAblation {
  baseline: string;
  candidate: string;
  clip_reduction_kwh: number;
  cost_increase: number | null;
  retained_savings_pct: number | null;
  throughput_ratio: number | null;
  comparison_valid: boolean;
  predefined_gate_passed?: boolean;
  margin_plan_failures?: number;
  fallback_count?: number;
  conclusion: string;
}

export interface Result {
  run_id: string;
  api_run_id?: string;
  config?: Config;
  dataset?: Dataset;
  risk_ablation?: RiskAblation;
  risk_ablations?: RiskAblation[];
  learning_ablation?: Ablation;
  ablation?: Ablation;
  validation_conclusion?: { verdict: string; policy: string; rules: { id: string; triggered: boolean; evidence: string }[]; next_steps: string[] };
  summary: {
    period_start: string;
    period_end: string;
    hours: number;
    intervals?: number;
    interval_minutes?: number;
    interval_hours?: number;
    demand_status?: unknown;
    days: number;
    source_label: string;
    warnings: string[];
    elapsed_seconds: number;
    selected_model: string;
    recommended_strategy?: string | null;
    recommendation_reason?: string;
    comparison_valid: boolean;
  };
  forecast: {
    pv?: { selected_model: string; selection_reason?: string; models?: Model[]; interval_coverage_pct?: number | null };
    replay_forecast_metrics?: Model;
    risk_calibration?: Record<string, unknown>;
    selection_reason?: string;
    evaluation_role?: string;
    selection_policy?: unknown;
    rolling_validation?: unknown[];
    models: Model[];
    validation: Model[];
    selected_model: string;
    improvement_vs_weekly_pct: number | null;
    train_end: string;
    validation_period: unknown;
    holdout_period: unknown;
    features: string[];
    notes: string[];
  };
  strategies: Strategy[];
  series: Tick[];
  daily: Record<string, string | number>[];
  monthly_bills?: Record<string, Record<string, unknown>[]>;
  assumptions: string[];
  artifacts: Record<string, string>;
  reproducibility?: Record<string, unknown>;
}

export interface Run {
  run_id: string;
  brief?: { strategy: string; total_cost: number | null; comparison_valid: boolean };
  legacy?: boolean;
  original_run_id?: string;
  status: string;
  progress: number;
  stage: string;
  message: string;
  created_at: string;
  completed_at?: string;
  config: Config;
  result?: Result;
  error?: unknown;
}

export interface RunPage { runs: Run[]; next_cursor?: string | null; total?: number }
export interface Batch { batch_id: string; status?: string; runs: Run[] }
export interface Citation { id: string; label: string; run_id?: string; section?: string; timestamp?: string; strategy?: string }
export interface ModelProfile {
  id: string;
  name: string;
  kind: 'cloud' | 'local';
  base_url: string;
  model: string;
  has_key: boolean;
  billing_ack: boolean;
  max_tokens: number;
  created_at?: string;
  updated_at?: string;
}
export interface ModelProfilePage { profiles: ModelProfile[]; secret_storage?: string; default_provider?: string }
export interface ModelConnectionTest { ok: boolean; model: string; kind: 'cloud' | 'local'; elapsed_seconds: number; message: string }
export interface AssistantStatus {
  available: boolean;
  local_available?: boolean;
  default_provider?: string;
  provider?: string;
  model?: string;
  public_only?: boolean;
  message?: string;
  disclosure?: string;
  profiles?: ModelProfile[];
  builtin_providers?: { id: string; name: string; available: boolean; model: string; connection_verified?: boolean }[];
  manual_backups?: { provider: string; name?: string; model: string; available?: boolean }[];
}
export interface ChatMessage { role: 'user' | 'assistant'; content: string; citations?: Citation[]; draft_patch?: Partial<Config>; model?: string; disclosure?: string }
export interface AssistantRequest {
  request_id: string;
  session_id?: string;
  status: string;
  stage?: string;
  message?: string;
  content?: string;
  citations?: Citation[];
  draft_patch?: Partial<Config>;
  mode?: string;
  model?: string;
  disclosure?: string;
}
