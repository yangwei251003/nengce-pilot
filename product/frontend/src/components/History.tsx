import { useState } from 'react';
import type { Batch, Config, Dataset, Run } from '../types';
import { active, statusLabel } from '../api';
import { Badge, Button, Empty, number, Section, stressName } from '../ui';
import { SiteBatch } from './SiteBatch';
export function History({ runs, total, nextCursor, batch, config, datasets, busy, onLoadMore, onSelect, onBatch, onSiteBatch }: {
    runs: Run[];
    total?: number;
    nextCursor: string | null;
    batch: Batch | null;
    config: Config;
    datasets: Dataset[];
    busy: boolean;
    onLoadMore: () => void;
    onSelect: (id: string) => void;
    onBatch: (stresses: string[]) => void;
    onSiteBatch: (configs: Config[]) => void;
}) {
    const [stresses, setStresses] = useState(['none', 'load_up_20', 'forecast_bias_up_20']);
    const [moreBusy, setMoreBusy] = useState(false);
    return <div className="page-stack">
    <div className="page-heading">
    <div>
    <span className="eyebrow">RUN LIBRARY</span>
    <h1>保留每一次计算</h1>
    <p>原始配置、失败与取消状态随运行保存。历史记录可以恢复，不覆盖现有证据。</p>
    </div>
    <Badge>{total === undefined ? `${runs.length} 条已加载` : `${total} 次运行`}</Badge>
    </div>
    <Section title="同一参数，批量压力评估" action={<Badge>本机串行队列</Badge>}>
    <p className="muted">沿用当前草稿：{datasets.find(item => item.dataset_id === config.dataset_id)?.name} · {config.evaluation.start} → {config.evaluation.end}</p>
    <div className="stress-options">{['none', 'load_up_20', 'peak_price_up_20', 'forecast_bias_up_20', 'pv_drop_30'].map(stress => <label className="check-label" key={stress}>
        <input type="checkbox" checked={stresses.includes(stress)} onChange={event => setStresses(values => event.target.checked ? [...values, stress] : values.filter(value => value !== stress))}/>{stressName(stress)}</label>)}</div>
    <Button disabled={busy || !stresses.length || Boolean(batch && active({ status: batch.status || 'queued' }))} onClick={() => onBatch(stresses)}>创建 {stresses.length} 个情景</Button>
      {batch && <div className="batch-list" aria-live="polite">
        <h3>批次 {batch.batch_id.slice(0, 8)} · {statusLabel(batch.status || 'queued')}</h3>{batch.runs.map(run => <button className="batch-item" key={run.run_id} onClick={() => onSelect(run.run_id)}>
            <span>{datasets.find(item => item.dataset_id === run.config?.dataset_id)?.name || run.config?.dataset_id}<small>{run.config?.evaluation.start} → {run.config?.evaluation.end} · {stressName(run.config?.stress)}</small></span>
            <Badge tone={run.status === 'succeeded' ? 'green' : run.status === 'failed' ? 'red' : 'neutral'}>{statusLabel(run.status)}</Badge>
            <span>{run.message}</span>
            </button>)}</div>}
    </Section>
    <SiteBatch config={config} datasets={datasets} busy={busy || Boolean(batch && active({ status: batch.status || 'queued' }))} onSubmit={onSiteBatch}/>
    <Section title="运行记录" action={<span className="muted">新 → 旧</span>}>{runs.length ? <>
        <div className="table-scroll">
        <table className="history-table">
        <thead>
        <tr>
        <th>运行 / 数据</th>
        <th>回放期间</th>
        <th>情景</th>
        <th>状态</th>
        <th>B2 费用 / 元</th>
        <th>操作</th>
        </tr>
        </thead>
        <tbody>{runs.map(run => <tr key={run.run_id}>
            <th>
            <code>{run.run_id.slice(0, 12)}</code>{run.legacy && <Badge>V2 存档</Badge>}<small>{datasets.find(item => item.dataset_id === run.config?.dataset_id)?.name || run.config?.dataset_id}</small>
            </th>
            <td>{run.config?.evaluation.start}<small>至 {run.config?.evaluation.end}</small>
            </td>
            <td>{stressName(run.config?.stress)}</td>
            <td>
            <Badge tone={run.status === 'succeeded' ? 'green' : run.status === 'failed' ? 'red' : 'neutral'}>{statusLabel(run.status)}</Badge>
            </td>
            <td>{number(run.brief ? run.brief.total_cost : run.result?.strategies.find(item => item.id === 'B2')?.total_cost, 2)}{run.brief?.comparison_valid === false && <small><Badge tone="amber">不可比</Badge></small>}</td>
            <td>
            <Button variant="ghost" disabled={busy} onClick={() => onSelect(run.run_id)}>打开运行</Button>
            </td>
            </tr>)}</tbody>
        </table>
        </div>{nextCursor && <div className="load-more">
            <Button disabled={moreBusy} variant="secondary" onClick={async () => { setMoreBusy(true); try {
                await onLoadMore();
            }
            finally {
                setMoreBusy(false);
            } }}>{moreBusy ? '读取中…' : '加载更多记录'}</Button>
            </div>}</> : <Empty compact title="还没有运行记录">首次计算完成后，这里会保存可恢复的记录。</Empty>}</Section>
  </div>;
}
