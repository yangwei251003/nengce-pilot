import { useEffect, useState } from 'react';
import { request } from '../api';
import { Badge, Notice, number } from '../ui';
type Detection = {
    id: string;
    label: string;
    count: number;
    threshold: unknown;
    handling: string;
    examples_truncated?: boolean;
    examples: {
        timestamp?: string;
        load_kw?: number;
        source_row?: number;
        source_timestamp?: string;
        delta_kw?: number;
        source_row_start?: number;
        source_row_end?: number;
    }[];
};
export function QualityDetails({ datasetId, totalRows }: {
    datasetId: string;
    totalRows?: number;
}) {
    const [detections, setDetections] = useState<Detection[] | null>(null);
    const [error, setError] = useState('');
    const [quality, setQuality] = useState<Record<string, unknown>>({});
    useEffect(() => {
        let cancelled = false;
        setDetections(null);
        setError('');
        request<{
            detections: Detection[];
            quality?: Record<string, unknown>;
        }>(`/datasets/${encodeURIComponent(datasetId)}/quality`).then(value => { if (!cancelled)
            { setDetections(value.detections); setQuality(value.quality || {}); } }).catch(issue => { if (!cancelled)
            setError(String(issue)); });
        return () => { cancelled = true; };
    }, [datasetId]);
    return <div className="quality-details">
    <h3>异常线索与原始行</h3>
    <div className="quality-counts"><span>数值有效记录 <strong>{number(typeof totalRows === 'number' && typeof quality.missing === 'number' ? totalRows - quality.missing : null, 0)}</strong></span><span>无效 / 缺测 <strong>{number(quality.missing, 0)}</strong></span><span>未观测 <strong>{number(quality.unobserved, 0)}</strong></span></div>
    <p className="caption">跳变和连续零值是描述性审查线索，不自动判定设备故障。</p>{error && <Notice tone="danger">质量明细读取失败：{error}</Notice>}{!detections && !error && <p role="status">正在读取本机质量报告…</p>}{detections?.map(item => <details key={item.id}>
        <summary>{item.label} <Badge tone={item.count ? 'amber' : 'green'}>{number(item.count, 0)} 处</Badge>
        </summary>
        <p className="caption">处理：{item.handling} · 阈值：{typeof item.threshold === 'object' ? JSON.stringify(item.threshold) : String(item.threshold ?? '—')}</p>{item.examples.length > 0 ? <div className="table-scroll">
            <table>
            <thead>
            <tr>
            <th>时段</th>
            <th>负荷 / kW</th>
            <th>变化 / kW</th>
            <th>原始行</th>
            <th>原始时间</th>
            </tr>
            </thead>
            <tbody>{item.examples.map((sample, index) => <tr key={index}>
                <td>{sample.timestamp || '—'}</td>
                <td>{number(sample.load_kw, 2)}</td>
                <td>{number(sample.delta_kw, 2)}</td>
                <td>{sample.source_row ?? (sample.source_row_start ? `${sample.source_row_start}—${sample.source_row_end}` : '—')}</td>
                <td>{sample.source_timestamp || '—'}</td>
                </tr>)}</tbody>
            </table>
            </div> : <p className="caption">没有提供命中样例。</p>}{item.examples_truncated && <p className="caption">这里只展示前 100 条样例；命中总数未截断。</p>}</details>)}</div>;
}
