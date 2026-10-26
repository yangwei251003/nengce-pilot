import { useEffect, useState } from 'react';
import type { Citation, Result } from '../types';
import { Badge, Empty, ExportLinks, KeyValue, money, Notice, number, Section, strategyName } from '../ui';
export function CostAnalysis({ result, focus }: {
    result?: Result;
    focus?: Citation | null;
}) {
    const [oracle, setOracle] = useState(false);
    const [selected, setSelected] = useState('B2');
    useEffect(() => { setSelected(result?.summary.recommended_strategy || 'B2'); }, [result?.run_id]);
    useEffect(() => { if (focus?.strategy && result?.strategies.some(item => item.id === focus.strategy)) { setSelected(focus.strategy); if (focus.strategy === 'O1') setOracle(true); } }, [focus, result?.run_id]);
    if (!result)
        return <Empty title="费用对照等待计算">运行后会在同一执行条件下，对照固定规则、朴素预测、学习模型和风险候选。</Empty>;
    const strategies = result.strategies.filter(item => oracle || item.id !== 'O1');
    const current = result.strategies.find(item => item.id === selected) || result.strategies[0];
    const maximum = Math.max(1, ...strategies.map(item => (item.energy_cost || 0) + (item.demand_cost || 0) + (item.degradation_cost || 0)));
    const bills = result.monthly_bills?.[current.id] || current.monthly_bills || [];
    const learning = result.learning_ablation;
    return <div className="page-stack">
    <div className="page-heading">
    <div>
    <span className="eyebrow">COST ATTRIBUTION</span>
    <h1>每一笔费用，都有边界</h1>
    <p>购电能量费、月度需量费与 AC 吞吐代理分开列示。以下均为实际执行回放。</p>
    </div>
    <ExportLinks runId={result.api_run_id || result.run_id}/>
    </div>
    {!result.summary.comparison_valid && <Notice tone="warning" title="本次比较不可直接用于收益结论">请检查终端状态、数据覆盖与需量计费范围。缺少完整月账时，仅显示已知费用小计。</Notice>}
    <Section title="策略费用构成" action={<label className="check-label">
        <input type="checkbox" checked={oracle} onChange={event => setOracle(event.target.checked)}/>显示完美预知诊断</label>}>
      <div className="cost-legend">
    <span>
    <i className="swatch energy"/>能量费</span>
    <span>
    <i className="swatch demand"/>需量费</span>
    <span>
    <i className="swatch wear"/>吞吐代理</span>
    </div>
      <div className="cost-bars">{strategies.map(item => <button key={item.id} className={`cost-row ${current.id === item.id ? 'is-selected' : ''}`} onClick={() => setSelected(item.id)} aria-label={`查看${strategyName(item.id)}费用`}>
        <span className="cost-label">
        <b>{item.id}</b>{strategyName(item.id)}</span>
        <span className="cost-track">{[['energy', item.energy_cost], ['demand', item.demand_cost], ['wear', item.degradation_cost]].map(([name, value]) => <i key={String(name)} className={String(name)} style={{ width: `${typeof value === 'number' ? Math.max(0, value) / maximum * 100 : 0}%` }}/>)}</span>
        <span className="cost-value">{item.total_cost === null ? '完整月账不可用' : `¥ ${money(item.total_cost)}`}<small className={typeof item.savings_pct === 'number' && item.savings_pct < 0 ? 'negative' : ''}>{item.savings_pct === null ? '不可比' : `节费 ${number(item.savings_pct, 2)}%`}</small>
        </span>
      </button>)}</div>
      <p className="footnote">完美预知使用未来实测值，仅提供诊断上界。图条仅展示返回的费用构成，不替代账单。</p>
    </Section>
    <div className="analysis-grid">
      <Section title={`${current.id} · ${strategyName(current.id)}`} action={<Badge tone={current.comparison_valid ? 'green' : 'amber'}>{current.comparison_valid ? '物理比较有效' : '覆盖不足 / 不可比'}</Badge>}>
        <div className="ledger">
    <KeyValue label="实际购电能量费">¥ {money(current.energy_cost)}</KeyValue>
    <KeyValue label={(result.config?.tariff.demand_per_kw || 0) === 0 ? '需量费（未启用）' : '完整月需量费'}>{current.demand_cost === null ? '无法计算完整月账' : `¥ ${money(current.demand_cost)}`}</KeyValue>
    <KeyValue label="AC 吞吐衰减代理">¥ {money(current.degradation_cost)}</KeyValue>
    <KeyValue label={current.total_cost === null ? '已知费用小计' : '回放总费用'}>¥ {money(current.total_cost ?? current.known_cost_subtotal)}</KeyValue>
    <KeyValue label="相对无储能节费">¥ {money(current.savings_vs_b0)}</KeyValue>
    </div>
        <details>
    <summary>计划、裁剪与末状态</summary>
    <div className="ledger">
    <KeyValue label="预测计划费用">¥ {money(current.forecast_plan_cost)}</KeyValue>
    <KeyValue label="计划与回放费用差">¥ {money(current.plan_replay_gap)}</KeyValue>
    <KeyValue label="累计动作裁剪">{number(current.clip_kwh, 2)} kWh</KeyValue>
    <KeyValue label="末 SOC 误差">{number(current.terminal_error_kwh, 4)} kWh</KeyValue>
    <KeyValue label="终端修复量">{number(current.terminal_repair_kwh, 2)} kWh</KeyValue>
    <KeyValue label="弃光">{number(current.curtailment_kwh, 2)} kWh</KeyValue>
    </div>
    <p className="footnote">计划差同时包含预测与实测负荷差异，不能解释为裁剪损失。</p>
    </details>
      </Section>
      <Section title="增量归因" eyebrow="KEEP THE BASELINES">
        <div className="attribution">
    <span className="index">01</span>
    <div>
    <h3>电池与固定规则</h3>
    <p>B1 相对 B0：¥ {money(result.strategies.find(item => item.id === 'B1')?.savings_vs_b0)}</p>
    <small>包含储能本身与峰谷规则的效果。</small>
    </div>
    </div>
        <div className="attribution">
    <span className="index">02</span>
    <div>
    <h3>优化策略增量</h3>
    <p>N1 相对 B1：{(() => { const a = result.strategies.find(item => item.id === 'B1')?.total_cost; const b = result.strategies.find(item => item.id === 'N1')?.total_cost; return a != null && b != null ? `¥ ${money(a - b)}` : '不可比'; })()}</p>
    <small>同电池和计费条件下的执行费用差。</small>
    </div>
    </div>
        <div className="attribution">
    <span className="index">03</span>
    <div>
    <h3>学习预测增量</h3>
    <p>L1 相对 N1：¥ {money(learning?.incremental_savings)}</p>
    <small>{learning ? (learning.comparison_valid ? '同优化器、同物理边界；负值表示学习模型没有带来额外节费。' : '该对照未通过可比性检查，不能据此归因收益。') : '同优化器对照结果尚未提供。'}</small>
    </div>
    </div>
        <p className="footnote">三段归因链终点为 L1；B2 是开发验证选定策略，可能回退。此处不推算软件愿付价、电池投资回报或真实寿命收益。</p>
      </Section>
    </div>
    <Section title="月账明细" action={<Badge>{current.id}</Badge>}>
      {bills.length ? <div className="table-scroll">
        <table>
        <thead>
        <tr>
        <th>月份</th>
        <th>覆盖</th>
        <th>能量费 / 元</th>
        <th>需量费 / 元</th>
        <th>电费 / 元</th>
        <th>吞吐代理 / 元</th>
        <th>总费用 / 元</th>
        </tr>
        </thead>
        <tbody>{bills.map((bill, index) => <tr key={index}>
            <th>{String(bill.month)}</th>
            <td>{bill.complete_observed_month ? '完整观测月' : '非完整月'}</td>
            <td>{money(bill.energy_cost)}</td>
            <td>{money(bill.demand_cost)}</td>
            <td>{money(bill.utility_bill)}</td>
            <td>{money(bill.degradation_cost)}</td>
            <td>{money(bill.total_cost)}</td>
            </tr>)}</tbody>
        </table>
        </div> : <p className="muted">本次产物未提供月账。以当前运行的费用口径为准。</p>}
      <p className="footnote">只有原生 15 分钟且完整观测月份，才支持本项目定义的月最大需量。价格为示例假设。</p>
    </Section>
  </div>;
}
