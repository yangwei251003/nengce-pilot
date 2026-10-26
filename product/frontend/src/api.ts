import type { Config } from './types';

let prefix = '/api/v3';

export function apiPath(path: string): string {
  return `${prefix}${path}`;
}

export async function discoverAPI(): Promise<void> {
  const response = await fetch('/api/v3/health');
  if (response.status === 404) prefix = '/api';
  else if (!response.ok) throw new Error(`计算服务连接失败（${response.status}）`);
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiPath(path), {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try {
      const payload = JSON.parse(raw);
      detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || payload);
    } catch { /* Preserve the actual server response. */ }
    throw new Error(`${response.status} · ${detail || response.statusText}`);
  }
  return response.json();
}

export function readSaved(key: string): string | null {
  try { return localStorage.getItem(`nengce.v3.${key}`); } catch { return null; }
}

export function save(key: string, value: unknown): void {
  try { localStorage.setItem(`nengce.v3.${key}`, typeof value === 'string' ? value : JSON.stringify(value)); } catch { /* Private browsing can disable persistence. */ }
}

export function forget(key: string): void {
  try { localStorage.removeItem(`nengce.v3.${key}`); } catch { /* No persistence is available. */ }
}

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

export function configSignature(config: Config): string {
  const business = {
    dataset_id: config.dataset_id,
    battery: config.battery,
    tariff: {
      ...config.tariff,
      prices: config.tariff.prices ?? null,
      demand_per_kw: config.tariff.demand_per_kw ?? 0,
      billing_identity: config.tariff.billing_identity || 'illustrative',
      peak_hours: [...config.tariff.peak_hours].sort((a, b) => a - b),
      offpeak_hours: [...config.tariff.offpeak_hours].sort((a, b) => a - b),
    },
    evaluation: config.evaluation,
    risk_margin_scale: config.risk_margin_scale ?? 1,
    stress: config.stress || 'none',
    protocol_id: config.protocol_id ?? null,
  };
  function canonical(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]));
    return value;
  }
  return JSON.stringify(canonical(business));
}

export const active = (run?: { status: string } | null) => Boolean(run && !['succeeded', 'failed', 'cancelled', 'completed'].includes(run.status));
const statusLabels: Record<string, string> = {
  running: '计算中', interrupted: '运行已中断',
  queued: '排队中', validating: '审查数据', forecasting: '验证预测', optimizing: '求解计划',
  replaying: '执行回放', evaluating: '核对账单', exporting: '保存证据',
  succeeded: '计算完成', completed: '已完成', failed: '运行失败', cancelled: '已取消',
};
export const statusLabel = (status: string) => statusLabels[status] || status;
