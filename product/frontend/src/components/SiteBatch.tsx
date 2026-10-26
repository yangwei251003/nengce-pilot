import { useMemo, useState } from 'react';
import type { Config, Dataset } from '../types';
import { siteBatchConfigs } from '../state/batchConfigs';
import { Badge, Button, Notice, number, Section, stressName } from '../ui';

export function SiteBatch({ config, datasets, busy, onSubmit }: {
  config: Config; datasets: Dataset[]; busy: boolean; onSubmit: (configs: Config[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [period, setPeriod] = useState<'day' | 'protocol'>('day');
  const [search, setSearch] = useState('');
  const configs = useMemo(() => siteBatchConfigs(config, datasets, selected, period), [config, datasets, selected, period]);
  const shown = datasets.filter(item => `${item.name} ${item.dataset_id}`.toLowerCase().includes(search.toLowerCase()));
  return <Section title="多站点独立评估" eyebrow="INDEPENDENT SITE BATCH" action={<Badge>逐站计算 · 不合并收益</Badge>}>
    <p className="muted">每站采用自己的默认评估日期与原生计量间隔。沿用当前草稿的电池、示例电价与压力条件，产生独立运行记录；不做多站协同优化。</p>
    <div className="site-batch-context"><span>电池 {number(config.battery.capacity_kwh, 0)} kWh / {number(config.battery.power_kw, 0)} kW</span><span>月需量单价 {number(config.tariff.demand_per_kw ?? 0, 2)} 元/kW·月</span><span>{stressName(config.stress)}</span></div>
    <div className="site-batch-tools"><label className="field">筛选站点<input aria-label="筛选批量评估站点" value={search} onChange={event => setSearch(event.target.value)} placeholder="站点或数据名称"/></label><label className="field">各站回放期间<select aria-label="批量站点评估期间" value={period} onChange={event => setPeriod(event.target.value as 'day' | 'protocol')}><option value="day">默认评估首日 · 快速演示</option><option value="protocol">各站协议完整评估区间</option></select></label></div>
    <div className="site-checklist" role="group" aria-label="选择独立评估站点">{shown.map(dataset => {
      const allowed = dataset.runtime_ready !== false && dataset.scope?.dispatch !== false && Boolean(dataset.default_evaluation);
      return <label key={dataset.dataset_id} className={!allowed ? 'is-unavailable' : ''}><input type="checkbox" aria-label={`批量选择 ${dataset.name}`} disabled={!allowed || busy} checked={selected.includes(dataset.dataset_id)} onChange={event => setSelected(values => event.target.checked ? [...values, dataset.dataset_id] : values.filter(value => value !== dataset.dataset_id))}/><span><strong>{dataset.name}</strong><small>{allowed ? `${dataset.interval_minutes || '—'} 分钟 · ${dataset.public_data ? '公开案例' : '私人本机'} · ${dataset.default_evaluation!.test_start.slice(0, 10)} 起` : dataset.scope?.reason || '没有可用的默认评估期间'}</small></span></label>;
    })}</div>
    {configs.length > 0 && <div className="table-scroll site-batch-preview"><table><caption>即将提交的独立配置</caption><thead><tr><th>站点</th><th>回放期间</th><th>原生间隔</th><th>需量口径</th></tr></thead><tbody>{configs.map(item => {
      const dataset = datasets.find(value => value.dataset_id === item.dataset_id)!;
      return <tr key={item.dataset_id}><th>{dataset.name}</th><td>{item.evaluation.start} → {item.evaluation.end}</td><td>{dataset.interval_minutes} 分钟</td><td>{(item.tariff.demand_per_kw || 0) === 0 ? '未启用' : period === 'day' || !dataset.demand_eligible ? '完整月账不可用' : '由后端逐月核验覆盖'}</td></tr>;
    })}</tbody></table></div>}
    {(config.tariff.demand_per_kw || 0) > 0 && <Notice tone="warning">需量单价保持当前草稿，不会悄悄改为 0。单日或覆盖不足的站点无法形成完整月账；已知小计与不可比状态将保留。</Notice>}
    {period === 'protocol' && <p className="caption">完整区间可能耗时较长，任务在本机串行执行。公开过的日期仍按历史回归解释。</p>}
    {selected.length > 20 && <Notice tone="warning">单批最多 20 个站点，请减少选择。</Notice>}
    <div className="site-batch-action"><span className="caption">已选 {selected.length} 站 · 各站独立记录</span><Button disabled={busy || !configs.length || configs.length > 20} onClick={() => onSubmit(configs)}>运行 {configs.length} 个独立站点</Button></div>
  </Section>;
}
