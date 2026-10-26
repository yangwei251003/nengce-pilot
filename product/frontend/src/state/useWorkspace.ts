import { useEffect, useRef, useState } from 'react';
import type { AssistantStatus, Batch, Config, Dataset, Run, RunPage } from '../types';
import { active, clone, configSignature, discoverAPI, forget, readSaved, request, save } from '../api';

export type Page = 'workspace' | 'datasets' | 'costs' | 'forecast' | 'history';
const pages: Page[] = ['workspace', 'datasets', 'costs', 'forecast', 'history'];

function readRoute(): { page: Page; runId: string } {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const page = params.get('page') as Page;
  return { page: pages.includes(page) ? page : 'workspace', runId: params.get('run') || '' };
}

function writeRoute(page: Page, runId: string, replace = false) {
  window.history[replace ? 'replaceState' : 'pushState'](null, '', `#page=${page}${runId ? `&run=${encodeURIComponent(runId)}` : ''}`);
}

export function validateConfig(config: Config): string {
  const b = config.battery;
  if (!Object.values(b).every(Number.isFinite)) return '请填写有效的电池参数。';
  if (b.capacity_kwh <= 0 || b.power_kw <= 0) return '电池容量与充放电功率必须大于 0。';
  if (!(b.min_soc >= 0 && b.max_soc <= 1 && b.min_soc < b.max_soc && b.min_soc <= b.initial_soc && b.initial_soc <= b.max_soc)) return 'SOC 需要满足：最低 SOC ≤ 初始 SOC ≤ 最高 SOC，且最低值小于最高值。';
  if (b.charge_efficiency <= 0 || b.charge_efficiency > 1 || b.discharge_efficiency <= 0 || b.discharge_efficiency > 1) return '充放电效率需大于 0 且不超过 100%。';
  if (!config.evaluation.start || !config.evaluation.end || config.evaluation.start > config.evaluation.end) return '请检查回放日期，开始时间不能晚于结束时间。';
  if (![config.tariff.offpeak, config.tariff.flat, config.tariff.peak, config.tariff.demand_per_kw ?? 0].every(value => Number.isFinite(value) && value >= 0)) return '电价必须是非负有限数值。';
  return '';
}

function configForDataset(dataset: Dataset, defaults: Config): Config {
  const next = clone(defaults);
  next.dataset_id = dataset.dataset_id;
  if (dataset.default_evaluation) {
    next.evaluation = { start: dataset.default_evaluation.test_start.slice(0, 10), end: dataset.default_evaluation.test_end.slice(0, 10) };
    next.protocol_id = dataset.default_evaluation.protocol_id || null;
  } else if (dataset.dataset_id === 'uci-steel-hourly') {
    next.evaluation = { start: '2018-12-01', end: '2018-12-31' };
  } else {
    const first = Date.parse(dataset.start.slice(0, 10)) + 75 * 86400000;
    const last = Math.min(Date.parse(dataset.end.slice(0, 10)), first + 30 * 86400000);
    next.evaluation = { start: new Date(first).toISOString().slice(0, 10), end: new Date(last).toISOString().slice(0, 10) };
    next.protocol_id = null;
  }
  return next;
}

