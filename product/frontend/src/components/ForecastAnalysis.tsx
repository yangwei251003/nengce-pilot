import { useState } from 'react';
import type { Result } from '../types';
import { Badge, Empty, KeyValue, modelName, number, Section } from '../ui';
export function ForecastAnalysis({ result }: {
    result?: Result;
}) {
    const [phase, setPhase] = useState<'validation' | 'replay'>('replay');
    if (!result)
        return <Empty title="预测对照等待计算">先固定日期与参数。模型选择只依据预先冻结的开发验证规则。</Empty>;
    const f = result.forecast;
    const models = phase === 'validation' ? f.validation : f.models;
    return <div className="page-stack">
    <div className="page-heading">
    <div>
    <span className="eyebrow">FORECAST & VALIDATION</span>
    <h1>预测分数与运行价值，分别检验</h1>
    <p>模型由训练期滚动验证选择；当前回放结果不用于临时换赢家。</p>
    </div>
    <Badge>{f.evaluation_role === 'historical_regression' ? '历史回归' : f.evaluation_role || '探索性回放'}</Badge>
    </div>
    <Section title={`实际使用 · ${modelName(f.selected_model)}`}>
    <p className="lead-copy">{f.selection_reason}</p>
    <div className="inline-facts">
    <KeyValue label="训练截止">{f.train_end}</KeyValue>
    <KeyValue label="回放相对周朴素 WAPE 改善">{number(f.improvement_vs_weekly_pct, 2)}%</KeyValue>
    <KeyValue label="学习预测费用增量">{number(result.learning_ablation?.incremental_savings, 2)} 元</KeyValue>
    </div>
    </Section>
    <Section title="同时间窗模型对照" action={<div className="segments">
        <button aria-pressed={phase === 'replay'} onClick={() => setPhase('replay')}>回放期</button>
        <button aria-pressed={phase === 'validation'} onClick={() => setPhase('validation')}>开发验证</button>
        </div>}>
      <div className="table-scroll">
    <table>
    <thead>
    <tr>
    <th>模型</th>
    <th>MAE / kW</th>
    <th>RMSE / kW</th>
    <th>WAPE / %</th>
    </tr>
    </thead>
    <tbody>{models.map(model => <tr key={model.name}>
        <th>{modelName(model.name)} {model.name === f.selected_model && <Badge tone="green">实际采用</Badge>}</th>
        <td>{number(model.mae_kw, 3)}</td>
        <td>{number(model.rmse_kw, 3)}</td>
        <td>{number(model.wape_pct, 2)}</td>
        </tr>)}</tbody>
    </table>
    </div>
    <p className="footnote">WAPE 越低越好。分数提升不必然带来费用下降；负值和失败案例保留。</p>
    </Section>
    {f.pv && <Section title={`光伏预测 · ${modelName(f.pv.selected_model)}`} eyebrow="PHOTOVOLTAIC FORECAST">
        <p className="lead-copy">{f.pv.selection_reason}</p>
        <div className="table-scroll">
        <table>
        <thead>
        <tr>
        <th>模型</th>
        <th>MAE / kW</th>
        <th>RMSE / kW</th>
        <th>WAPE / %</th>
        </tr>
        </thead>
        <tbody>{f.pv.models?.map(model => <tr key={model.name}>
            <th>{modelName(model.name)}</th>
            <td>{number(model.mae_kw, 3)}</td>
            <td>{number(model.rmse_kw, 3)}</td>
            <td>{number(model.wape_pct, 2)}</td>
            </tr>)}</tbody>
        </table>
        </div>
        <p className="footnote">经验区间覆盖率 {number(f.pv.interval_coverage_pct, 2)}%。模型回退按开发验证规则执行，不因当前回放成绩临时调整。</p>
        </Section>}
    <div className="analysis-grid">
    <Section title="信息可见性">
    <div className="feature-tags">{f.features.map(feature => <span key={feature}>{feature}</span>)}</div>{f.notes.map((note, index) => <p className="muted" key={index}>{note}</p>)}</Section>
    <Section title="冻结与复查">
    <details open>
    <summary>选择规则</summary>
    <pre>{JSON.stringify(f.selection_policy, null, 2)}</pre>
    </details>
    <details>
    <summary>滚动验证记录</summary>
    <pre>{JSON.stringify(f.rolling_validation, null, 2)}</pre>
    </details>
    <details>
    <summary>风险标定</summary>
    <pre>{JSON.stringify(f.risk_calibration, null, 2)}</pre>
    </details>
    </Section>
    </div>
  </div>;
}
