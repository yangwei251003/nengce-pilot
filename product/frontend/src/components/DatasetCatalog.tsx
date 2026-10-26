import { useRef, useState } from 'react';
import type { Dataset } from '../types';
import { request } from '../api';
import { Icon } from '../icons';
import { Badge, Button, Notice, number, Section } from '../ui';
import { QualityDetails } from './QualityDetails';
type ImportResponse = {
    valid: boolean;
    dataset?: Dataset;
    errors?: {
        row: number;
        field: string;
        reason: string;
    }[];
    error_count?: number;
};
const isPublic = (dataset: Dataset) => dataset.public_data === true || dataset.privacy === 'public' || dataset.source_type === 'public_observed';
export function DatasetCatalog({ datasets, selectedId, onChoose, onImported }: {
    datasets: Dataset[];
    selectedId?: string;
    onChoose: (dataset: Dataset) => void;
    onImported: (dataset: Dataset) => void;
}) {
    const [search, setSearch] = useState('');
    const [scope, setScope] = useState('all');
    const [importing, setImporting] = useState(false);
    const [expanded, setExpanded] = useState<string | null>(null);
    const filtered = datasets.filter(dataset => `${dataset.name} ${dataset.dataset_id}`.toLowerCase().includes(search.toLowerCase()) && (scope === 'all' || (scope === 'public') === isPublic(dataset)));
    return <>
    <div className="page-heading">
    <div>
    <span className="eyebrow">DATA CATALOG</span>
    <h1>数据目录</h1>
    <p>时间、来源和适用范围，先于任何模型成绩。</p>
    </div>
    <Button onClick={() => setImporting(value => !value)} variant={importing ? 'secondary' : 'primary'}>
    <Icon name={importing ? 'close' : 'down'} size={16}/>{importing ? '关闭导入' : '导入私人 CSV'}</Button>
    </div>
    {importing && <CSVImport onImported={dataset => { onImported(dataset); setImporting(false); }}/>}
    <div className="catalog-toolbar">
    <label className="search-field">
    <Icon name="data" size={17}/>
    <input aria-label="搜索数据目录" placeholder="搜索站点、数据名称…" value={search} onChange={event => setSearch(event.target.value)}/>
    </label>
    <div className="segmented">{[['all', '全部'], ['public', '公开案例'], ['private', '私人导入']].map(([value, label]) => <button key={value} aria-pressed={scope === value} className={scope === value ? 'active' : ''} onClick={() => setScope(value)}>{label}</button>)}</div>
    <span className="caption">{filtered.length} 份数据</span>
    </div>
    <div className="dataset-grid">{filtered.map(dataset => <Section key={dataset.dataset_id} className={`dataset-card ${selectedId === dataset.dataset_id ? 'is-selected' : ''}`}>
      <div className="dataset-card-top">
        <div className="dataset-symbol">
        <Icon name={dataset.pv_available ? 'bolt' : 'grid'} size={25}/>
        </div>
        <Badge tone={isPublic(dataset) ? 'green' : 'neutral'}>{isPublic(dataset) ? '公开案例' : '私人 · 本机'}</Badge>{selectedId === dataset.dataset_id && <span className="selected-indicator">
            <Icon name="check" size={14}/>当前草稿</span>}</div>
      <h2>{dataset.name}</h2>
        <p className="dataset-identity">{dataset.dataset_id}</p>
      {dataset.runtime_ready === false && <Notice tone="warning">公开原件未齐：请按 README 的数据准备步骤取得并校验缺失文件，当前仅供审查。</Notice>}
      <div className="dataset-facts">
        <div>
        <span>原生间隔</span>
        <strong>{dataset.interval_minutes || '—'}<small>分钟</small>
        </strong>
        </div>
        <div>
        <span>记录总数</span>
        <strong>{number(dataset.rows ?? dataset.rows_hourly, 0)}</strong>
        </div>
        <div>
        <span>光伏序列</span>
        <strong>{dataset.pv_available ? '已提供' : '未提供'}</strong>
        </div>
        </div>
      <div className="dataset-period">
        <Icon name="clock" size={14}/>{dataset.start.slice(0, 10)} <span>至</span> {dataset.end.slice(0, 10)}</div>
      <div className="dataset-capabilities">
        <Badge tone={dataset.quality.passed === false ? 'red' : 'neutral'}>{dataset.quality.passed === false ? '质量未通过' : dataset.quality.passed === true ? '数据质量已核验' : '质量待核验'}</Badge>
        <Badge tone={dataset.demand_eligible ? 'green' : 'amber'}>{dataset.demand_eligible ? '可核算原生需量' : '需量适用性受限'}</Badge>
        </div>
      <p className="caption dataset-scope">{dataset.scope?.reason || (dataset.interval_minutes === 60 ? '小时级数据不插值冒充 15 分钟需量。' : '适用性以来源、完整月覆盖与冻结协议为据。')}</p>
      <div className="dataset-card-actions">
        <button className="text-button" onClick={() => setExpanded(expanded === dataset.dataset_id ? null : dataset.dataset_id)}>来源与审查<Icon name="chevron" size={14}/>
        </button>
        <Button disabled={dataset.scope?.dispatch === false || dataset.runtime_ready === false} variant={selectedId === dataset.dataset_id ? 'secondary' : 'primary'} onClick={() => onChoose(dataset)}>{dataset.runtime_ready === false ? '需补齐公开原件' : dataset.scope?.dispatch === false ? '仅可审查' : selectedId === dataset.dataset_id ? '检查参数' : '用于方案'}<Icon name="arrow" size={14}/>
        </Button>
        </div>
      {expanded === dataset.dataset_id && <div className="dataset-audit">
            <QualityDetails datasetId={dataset.dataset_id} totalRows={dataset.rows ?? dataset.rows_hourly}/>
            <dl>
            <div>
            <dt>时区 / 时间语义</dt>
            <dd>{dataset.timezone}</dd>
            </div>
            <div>
            <dt>来源许可</dt>
            <dd>{String(dataset.provenance.license || '来源未提供许可摘要')}</dd>
            </div>
            </dl>
            <details>
            <summary>质量与原始指纹</summary>
            <pre>{JSON.stringify({ quality: dataset.quality, provenance: dataset.provenance, default_evaluation: dataset.default_evaluation }, null, 2)}</pre>
            </details>
            </div>}
    </Section>)}</div>
    {filtered.length === 0 && <Notice>当前筛选没有匹配的数据。可以改变筛选，或导入拥有使用授权的 CSV。</Notice>}
  </>;
}
function CSVImport({ onImported }: {
    onImported: (dataset: Dataset) => void;
}) {
    const [name, setName] = useState('私人授权站点');
    const [timezone, setTimezone] = useState('source-local-unknown');
    const [unit, setUnit] = useState('kW');
    const [interval, setInterval] = useState(60);
    const [pvColumn, setPVColumn] = useState('');
    const [authorized, setAuthorized] = useState(false);
    const [text, setText] = useState('');
    const [filename, setFilename] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [validation, setValidation] = useState<ImportResponse | null>(null);
    const lock = useRef(false);
    async function readFile(file?: File) {
        if (!file)
            return;
        if (file.size > 20000000) {
            setError('CSV 超过 20 MB，请限定到本次所需数据范围。');
            return;
        }
        try {
            setText(await file.text());
            setFilename(file.name);
            setError('');
            setValidation(null);
        }
        catch (failure) {
            setError(`文件读取失败：${String(failure)}`);
        }
    }
    async function submit() {
        if (lock.current)
            return;
        if (!authorized) {
            setError('请先确认拥有本文件数据的使用授权。');
            return;
        }
        if (!text.trim()) {
            setError('请先选择文件或粘贴 CSV 内容。');
            return;
        }
        lock.current = true;
        setBusy(true);
        setError('');
        setValidation(null);
        try {
            const response = await request<ImportResponse>('/datasets/import', { method: 'POST', body: JSON.stringify({ name, timezone, unit, authorized, csv_text: text, interval_minutes: interval, pv_column: pvColumn.trim() || null }) });
            setValidation(response);
            if (response.valid && response.dataset)
                onImported(response.dataset);
        }
        catch (failure) {
            setError(`导入未完成：${String(failure)}`);
        }
        finally {
            lock.current = false;
            setBusy(false);
        }
    }
    return <Section title="私人数据，默认留在本机" eyebrow="LOCAL IMPORT" className="csv-import" action={<Badge>不提供给在线助手</Badge>}>
    <form onSubmit={event => { event.preventDefault(); void submit(); }}>
      <div className="import-fields">
    <label className="field">数据名称<input required value={name} maxLength={120} onChange={event => setName(event.target.value)}/>
    </label>
    <label className="field">时间语义 / 时区<input required value={timezone} onChange={event => setTimezone(event.target.value)}/>
    </label>
    <label className="field">原生计量间隔<select aria-label="原生计量间隔" value={interval} onChange={event => setInterval(Number(event.target.value))}>
    <option value={60}>60 分钟</option>
    <option value={15}>15 分钟</option>
    </select>
    </label>
    <label className="field">数值单位<select aria-label="CSV 数值单位" value={unit} onChange={event => setUnit(event.target.value)}>
    <option value="kW">kW · 区间平均功率</option>
    <option value="kWh">kWh · 原生区间电量</option>
    </select>
    </label>
    <label className="field">光伏列名（可选）<input value={pvColumn} placeholder={unit === 'kW' ? '例如 pv_kw' : '例如 pv_kwh'} onChange={event => setPVColumn(event.target.value)}/>
    </label>
    </div>
      <label className="file-drop">
    <Icon name="file" size={28}/>
    <strong>{filename || '选择本机 CSV 文件'}</strong>
    <span>UTF-8 · 最大 20 MB · 时间为区间开始</span>
    <input type="file" aria-label="选择 CSV 文件" accept=".csv,text/csv" onChange={event => void readFile(event.target.files?.[0])}/>
    </label>
      <details className="paste-csv">
    <summary>或粘贴 CSV 内容</summary>
    <textarea aria-label="CSV 内容" value={text} onChange={event => { setText(event.target.value); setFilename('粘贴的 CSV'); }} placeholder={`timestamp,${unit === 'kW' ? 'load_kw' : 'load_kwh'}\n2025-01-01 00:00:00,42.0\n...`}/>
    </details>
      <p className="caption">必须包含 timestamp 与 {unit === 'kW' ? 'load_kw' : 'load_kwh'}；可选光伏列使用相同单位。完整性、原始行、重复和缺口由本地服务审查，不静默插补。</p>
      <label className="authorization">
    <input type="checkbox" checked={authorized} onChange={event => setAuthorized(event.target.checked)}/>我拥有将这些数据用于本机预测、计划、回放与证据导出的授权。</label>
      {error && <Notice tone="danger">{error}</Notice>}
      {validation && !validation.valid && <Notice tone="danger" title={`数据未通过校验 · ${validation.error_count || validation.errors?.length || 0} 项问题`}>
        <ul>{validation.errors?.map((item, index) => <li key={index}>{item.row > 0 ? `原始 CSV 第 ${item.row} 行` : '文件级检查'}：{item.reason}</li>)}</ul>
        </Notice>}
      <div className="import-submit">
    <span className="caption">只发送给本机计算服务；数据用途不会自动扩大。</span>
    <Button type="submit" disabled={busy}>{busy ? '正在审查文件' : '校验并导入'}<Icon name="arrow" size={15}/>
    </Button>
    </div>
    </form>
  </Section>;
}
