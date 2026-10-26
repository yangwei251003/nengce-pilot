import type { Config, Dataset, Result } from '../types';
import { Badge, Empty, ExportLinks, KeyValue, number } from '../ui';
export function EvidencePanel({ result, config, dataset }: {
    result?: Result;
    config?: Config;
    dataset?: Dataset;
}) {
    if (!result)
        return <Empty compact title="证据等待计算">成功运行会保存配置、结果、来源与校验信息。尚无结果时不会生成装饰性报告。</Empty>;
    const b2 = result.strategies.find(item => item.id === 'B2');
    return <div className="evidence-panel">
    <Badge>不可变运行 · {result.run_id}</Badge>
    <p>下载直接读取本次后端冻结产物，与图表使用同一份结果。</p>
    <ExportLinks runId={result.api_run_id || result.run_id}/>
    <hr />
    <h3>B2 物理约束检查</h3>
    <p className="caption">此处仅展示 B2；全部策略分别保存在原始 JSON 中。任务完成不等于所有策略或候选关卡通过。</p>
    <KeyValue label="比较有效">{b2?.comparison_valid ? '是' : '否'}</KeyValue>
    <KeyValue label="末状态误差">{number(b2?.terminal_error_kwh, 6)} kWh</KeyValue>
    <KeyValue label="最大 SOC 越界">{number(b2?.max_soc_violation_kwh, 6)} kWh</KeyValue>
    <KeyValue label="同时充放时段">{number(b2?.simultaneous_count, 0)}</KeyValue>
    <KeyValue label="电网越界">{number(b2?.grid_violation_kwh, 6)} kWh</KeyValue>
    <details open>
    <summary>本次冻结配置</summary>
    <pre>{JSON.stringify(result.config || config, null, 2)}</pre>
    </details>
    <details>
    <summary>数据来源与质量</summary>
    <pre>{JSON.stringify(result.dataset || dataset, null, 2)}</pre>
    </details>
    <details>
    <summary>复现与校验信息</summary>
    <pre>{JSON.stringify(result.reproducibility || result.artifacts, null, 2)}</pre>
    </details>
    <details>
    <summary>假设与限制</summary>
    <ul>{result.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </details>
  </div>;
}
