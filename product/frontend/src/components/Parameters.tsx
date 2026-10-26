import { useState } from 'react';
import type { Config, Dataset } from '../types';
import { Icon } from '../icons';
import { Badge, Button, Notice, NumberField, number } from '../ui';
import { validateConfig } from '../state/useWorkspace';
const labels: Record<string, string> = {
    'battery.capacity_kwh': '电池容量', 'battery.power_kw': '充放电功率', 'battery.initial_soc': '初始 SOC',
    'battery.min_soc': '最低 SOC', 'battery.max_soc': '最高 SOC', 'battery.charge_efficiency': '充电效率',
    'battery.discharge_efficiency': '放电效率', 'battery.degradation_per_kwh': '吞吐代理费',
    'tariff.offpeak': '谷价', 'tariff.flat': '平价', 'tariff.peak': '峰价', 'tariff.demand_per_kw': '月需量单价',
    'evaluation.start': '开始日期', 'evaluation.end': '结束日期', risk_margin_scale: '安全余量强度', stress: '压力情景', dataset_id: '数据源', protocol_id: '评估协议', 'tariff.prices': '自定义日内电价',
};
function draftDiff(config: Config, frozen?: Config) {
    if (!frozen)
        return [];
    const flatten = (value: unknown, prefix = ''): Record<string, unknown> => {
        if (value && typeof value === 'object' && !Array.isArray(value))
            return Object.assign({}, ...Object.entries(value).filter(([key]) => key !== 'idempotency_key').map(([key, next]) => flatten(next, prefix ? `${prefix}.${key}` : key)));
        return { [prefix]: value };
    };
    const normalize = (value: Config) => ({ ...value, risk_margin_scale: value.risk_margin_scale ?? 1, stress: value.stress || 'none', protocol_id: value.protocol_id ?? null, tariff: { ...value.tariff, prices: value.tariff.prices ?? null, demand_per_kw: value.tariff.demand_per_kw ?? 0 } });
    const before = flatten(normalize(frozen)), after = flatten(normalize(config));
    return Object.entries(after).filter(([key, value]) => labels[key] && JSON.stringify(value ?? null) !== JSON.stringify(before[key] ?? null)).map(([key, value]) => ({ key, label: labels[key], before: before[key], after: value }));
}
const display = (value: unknown) => value === null || value === undefined ? '未设置' : Array.isArray(value) ? `${value.length} 个价格点` : String(value);
export function Parameters({ config, frozen, dataset, working, onChange, onRun, onReset }: {
    config: Config;
    frozen?: Config;
    dataset?: Dataset;
    working: boolean;
    onChange: (config: Config) => void;
    onRun: () => Promise<boolean>;
    onReset: () => void;
}) {
    const [error, setError] = useState('');
    const [customPrices, setCustomPrices] = useState(config.tariff.prices?.join(', ') || '');
    const b = config.battery, t = config.tariff;
    const differences = draftDiff(config, frozen);
    const setBattery = (key: keyof Config['battery'], value: number) => onChange({ ...config, battery: { ...b, [key]: value } });
    const setTariff = (key: keyof Config['tariff'], value: number | number[] | null) => onChange({ ...config, tariff: { ...t, [key]: value } });
    async function submit() {
        const issue = validateConfig(config);
        if (issue) {
            setError(issue);
            return;
        }
        setError('');
        await onRun();
    }
    return <form className="parameters-form" onSubmit={event => { event.preventDefault(); void submit(); }}>
    <div className="draft-overview">
    <Badge tone={differences.length ? 'amber' : 'neutral'}>{differences.length ? `${differences.length} 处参数草稿变更` : '当前参数草稿'}</Badge>
    <button className="text-button" type="button" onClick={onReset}>
    <Icon name="refresh" size={14}/>恢复默认</button>
    </div>
    {differences.length > 0 && <details className="draft-diff" open>
        <summary>与本次冻结配置比较</summary>
        <table>
        <thead>
        <tr>
        <th>参数</th>
        <th>已计算</th>
        <th>草稿</th>
        </tr>
        </thead>
        <tbody>{differences.map(item => <tr key={item.key}>
            <td>{item.label}</td>
            <td>{display(item.before)}</td>
            <td>{display(item.after)}</td>
            </tr>)}</tbody>
        </table>
        <p>保存为草稿不会改写结果；运行后产生独立证据。</p>
        </details>}
    <fieldset>
    <legend>
    <span>01</span>评价范围</legend>
    <p className="field-help">{dataset?.name || config.dataset_id}</p>
    <div className="evaluation-shortcuts">
    <Button variant="secondary" onClick={() => onChange({ ...config, evaluation: { ...config.evaluation, end: config.evaluation.start } })}>单日快速演示</Button>{dataset?.default_evaluation && <Button variant="ghost" onClick={() => onChange({ ...config, evaluation: { start: dataset.default_evaluation!.test_start.slice(0, 10), end: dataset.default_evaluation!.test_end.slice(0, 10) } })}>使用协议完整区间</Button>}</div>
    <div className="form-grid">
    <label className="field">开始日期<input type="date" required min={dataset?.start.slice(0, 10)} max={dataset?.end.slice(0, 10)} value={config.evaluation.start} onChange={event => onChange({ ...config, evaluation: { ...config.evaluation, start: event.target.value } })}/>
    </label>
    <label className="field">结束日期<input type="date" required min={config.evaluation.start} max={dataset?.end.slice(0, 10)} value={config.evaluation.end} onChange={event => onChange({ ...config, evaluation: { ...config.evaluation, end: event.target.value } })}/>
    </label>
    </div>
    <p className="caption">需量费仅在原生 15 分钟数据且完整自然月覆盖时可完整核算。日期和协议由后端再次校验。</p>{config.protocol_id && <div className="protocol-label">冻结协议 <code>{config.protocol_id}</code>
        </div>}</fieldset>
    <fieldset>
    <legend>
    <span>02</span>储能边界</legend>
    <div className="form-grid">
      <NumberField label="额定容量" value={b.capacity_kwh} onChange={value => setBattery('capacity_kwh', value)} unit="kWh" min={.1}/>
      <NumberField label="最大充 / 放电功率" value={b.power_kw} onChange={value => setBattery('power_kw', value)} unit="kW" min={.1}/>
      <NumberField label="初始 SOC" value={b.initial_soc * 100} onChange={value => setBattery('initial_soc', value / 100)} unit="%" min={0} max={100}/>
      <NumberField label="最低 SOC" value={b.min_soc * 100} onChange={value => setBattery('min_soc', value / 100)} unit="%" min={0} max={99}/>
      <NumberField label="最高 SOC" value={b.max_soc * 100} onChange={value => setBattery('max_soc', value / 100)} unit="%" min={1} max={100}/>
      <NumberField label="吞吐衰减代理费" value={b.degradation_per_kwh} onChange={value => setBattery('degradation_per_kwh', value)} unit="元/kWh" min={0}/>
      <NumberField label="充电效率" value={b.charge_efficiency * 100} onChange={value => setBattery('charge_efficiency', value / 100)} unit="%" min={.1} max={100}/>
      <NumberField label="放电效率" value={b.discharge_efficiency * 100} onChange={value => setBattery('discharge_efficiency', value / 100)} unit="%" min={.1} max={100}/>
    </div>
    <div className="soc-window">
    <span>允许电量</span>
    <div>
    <i style={{ left: `${b.min_soc * 100}%`, width: `${(b.max_soc - b.min_soc) * 100}%` }}/>
    <b style={{ left: `${b.initial_soc * 100}%` }}/>
    </div>
    <strong>{number(b.min_soc * b.capacity_kwh)}—{number(b.max_soc * b.capacity_kwh)} kWh</strong>
    </div>
    <p className="caption">连续 SOC 与共同每日终端条件由求解器校验；不将初始电量耗尽当作收益。</p>
    </fieldset>
    <fieldset>
    <legend>
    <span>03</span>电价与完整月需量</legend>
    <div className="form-grid form-grid--three">
    <NumberField label="谷时电价" value={t.offpeak} onChange={value => setTariff('offpeak', value)} unit="元/kWh" min={0}/>
    <NumberField label="平时电价" value={t.flat} onChange={value => setTariff('flat', value)} unit="元/kWh" min={0}/>
    <NumberField label="峰时电价" value={t.peak} onChange={value => setTariff('peak', value)} unit="元/kWh" min={0}/>
    </div>
    <div className="tariff-strip">{Array.from({ length: 24 }, (_, hour) => <div key={hour} title={`${hour}:00 / ${t.peak_hours.includes(hour) ? t.peak : t.offpeak_hours.includes(hour) ? t.offpeak : t.flat} 元/kWh`}>
        <i className={t.peak_hours.includes(hour) ? 'peak' : t.offpeak_hours.includes(hour) ? 'offpeak' : 'flat'}/>
        <small>{hour % 6 === 0 ? String(hour).padStart(2, '0') : ''}</small>
        </div>)}</div>
    <NumberField label="完整月最大需量单价" value={t.demand_per_kw ?? 0} onChange={value => setTariff('demand_per_kw', value)} unit="元/kW·月" min={0}/>{!dataset?.demand_eligible && (t.demand_per_kw || 0) > 0 && <Notice tone="warning">当前数据未标明可核算 15 分钟完整月需量；后端可能返回“无法计算完整月账”。不将小时数据插值当作 15 分钟计量。</Notice>}<details className="custom-prices">
    <summary>自定义 24 / 96 个日内电价</summary>
    <textarea aria-label="日内电价序列" value={customPrices} onChange={event => setCustomPrices(event.target.value)} placeholder="使用逗号或空格分隔，24 个小时价格或 96 个 15 分钟价格"/>
    <div>
    <Button variant="secondary" onClick={() => { const prices = customPrices.split(/[\s,，]+/).filter(Boolean).map(Number); if (![24, 96].includes(prices.length) || prices.some(value => !Number.isFinite(value) || value < 0))
        setError('日内电价需要 24 或 96 个非负有限价格。');
    else {
        setError('');
        setTariff('prices', prices);
    } }}>应用价格序列</Button>
    <Button variant="ghost" onClick={() => { setCustomPrices(''); setTariff('prices', null); }}>使用峰平谷</Button>
    </div>
    </details>
    <p className="caption">电价均为明确情景假设，不代表源站点合同；购电能量费、需量费与吞吐代理分列。</p>
    </fieldset>
    <fieldset>
    <legend>
    <span>04</span>风险与压力条件</legend>
    <NumberField label="安全余量强度" value={(config.risk_margin_scale ?? 1) * 100} onChange={value => onChange({ ...config, risk_margin_scale: value / 100 })} unit="%" min={0} max={100}/>
    <label className="field">压力情景<select aria-label="压力情景" value={config.stress || 'none'} onChange={event => onChange({ ...config, stress: event.target.value })}>
    <option value="none">标准情景</option>
    <option value="load_up_20">实际负荷增加 20%</option>
    <option value="peak_price_up_20">峰价增加 20%</option>
    <option value="forecast_bias_up_20">预测偏高 20%</option>
    <option value="pv_drop_30">光伏下降 30%</option>
    </select>
    </label>
    <p className="caption">保留所有预定情景与负结果；光伏来自输入序列，不编造装机或收益。</p>
    </fieldset>
    {error && <Notice tone="danger">{error}</Notice>}
    <div className="drawer-sticky-action">
    <span>生成新的不可变运行<br />
    <small>CPU 计算 · 不发送设备指令</small>
    </span>
    <Button type="submit" disabled={working || dataset?.scope?.dispatch === false}>
    <Icon name="play" size={16}/>{working ? '计算进行中' : '运行当前草稿'}</Button>
    </div>
  </form>;
}
