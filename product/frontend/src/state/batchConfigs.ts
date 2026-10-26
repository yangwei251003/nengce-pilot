import type { Config, Dataset } from '../types';
import { clone } from '../api';

export function siteBatchConfigs(base: Config, datasets: Dataset[], selectedIds: string[], period: 'day' | 'protocol'): Config[] {
  return selectedIds.map(id => {
    const dataset = datasets.find(item => item.dataset_id === id);
    if (!dataset?.default_evaluation || dataset.scope?.dispatch === false || dataset.runtime_ready === false) throw new Error(`${dataset?.name || id} 不具备可调度的默认评估区间。`);
    const evaluation = dataset.default_evaluation;
    const start = evaluation.test_start.slice(0, 10);
    return {
      ...clone(base),
      dataset_id: id,
      evaluation: { start, end: period === 'day' ? start : evaluation.test_end.slice(0, 10) },
      protocol_id: evaluation.protocol_id || null,
    };
  });
}
