import { useEffect, useRef } from 'react';
import { Icon } from './icons';
import { apiPath } from './api';
export function number(value: unknown, digits = 1): string {
    return typeof value === 'number' && Number.isFinite(value)
        ? value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
        : '—';
}
export const money = (value: unknown) => number(value, 2);
export const modelName = (name?: string) => ({ HistGradientBoosting: '梯度提升树 HGB', hist_gradient_boosting: '梯度提升树 HGB', 'Weekly naive': '周季节朴素', weekly_naive: '周季节朴素', 'Daily naive': '日季节朴素', daily_naive: '日季节朴素' }[name || ''] || name || '待计算');
export const strategyName = (id: string) => ({ B0: '无储能', B1: '固定峰谷规则', B2: '验证选定预测', N1: '周朴素对照', L1: '学习模型 HGB', R1: '误差安全余量', R2: '状态可达风险策略', O1: '完美预知参照' }[id] || id);
export const stressName = (id?: string) => ({ none: '标准情景', load_up_20: '负荷增加 20%', peak_price_up_20: '峰价增加 20%', forecast_bias_up_20: '预测偏高 20%', pv_drop_30: '光伏下降 30%' }[id || 'none'] || id);
export function Button({ children, onClick, disabled, variant = 'primary', type = 'button', className = '', title }: {
    children: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
    type?: 'button' | 'submit';
    className?: string;
    title?: string;
}) {
    return <button type={type} onClick={onClick} disabled={disabled} className={`button button--${variant} ${className}`} title={title}>{children}</button>;
}
export function Badge({ children, tone = 'neutral' }: {
    children: React.ReactNode;
    tone?: 'neutral' | 'green' | 'amber' | 'red';
}) {
    return <span className={`badge badge--${tone}`}>{children}</span>;
}
export function Notice({ children, tone = 'info', title }: {
    children: React.ReactNode;
    tone?: 'info' | 'warning' | 'danger';
    title?: string;
}) {
    return <div className={`notice notice--${tone}`} role={tone === 'danger' ? 'alert' : undefined}>
    <Icon name={tone === 'danger' ? 'alert' : 'info'} size={17}/>
    <div>{title && <strong>{title}</strong>}<div>{children}</div>
    </div>
    </div>;
}
export function Section({ title, eyebrow, action, children, className = '', id }: {
    title?: string;
    eyebrow?: string;
    action?: React.ReactNode;
    children: React.ReactNode;
    className?: string;
    id?: string;
}) {
    return <section className={`surface ${className}`} id={id}>
    {(title || eyebrow || action) && <div className="section-heading">
        <div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}{title && <h2>{title}</h2>}</div>{action}</div>}
    {children}
  </section>;
}
export function Drawer({ title, eyebrow, children, open, onClose, className = '' }: {
    title: string;
    eyebrow?: string;
    children: React.ReactNode;
    open: boolean;
    onClose: () => void;
    className?: string;
}) {
    const ref = useRef<HTMLDialogElement>(null);
    const trigger = useRef<HTMLElement | null>(null);
    useEffect(() => {
        if (open && !ref.current?.open) {
            trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            ref.current?.showModal();
        }
        if (!open && ref.current?.open) {
            ref.current.close();
            if (trigger.current?.isConnected) trigger.current.focus({ preventScroll: true });
        }
    }, [open]);
    return <dialog ref={ref} className={`drawer ${className}`} aria-label={title} onCancel={event => { event.preventDefault(); onClose(); }} onKeyDown={event => {
        if (event.key !== 'Tab' || !ref.current) return;
        const candidates = Array.from(ref.current.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])'));
        const focusable = candidates.filter(element => {
            const closed = element.closest('details:not([open])');
            if (closed && !closed.querySelector('summary')?.contains(element)) return false;
            const style = window.getComputedStyle(element);
            return element.tabIndex >= 0 && element.getClientRects().length > 0 && style.visibility !== 'hidden' && style.display !== 'none';
        });
        focusable.sort((left, right) => left.compareDocumentPosition(right) & window.Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (!first) { event.preventDefault(); ref.current.focus(); return; }
        if (event.shiftKey && (document.activeElement === first || !focusable.includes(document.activeElement as HTMLElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !focusable.includes(document.activeElement as HTMLElement))) { event.preventDefault(); first.focus(); }
    }} onClick={event => { if (event.target === ref.current)
        onClose(); }}>
    <div className="drawer-header">
    <div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2>
    </div>
    <button className="icon-button" aria-label="关闭侧栏" onClick={onClose}>
    <Icon name="close"/>
    </button>
    </div>
    <div className="drawer-body">{children}</div>
  </dialog>;
}
export function Empty({ title, children, action, compact = false }: {
    title: string;
    children: React.ReactNode;
    action?: React.ReactNode;
    compact?: boolean;
}) {
    return <div className={`empty-state ${compact ? 'empty-state--compact' : ''}`}>
    <div className="empty-mark">
    <Icon name="chart" size={27}/>
    </div>
    <h3>{title}</h3>
    <p>{children}</p>{action}</div>;
}
export function NumberField({ label, value, unit, onChange, min, max, step = 'any' }: {
    label: string;
    value: number;
    unit?: string;
    onChange: (value: number) => void;
    min?: number;
    max?: number;
    step?: number | 'any';
}) {
    return <label className="field">
    <span>{label}</span>
    <div className="number-input">
    <input type="number" required value={Number.isFinite(value) ? Number(value.toFixed(5)) : ''} min={min} max={max} step={step} onChange={event => onChange(event.target.value === '' ? NaN : Number(event.target.value))}/>{unit && <small>{unit}</small>}</div>
    </label>;
}
export function KeyValue({ label, children }: {
    label: string;
    children: React.ReactNode;
}) {
    return <div className="key-value">
    <span>{label}</span>
    <strong>{children}</strong>
    </div>;
}
export function ExportLinks({ runId }: {
    runId: string;
}) {
    return <div className="export-links">{['json', 'csv', 'html'].map(format => <a key={format} href={apiPath(`/runs/${encodeURIComponent(runId)}/export/${format}`)} download className="button button--secondary">
        <Icon name="down" size={15}/>{format.toUpperCase()}</a>)}</div>;
}
