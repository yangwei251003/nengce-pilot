import { useEffect, useMemo, useRef, useState } from 'react';
import type { Citation, Config, Result, Tick } from '../types';
import { Icon } from '../icons';
import { Badge, number, Section, strategyName } from '../ui';
const color = { load: '#78816e', grid: '#246546', forecast: '#718044', pv: '#a57720', charge: '#748d48', discharge: '#327858' };
export function Timeline({ result, config, focus, onNotify }: {
    result: Result;
    config: Config;
    focus?: Citation | null;
    onNotify: (message: string) => void;
}) {
    const chartContainer = useRef<HTMLDivElement>(null);
    const [chartWidth, setChartWidth] = useState(960);
    useEffect(() => {
        const node = chartContainer.current;
        if (!node || typeof ResizeObserver === 'undefined') return;
        const observer = new ResizeObserver(entries => setChartWidth(Math.max(280, Math.round(entries[0].contentRect.width))));
        observer.observe(node);
        return () => observer.disconnect();
    }, []);
    const days = useMemo(() => [...new Set(result.series.map(row => row.timestamp.slice(0, 10)))], [result.run_id]);
    const [day, setDay] = useState(days[0] || '');
    const [strategy, setStrategy] = useState(result.summary.recommended_strategy || 'B2');
    const [index, setIndex] = useState(0);
    const [showForecast, setShowForecast] = useState(true);
    const [showPV, setShowPV] = useState(true);
    const [showOracle, setShowOracle] = useState(false);
    useEffect(() => { setDay(days[0] || ''); setIndex(0); setStrategy(result.summary.recommended_strategy || 'B2'); }, [result.run_id]);
    useEffect(() => {
        if (!focus)
            return;
        if (focus.strategy && result.strategies.some(item => item.id === focus.strategy))
            setStrategy(focus.strategy);
        if (focus.timestamp) {
            const date = focus.timestamp.slice(0, 10);
            if (days.includes(date)) {
                setDay(date);
                const rows = result.series.filter(row => row.timestamp.startsWith(date));
                const found = rows.findIndex(row => row.timestamp === focus.timestamp);
                setIndex(Math.max(0, found));
            }
        }
    }, [focus, result.run_id]);
    const rows = useMemo(() => result.series.filter(row => row.timestamp.startsWith(day)), [result.run_id, day]);
    const selectedIndex = Math.max(0, Math.min(index, rows.length - 1));
    const current = rows[selectedIndex];
    const state = current?.strategies[strategy];
    const hasPV = result.dataset?.pv_available === true || result.series.some(row => (row.pv_kw || 0) > 0);
    const width = chartWidth, height = 474, left = 48, right = 15, plotWidth = width - left - right;
    const x = (position: number) => left + plotWidth * position / Math.max(1, rows.length - 1);
    const maxPower = Math.max(1, ...rows.flatMap(row => [row.actual_kw, row.forecast_kw, row.pv_kw || 0, row.pv_forecast_kw || 0, row.strategies[strategy]?.grid_kw || 0])) * 1.12;
    const y = (value: number) => 208 - value / maxPower * 168;
    const line = (pick: (row: Tick) => number) => rows.map((row, position) => `${position ? 'L' : 'M'} ${x(position).toFixed(2)},${y(pick(row)).toFixed(2)}`).join(' ');
    const socPath = rows.map((row, position) => `${position ? 'L' : 'M'} ${x(position)},${446 - (row.strategies[strategy]?.soc_kwh || 0) / config.battery.capacity_kwh * 60}`).join(' ');
    const batteryPower = Math.max(1, config.battery.power_kw);
    const maxPrice = Math.max(...rows.map(row => row.price), 0);
    const minPrice = rows.length ? Math.min(...rows.map(row => row.price)) : 0;
    const barWidth = Math.max(2, plotWidth / Math.max(1, rows.length) - 2);
    const dailyRisk = days.map(date => ({ date, clip: result.series.filter(row => row.timestamp.startsWith(date)).reduce((sum, row) => sum + (row.strategies[strategy]?.clip_kwh || 0), 0) }));
    const maximumRisk = Math.max(1, ...dailyRisk.map(item => item.clip));
    function locateMaximum() {
        const candidate = result.series.reduce((first, next) => (next.strategies[strategy]?.clip_kwh || 0) > (first.strategies[strategy]?.clip_kwh || 0) ? next : first, result.series[0]);
        if (!candidate || (candidate.strategies[strategy]?.clip_kwh || 0) < 1e-6) {
            onNotify(`${strategy} 本次运行未报告动作裁剪。`);
            return;
        }
        const nextDay = candidate.timestamp.slice(0, 10);
        setDay(nextDay);
        setIndex(result.series.filter(row => row.timestamp.startsWith(nextDay)).findIndex(row => row.timestamp === candidate.timestamp));
    }
    return <Section title="计划与实际，在同一条时间线上" eyebrow="DISPATCH / INTERVAL REPLAY" className="timeline" id="timeline" action={<div className="timeline-controls">
    <label>
        <span className="sr-only">选择回放策略</span>
        <select aria-label="选择回放策略" value={strategy} onChange={event => setStrategy(event.target.value)}>{result.strategies.filter(item => item.id !== 'O1').map(item => <option key={item.id} value={item.id}>{item.id} · {strategyName(item.id)}</option>)}</select>
        </label>
    <label>
        <span className="sr-only">选择回放日期</span>
        <input aria-label="选择回放日期" type="date" min={days[0]} max={days[days.length - 1]} value={day} onChange={event => { if (days.includes(event.target.value)) {
            setDay(event.target.value);
            setIndex(0);
        } }}/>
        </label>
  </div>}>
    <div className="chart-legend">
      <span>
    <i style={{ background: color.load }}/>实际负荷</span>
      <span>
    <i style={{ background: color.grid }}/>{strategy} 电网购电</span>
      <button aria-pressed={showForecast} onClick={() => setShowForecast(value => !value)} className={!showForecast ? 'legend-muted' : ''}>
    <i className="dashed" style={{ borderColor: color.forecast }}/>负荷预测</button>
      {hasPV && <button aria-pressed={showPV} onClick={() => setShowPV(value => !value)} className={!showPV ? 'legend-muted' : ''}>
        <i style={{ background: color.pv }}/>光伏</button>}
      <label className="oracle-toggle">
    <input type="checkbox" checked={showOracle} onChange={event => setShowOracle(event.target.checked)}/>事后参照</label>
    </div>
    <div ref={chartContainer} className="chart-scroll" tabIndex={0} aria-label="自适应时序图；下方提供可读数值">
      <svg className="time-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${day} ${strategy} 负荷、光伏、购电、充放电及 SOC 联动图`} onPointerMove={event => {
            const bounds = event.currentTarget.getBoundingClientRect();
            setIndex(Math.max(0, Math.min(rows.length - 1, Math.round(((event.clientX - bounds.left) / bounds.width * width - left) / plotWidth * (rows.length - 1)))));
        }}>
        <defs>
    <linearGradient id="grid-area-v3" x1="0" x2="0" y1="0" y2="1">
    <stop offset="0" stopColor={color.grid} stopOpacity=".09"/>
    <stop offset="1" stopColor={color.grid} stopOpacity="0"/>
    </linearGradient>
    </defs>
        {maxPrice > minPrice && rows.map((row, position) => row.price === maxPrice && <rect key={`price-${position}`} x={Math.max(left, x(position) - barWidth / 2)} y={38} width={barWidth + 2} height={170} fill="#ead3a0" opacity=".16"/>)}
        {[0, .25, .5, .75, 1].map(fraction => <g key={fraction}>
        <line x1={left} y1={y(maxPower * fraction)} x2={width - right} y2={y(maxPower * fraction)} stroke="#e1e6dc" strokeDasharray="3 5"/>
        <text x={left - 10} y={y(maxPower * fraction) + 4} textAnchor="end" className="chart-axis">{number(maxPower * fraction, maxPower < 10 ? 2 : 0)}</text>
        </g>)}
        <text x={left} y={20} className="chart-track-label">功率 / kW</text>
        {rows.length > 0 && <path d={`${line(row => row.strategies[strategy]?.grid_kw || 0)} L ${x(rows.length - 1)},208 L ${left},208 Z`} fill="url(#grid-area-v3)"/>}
        <path d={line(row => row.actual_kw)} fill="none" stroke={color.load} strokeWidth="2"/>
        {hasPV && showPV && <path d={line(row => row.pv_kw || 0)} fill="none" stroke={color.pv} strokeWidth="2"/>}
        {showForecast && <path d={line(row => row.forecast_kw)} fill="none" stroke={color.forecast} strokeWidth="2" strokeDasharray="5 5"/>}
        {hasPV && showPV && showForecast && <path d={line(row => row.pv_forecast_kw || 0)} fill="none" stroke={color.pv} strokeWidth="1.7" strokeDasharray="3 4"/>}
        <path d={line(row => row.strategies[strategy]?.grid_kw || 0)} fill="none" stroke={color.grid} strokeWidth="2.5" strokeLinejoin="round"/>
        {showOracle && <path d={line(row => row.strategies.O1?.grid_kw || 0)} fill="none" stroke="#a77b59" strokeWidth="1.8" strokeDasharray="2 4"/>}
        <line x1={left} y1={238} x2={width - right} y2={238} stroke="#e5e9df"/>
        <text x={left} y={261} className="chart-track-label">充电 + / 放电 − · kW</text>
        <>{[-1, 0, 1].map(fraction => <text key={fraction} x={left - 10} y={299 - fraction * 28 + 4} textAnchor="end" className="chart-axis">{fraction > 0 ? '+' : ''}{number(fraction * config.battery.power_kw, 0)}</text>)}</>
        <line x1={left} y1={299} x2={width - right} y2={299} stroke="#dce3d4"/>
        {rows.map((row, position) => {
            const point = row.strategies[strategy];
            if (!point)
                return null;
            const charge = point.charge_kw / batteryPower * 28, discharge = point.discharge_kw / batteryPower * 28;
            return <g key={`battery-${position}`}>
            <rect x={x(position) - barWidth / 2} y={299 - charge} width={barWidth} height={charge} rx="1" fill={color.charge}/>
            <rect x={x(position) - barWidth / 2} y={299} width={barWidth} height={discharge} rx="1" fill={color.discharge}/>
            </g>;
        })}
        <line x1={left} y1={342} x2={width - right} y2={342} stroke="#e5e9df"/>
        <text x={left} y={367} className="chart-track-label">SOC / %</text>
        {[0, 50, 100].map(value => <text key={value} x={left - 10} y={446 - value / 100 * 60 + 4} textAnchor="end" className="chart-axis">{value}</text>)}
        <line x1={left} y1={446 - config.battery.min_soc * 60} x2={width - right} y2={446 - config.battery.min_soc * 60} stroke="#cbd9bd" strokeDasharray="3 4"/>
        <line x1={left} y1={446 - config.battery.max_soc * 60} x2={width - right} y2={446 - config.battery.max_soc * 60} stroke="#cbd9bd" strokeDasharray="3 4"/>
        <path d={socPath} fill="none" stroke="#718c45" strokeWidth="2"/>
        {rows.map((row, position) => (position === 0 || row.timestamp.slice(14, 16) === '00' && Number(row.timestamp.slice(11, 13)) % 6 === 0 || position === rows.length - 1) && <text key={`time-${position}`} x={x(position)} y={471} textAnchor={position === 0 ? 'start' : position === rows.length - 1 ? 'end' : 'middle'} className="chart-axis">{row.timestamp.slice(11, 16)}</text>)}
        {current && <g>
        <line x1={x(selectedIndex)} y1={36} x2={x(selectedIndex)} y2={449} stroke="#8e9e7e" strokeDasharray="3 4"/>
        <circle cx={x(selectedIndex)} cy={y(state?.grid_kw || 0)} r="4" fill="#fffefa" stroke={color.grid} strokeWidth="2"/>
        </g>}
      </svg>
    </div>
    <label className="hour-slider">
    <span className="sr-only">选择时段</span>
    <input type="range" aria-label="选择时段" min={0} max={Math.max(0, rows.length - 1)} value={selectedIndex} onChange={event => setIndex(Number(event.target.value))}/>
    </label>
    <div className="timeline-readout" aria-live="off">
      <div>
    <span>选中时段</span>
    <strong>{current?.timestamp.slice(11, 16) || '—'}</strong>
    <small>{day}</small>
    </div>
      <div>
    <span>实际负荷</span>
    <strong>{number(current?.actual_kw)} <small>kW</small>
    </strong>
    </div>
      {hasPV && <div>
        <span>光伏出力</span>
        <strong>{number(current?.pv_kw)} <small>kW</small>
        </strong>
        </div>}
      <div>
    <span>{strategy} 充 / 放</span>
    <strong>{number(state?.charge_kw)} / {number(state?.discharge_kw)} <small>kW</small>
    </strong>
    </div>
      <div>
    <span>执行后 SOC</span>
    <strong>{number(state ? state.soc_kwh / config.battery.capacity_kwh * 100 : null)}<small>%</small>
    </strong>
    </div>
      <div className={(state?.clip_kwh || 0) > 1e-6 ? 'text-risk' : ''}>
    <span>动作裁剪</span>
    <strong>{number(state?.clip_kwh, 2)} <small>kWh</small>
    </strong>
    </div>
    </div>
    <div className="day-risk-head">
    <div>
    <strong>每日风险定位</strong>
    <span>颜色按 {strategy} 当日裁剪量显示</span>
    </div>
    <button className="text-button" onClick={locateMaximum}>
    <Icon name="alert" size={14}/>定位最大裁剪</button>
    </div>
    <div className="day-risk-strip" role="group" aria-label="每日裁剪风险">
      {dailyRisk.map(item => <button key={item.date} aria-label={`${item.date}，裁剪 ${number(item.clip, 2)} kWh`} className={day === item.date ? 'selected' : ''} onClick={() => { setDay(item.date); setIndex(0); }} title={`${item.date} / ${number(item.clip, 2)} kWh`} style={{ '--risk-intensity': item.clip < 1e-6 ? 0 : .15 + item.clip / maximumRisk * .8 } as React.CSSProperties}>
        <i />
        <span>{item.date.slice(8)}</span>
        </button>)}
    </div>
    <div className="chart-footnote">
    <Badge>{result.summary.interval_minutes || result.dataset?.interval_minutes || 60} 分钟步长</Badge>
    <span>下方时间轴可用方向键调整时段。{showOracle ? '事后参照看见未来，不可部署。' : 'SOC 为时段执行后的状态；虚线边界为设定的 SOC 范围。'}{hasPV && showForecast && ' 金色虚线为光伏预测。'}</span>
    </div>
    <details className="details-table">
    <summary>逐时数值与计划动作</summary>
    <div className="table-scroll">
    <table>
    <thead>
    <tr>
    <th>时段</th>
    <th>实际 / kW</th>
    <th>预测 / kW</th>
    <th>光伏 / kW</th>
    <th>购电 / kW</th>
    <th>计划充 / 放</th>
    <th>实际充 / 放</th>
    <th>SOC / kWh</th>
    <th>裁剪 / kWh</th>
    </tr>
    </thead>
    <tbody>{rows.map(row => {
            const point = row.strategies[strategy];
            return <tr key={row.timestamp}>
            <td>{row.timestamp.slice(11, 16)}</td>
            <td>{number(row.actual_kw, 2)}</td>
            <td>{number(row.forecast_kw, 2)}</td>
            <td>{number(row.pv_kw, 2)}</td>
            <td>{number(point?.grid_kw, 2)}</td>
            <td>{number(point?.planned_charge_kw)} / {number(point?.planned_discharge_kw)}</td>
            <td>{number(point?.charge_kw)} / {number(point?.discharge_kw)}</td>
            <td>{number(point?.soc_kwh, 2)}</td>
            <td>{number(point?.clip_kwh, 2)}</td>
            </tr>;
        })}</tbody>
    </table>
    </div>
    </details>
  </Section>;
}