export function useWorkspace() {
  const [page, setPage] = useState<Page>(readRoute().page);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [defaults, setDefaults] = useState<Config | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [historyTotal, setHistoryTotal] = useState<number | undefined>();
  const [loading, setLoading] = useState(true);
  const [loadingRun, setLoadingRun] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cancelPending, setCancelPending] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [batch, setBatch] = useState<Batch | null>(null);
  const [assistantStatus, setAssistantStatus] = useState<AssistantStatus>({ available: false, message: '正在读取助手服务状态' });
  const [boot, setBoot] = useState(0);
  const runId = useRef('');
  const loadGeneration = useRef(0);
  const submitLock = useRef(false);
  const pageRef = useRef(page);
  pageRef.current = page;

  const result = !loadingRun && run?.status === 'succeeded' && run.result ? { ...run.result, api_run_id: run.run_id } : undefined;
  const dataset = datasets.find(item => item.dataset_id === config?.dataset_id);
  const frozenDataset = result?.dataset || datasets.find(item => item.dataset_id === run?.config.dataset_id);
  const working = active(run) || submitting;
  const dirty = Boolean(config && run?.config && configSignature(config) !== configSignature(run.config));

  function updateConfig(next: Config) { setConfig(next); save('draft', next); }
  function navigate(next: Page) { setPage(next); writeRoute(next, runId.current); }

  async function refreshHistory(cursor?: string) {
    try {
      const response = await request<RunPage>(`/runs?limit=12${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
      setHistory(previous => cursor ? [...previous, ...response.runs.filter(item => !previous.some(savedRun => savedRun.run_id === item.run_id))] : response.runs);
      setNextCursor(response.next_cursor || null);
      setHistoryTotal(response.total);
    } catch (issue) { setError(`读取运行记录失败：${String(issue)}`); }
  }

  async function selectRun(id: string, goToWorkspace = true) {
    if (!id || submitting) return;
    const generation = ++loadGeneration.current;
    setLoadingRun(true); setError('');
    try {
      const next = await request<Run>(`/runs/${encodeURIComponent(id)}`);
      if (generation !== loadGeneration.current) return;
      runId.current = id;
      setRun(next); updateConfig(clone(next.config)); setCancelPending(false);
      save('run', id);
      const nextPage = goToWorkspace ? 'workspace' : pageRef.current;
      setPage(nextPage); writeRoute(nextPage, id, !goToWorkspace);
    } catch (issue) { if (generation === loadGeneration.current) setError(`读取运行失败：${String(issue)}`); }
    finally { if (generation === loadGeneration.current) setLoadingRun(false); }
  }

  useEffect(() => {
    let stopped = false;
    setLoading(true); setError('');
    (async () => {
      try {
        await discoverAPI();
        const [data, initial, runs] = await Promise.all([
          request<{ datasets: Dataset[] }>('/datasets'), request<Config>('/defaults'), request<RunPage>('/runs?limit=12'),
        ]);
        if (stopped) return;
        setDatasets(data.datasets); setDefaults(initial);
        const demoDataset = data.datasets.find(item => item.dataset_id === 'uci-steel-15min');
        const firstDraft = demoDataset ? configForDataset(demoDataset, initial) : clone(initial);
        firstDraft.evaluation.end = firstDraft.evaluation.start;
        setConfig(firstDraft);
        setHistory(runs.runs); setNextCursor(runs.next_cursor || null); setHistoryTotal(runs.total);
        const route = readRoute();
        const id = route.runId || readSaved('run');
        if (id) {
          try {
            const restored = await request<Run>(`/runs/${encodeURIComponent(id)}`);
            if (stopped) return;
            runId.current = id; setRun(restored); setConfig(clone(restored.config)); writeRoute(route.page, id, true);
          } catch { forget('run'); setError('上次运行无法恢复；可以在运行记录中重新选择，或创建一次新运行。'); }
        }
        try {
          const draft = JSON.parse(readSaved('draft') || 'null') as Config | null;
          if (draft && data.datasets.some(item => item.dataset_id === draft.dataset_id)) setConfig(draft);
        } catch { forget('draft'); }
        request<AssistantStatus>('/assistant/status').then(value => { if (!stopped) setAssistantStatus(value); }).catch(() => { if (!stopped) setAssistantStatus({ available: false, message: '助手服务尚未就绪，核心计算仍可独立运行。' }); });
        const savedBatch = readSaved('batch');
        if (savedBatch) request<Batch>(`/batches/${encodeURIComponent(savedBatch)}`).then(value => { if (!stopped) setBatch(value); }).catch(() => { forget('batch'); });
      } catch (issue) { if (!stopped) setError(`本地服务连接失败：${String(issue)}`); }
      finally { if (!stopped) setLoading(false); }
    })();
    return () => { stopped = true; };
  }, [boot]);

  useEffect(() => {
    const onLocation = () => {
      const route = readRoute();
      setPage(route.page);
      if (route.runId && route.runId !== runId.current) void selectRun(route.runId, false);
    };
    window.addEventListener('popstate', onLocation);
    window.addEventListener('hashchange', onLocation);
    return () => { window.removeEventListener('popstate', onLocation); window.removeEventListener('hashchange', onLocation); };
  }, []);

  useEffect(() => {
    if (!run || !active(run)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const id = run.run_id, generation = loadGeneration.current;
    async function poll() {
      try {
        const next = await request<Run>(`/runs/${encodeURIComponent(id)}`);
        if (stopped || generation !== loadGeneration.current || runId.current !== id) return;
        setRun(next);
        setError(previous => previous.startsWith('暂时无法读取进度') ? '' : previous);
        if (active(next)) timer = setTimeout(poll, 900);
        else {
          setCancelPending(false); void refreshHistory();
          setToast(next.status === 'succeeded' ? '计算完成，结果与证据已保存。' : next.message || '运行已结束。');
        }
      } catch (issue) {
        if (!stopped && generation === loadGeneration.current) {
          setError(`暂时无法读取进度：${String(issue)}。正在重连，不会重复创建计算。`);
          timer = setTimeout(poll, 3000);
        }
      }
    }
    timer = setTimeout(poll, 600);
    return () => { stopped = true; clearTimeout(timer); };
  }, [run?.run_id, run?.status, loadingRun]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 4500);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!batch || !active({ status: batch.status || 'queued' })) return;
    let stopped = false;
    const timer = setInterval(async () => {
      try {
        const next = await request<Batch>(`/batches/${encodeURIComponent(batch.batch_id)}`);
        if (!stopped) { setBatch(next); if (!active(next as { status: string })) void refreshHistory(); }
      } catch (issue) { if (!stopped) setError(`批量状态暂不可用：${String(issue)}`); }
    }, 1400);
    return () => { stopped = true; clearInterval(timer); };
  }, [batch?.batch_id, batch?.status]);

  async function start() {
    if (!config || working || loadingRun || submitLock.current) return false;
    const issue = dataset?.scope?.dispatch === false ? dataset.scope.reason || '此数据仅用于审查，不能启动收益回放。' : validateConfig(config);
    if (issue) { setError(issue); return false; }
    submitLock.current = true; setSubmitting(true); setError('');
    const body = clone(config), signature = configSignature(body);
    let key = crypto.randomUUID();
    try { const pending = JSON.parse(readSaved('pending') || 'null'); if (pending?.signature === signature) key = pending.key; } catch { /* A malformed local draft cannot create a duplicate key. */ }
    save('pending', { signature, key });
    try {
      const next = await request<Run>('/runs', { method: 'POST', body: JSON.stringify({ ...body, idempotency_key: key }) });
      ++loadGeneration.current;
      runId.current = next.run_id;
      setRun({ ...next, config: next.config || body, progress: next.progress || 0 });
      save('run', next.run_id); forget('pending'); setCancelPending(false);
      setPage('workspace'); writeRoute('workspace', next.run_id); void refreshHistory();
      if (next.status === 'succeeded' && !next.result) {
        const completed = await request<Run>(`/runs/${encodeURIComponent(next.run_id)}`);
        setRun(completed);
      }
      return true;
    } catch (failure) {
      setError(`提交未确认：${String(failure)}。重试相同配置会复用请求标识。`);
      if (/^Error: 4\d\d/.test(String(failure))) forget('pending');
      return false;
    } finally { submitLock.current = false; setSubmitting(false); }
  }

  async function cancel() {
    if (!run || cancelPending) return;
    setCancelPending(true);
    try { await request(`/runs/${encodeURIComponent(run.run_id)}/cancel`, { method: 'POST' }); }
    catch (issue) { setCancelPending(false); setError(`取消未确认：${String(issue)}`); }
  }

  function chooseDataset(selected: Dataset) {
    if (defaults) updateConfig(configForDataset(selected, config || defaults));
    setToast('数据已设为草稿，请审查参数后运行。');
  }

  function imported(selected: Dataset) {
    setDatasets(previous => [...previous.filter(item => item.dataset_id !== selected.dataset_id), selected]);
    chooseDataset(selected);
  }

  async function startBatch(stresses: string[]) {
    if (!config || !stresses.length || submitLock.current) return;
    await startBatchConfigs(stresses.map(stress => ({ ...clone(config), stress })));
  }

  async function startBatchConfigs(configs: Config[]) {
    if (!configs.length || configs.length > 20 || submitLock.current) return;
    for (const item of configs) {
      const source = datasets.find(dataset => dataset.dataset_id === item.dataset_id);
      const issue = source?.scope?.dispatch === false ? source.scope.reason || '此数据仅用于审查。' : validateConfig(item);
      if (issue) { setError(issue); return; }
    }
    submitLock.current = true; setSubmitting(true); setError('');
    const signature = JSON.stringify(configs.map(configSignature));
    let key = crypto.randomUUID();
    try { const pending = JSON.parse(readSaved('batch.pending') || 'null'); if (pending?.signature === signature) key = pending.key; } catch { /* Invalid cached metadata cannot supply an idempotency key. */ }
    save('batch.pending', { signature, key });
    try {
      const response = await request<Batch>('/batches', { method: 'POST', body: JSON.stringify({ configs, idempotency_key: key }) });
      forget('batch.pending'); save('batch', response.batch_id); setBatch(response); navigate('history'); void refreshHistory();
    } catch (issue) { setError(`批量评估未能创建：${String(issue)}`); }
    finally { submitLock.current = false; setSubmitting(false); }
  }

  return {
    page, navigate, datasets, dataset, frozenDataset, defaults, config, updateConfig, run, result,
    history, nextCursor, historyTotal, refreshHistory, selectRun, loading, loadingRun, submitting, working,
    cancelPending, error, setError, toast, setToast, dirty, batch, startBatch, startBatchConfigs, assistantStatus,
    start, cancel, chooseDataset, imported, retryConnection: () => setBoot(value => value + 1),
    reset: () => { if (defaults) updateConfig(dataset ? configForDataset(dataset, defaults) : clone(defaults)); },
  };
}
