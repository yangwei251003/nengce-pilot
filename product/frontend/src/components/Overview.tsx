import type { Citation, Config, Dataset, Result } from '../types';
import { Icon } from '../icons';
import { Badge, Button, Empty, KeyValue, modelName, money, number, Section } from '../ui';
import { Timeline } from './Timeline';
export function Overview({ result, config, dataset, focus, onConfigure, onData, onEvidence, onAssistant, onForecast, onNotify }: {
    result?: Result;
    config: Config | null;
    dataset?: Dataset;
    focus?: Citation | null;
    onConfigure: () => void;
    onData: () => void;
    onEvidence: () => void;
    onAssistant: () => void;
    onForecast: () => void;
    onNotify: (message: string) => void;
}) {
    if (!result || !config)
        return <div className="overview-empty-layout">
    <Section title="先审查输入，再让计算给出判断" eyebrow="NEW ANALYSIS" className="start-surface">
      <div className="start-intro">
        <div>
        <Badge tone="green">单站光储 · 本机计算</Badge>
        <h2>准备一份可复算的储能方案</h2>
        <p>从来源明确的负荷开始，对照预测、检查执行风险，再核对完整账单。</p>
        </div>
        <div className="start-initial">N<span>03</span>
        </div>
        </div>
      <div className="empty-plot" aria-label="尚无计算结果，不显示示例曲线">
        <div className="empty-plot-grid"/>
        <div>
        <Icon name="chart" size={28}/>
        <strong>主图等待真实计算</strong>
        <p>负荷、光伏、充放电与 SOC 将在同一时段联动。</p>
        </div>
        </div>
      <div className="start-actions">
        <Button onClick={onConfigure}>
        <Icon name="sliders" size={16}/>检查参数并运行</Button>
        <Button variant="secondary" onClick={onData}>选择其他数据<Icon name="arrow" size={15}/>
        </Button>
        </div>
    </Section>
    <aside className="analysis-rail">
        <Section title="当前数据" eyebrow="INPUT CONTEXT">
        <h3 className="dataset-name">{dataset?.name || '等待读取数据目录'}</h3>
        <KeyValue label="原生/分析间隔">{dataset?.interval_minutes ? `${dataset.interval_minutes} 分钟` : '待核验'}</KeyValue>
        <KeyValue label="数据量">{number(dataset?.rows ?? dataset?.rows_hourly, 0)} 条</KeyValue>
        <KeyValue label="光伏序列">{dataset?.pv_available === true ? '已提供' : dataset?.pv_available === false ? '未提供' : '待核验'}</KeyValue>
        <KeyValue label="时间语义">{dataset?.timezone || '待读取'}</KeyValue>
        <button className="text-button rail-link" onClick={onData}>审查来源与质量<Icon name="arrow" size={14}/>
        </button>
        </Section>
      <Section title="计算后，你会得到" className="next-steps">
        <ol>
        <li>
        <span>01</span>
        <div>
        <strong>公平的预测对照</strong>
        <p>学习模型和简单基线都保留。</p>
        </div>
        </li>
        <li>
        <span>02</span>
        <div>
        <strong>可定位的执行风险</strong>
        <p>计划、裁剪和末端电量分开看。</p>
        </div>
        </li>
        <li>
        <span>03</span>
        <div>
        <strong>可复算的费用证据</strong>
        <p>购电、需量与吞吐代理分列。</p>
        </div>
        </li>
        </ol>
        </Section>
    </aside>
  </div>;
    const chosen = result.strategies.find(item => item.id === (result.summary.recommended_strategy || 'B2')) || result.strategies.find(item => item.id === 'B2')!;
    const baseline = result.strategies.find(item => item.id === 'B0');
    const valid = result.summary.comparison_valid;
    const savings = chosen.savings_vs_b0;
    const headline = result.summary.recommended_strategy === null ? '尚无可推荐的完整方案' : chosen.total_cost === null ? '尚不能计算完整月账' : !valid ? '本次比较需要复核' : savings !== null && savings > 1e-6 ? '在当前情景下，运行费用下降' : savings !== null && savings < -1e-6 ? '在当前情景下，运行费用增加' : '本次情景没有产生净节费';
    const risks = result.risk_ablations || (result.risk_ablation ? [result.risk_ablation] : []);
    const learning = result.learning_ablation || result.ablation;
    return <>
    <div className="result-heading">
    <div>
    <span className="eyebrow">RUN / {result.run_id.slice(-8).toUpperCase()}</span>
    <h1>{headline}</h1>
    </div>
    <div className="result-heading-tags">
    <Badge tone={valid ? 'green' : 'red'}>{valid ? '物理比较有效' : '比较无效'}</Badge>
    <Badge>{result.summary.interval_minutes || result.dataset?.interval_minutes || 60} 分钟步长</Badge>
    </div>
    </div>
    <>{result.summary.recommendation_reason && <p className="recommendation-reason">{result.summary.recommendation_reason}{result.summary.recommended_strategy === null && ' · 以下 B2 仅供诊断'}</p>}</>
    <>{typeof learning?.incremental_savings === 'number' && learning.incremental_savings < -1e-6 && <p className="learning-caveat"><Icon name="info" size={15}/>学习预测增量为 ¥ {money(learning.incremental_savings)}（L1 相对 N1）。本次储能节费不能全部归因于 AI。</p>}</>
    <div className="summary-grid">
      <div className="summary-cell">
    <span>{chosen.id} 实际回放总费用</span>
    <strong>{chosen.total_cost === null ? '待完整月核算' : `¥ ${money(chosen.total_cost)}`}</strong>
    <small>{chosen.total_cost === null ? `已知成本小计 ¥ ${money(chosen.known_cost_subtotal)}，不可作完整账单` : `无储能基线 ¥ ${money(baseline?.total_cost)}`}</small>
    </div>
      <div className={`summary-cell ${typeof savings === 'number' && savings < -1e-6 ? 'text-risk' : typeof savings === 'number' && savings > 1e-6 ? 'text-green' : ''}`}>
    <span>相对无储能净节费</span>
    <strong>{savings === null ? '—' : `¥ ${money(savings)}`}</strong>
    <small>{number(chosen.savings_pct, 2)}% · 不等于学习模型贡献</small>
    </div>
      <div className="summary-cell">
    <span>实际购电峰值</span>
    <strong>{number(chosen.peak_grid_kw)} <em>kW</em>
    </strong>
    <small>计量间隔与整月覆盖决定需量可计费性</small>
    </div>
      <div className={`summary-cell ${(chosen.clip_kwh || 0) > 1e-6 ? 'text-amber' : ''}`}>
    <span>{chosen.id} 计划动作裁剪</span>
    <strong>{number(chosen.clip_kwh)} <em>kWh</em>
    </strong>
    <small>安全执行后的零越界不代表计划完整执行</small>
    </div>
    </div>
    <div className="analysis-layout">
      <div className="analysis-main">
    <Timeline key={result.run_id} result={result} config={config} focus={focus} onNotify={onNotify}/>
        <Section title="学习模型的增量，单独核对" eyebrow="ATTRIBUTION" action={<button className="text-button" onClick={onForecast}>预测验证<Icon name="arrow" size={14}/>
        </button>} className="learning-brief">
    <div>
    <span>HGB 相对周朴素 WAPE 改善</span>
    <strong className={(result.forecast.improvement_vs_weekly_pct || 0) < 0 ? 'text-risk' : ''}>{number(result.forecast.improvement_vs_weekly_pct, 2)}%</strong>
    <small>负值表示更差；按当前评估身份解读</small>
    </div>
    <div>
    <span>学习模型 + 同优化器增量</span>
    <strong className={(learning?.incremental_savings || 0) < 0 ? 'text-risk' : 'text-green'}>¥ {money(learning?.incremental_savings)}</strong>
    <small>{learning?.candidate || 'L1'} 对比 {learning?.baseline || 'N1'} · 仅为该情景下预测增量</small>
    </div>
    </Section>
      </div>
      <aside className="analysis-rail">
        <Section title="本次判断" eyebrow="READ THE RESULT" className="decision-card">
    <div className="decision-model">
    <span className="round-icon">
    <Icon name="spark" size={20}/>
    </span>
    <div>
    <small>实际选定预测</small>
    <strong>{modelName(result.forecast.selected_model)}</strong>
    </div>
    </div>
    <p>{result.forecast.selection_reason || '按开发验证规则选型，最终评价结果保留。'}</p>
    <Badge tone="amber">{result.forecast.evaluation_role === 'historical_regression' ? '公开历史回归' : '评估身份以冻结协议为准'}</Badge>
    <p className="caption">{result.forecast.evaluation_role === 'historical_regression' ? '2018 年 12 月结果已公开，不是新盲测。' : '新数据的独立性须以首次评估前冻结的协议与哈希为据。'}</p>
    <button className="text-button rail-link" onClick={onAssistant}>
    <Icon name="spark" size={15}/>问助手：这份结果说明什么？</button>
    </Section>
        <Section title="风险措施与代价" eyebrow="CANDIDATE GATE" className="risk-candidates">{risks.length ? risks.map(risk => <div className="candidate" key={risk.candidate}>
        <div>
        <strong>{risk.candidate} · {risk.candidate === 'R2' ? '状态可达策略' : '误差安全余量'}</strong>
        <Badge tone={risk.predefined_gate_passed ? 'green' : 'amber'}>{risk.predefined_gate_passed ? '关卡通过' : '关卡未过'}</Badge>
        </div>
        <KeyValue label="裁剪减少">{number(risk.clip_reduction_kwh, 2)} kWh</KeyValue>
        <KeyValue label="费用增加">
        <span className={(risk.cost_increase || 0) > 0 ? 'text-risk' : ''}>¥ {money(risk.cost_increase)}</span>
        </KeyValue>
        <p className="caption">保留节费 {number(risk.retained_savings_pct, 2)}% · 吞吐比 {number(typeof risk.throughput_ratio === 'number' ? risk.throughput_ratio * 100 : null)}%</p>{(risk.margin_plan_failures || 0) > 0 && <p className="caption text-amber">余量失败 {risk.margin_plan_failures} 次 / 原约束降级 {risk.fallback_count ?? '—'} 次</p>}</div>) : <p className="caption">当前结果没有风险消融产物。</p>}<p className="caption">物理约束有效、候选通过和任务完成分别判断；不自动切换赢家。</p>
    </Section>
        <Section title="本次计算证据" eyebrow="REPRODUCIBLE">
    <KeyValue label="回放区间">{result.summary.period_start.slice(0, 10)}<br />— {result.summary.period_end.slice(0, 10)}</KeyValue>
    <KeyValue label="实际时段">{number(result.summary.intervals ?? result.series.length, 0)} 个</KeyValue>
    <KeyValue label="机器耗时">{number(result.summary.elapsed_seconds)} s</KeyValue>
    <button className="text-button rail-link" onClick={onEvidence}>查看配置、来源与导出<Icon name="arrow" size={14}/>
    </button>
    </Section>
      </aside>
    </div>
    {(result.summary.warnings || []).length > 0 && <details className="warnings-summary">
        <summary>
        <Icon name="info" size={16}/>{result.summary.warnings.length} 条运行说明与边界<span>展开原始说明</span>
        </summary>
        <ul>{result.summary.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
        </details>}
  </>;
}
