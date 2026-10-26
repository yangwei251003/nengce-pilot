import { useEffect, useState } from 'react';
import type { Citation, Config } from './types';
import { statusLabel } from './api';
import { useWorkspace } from './state/useWorkspace';
import type { Page } from './state/useWorkspace';
import { Icon } from './icons';
import { Badge, Button, Drawer, Notice, stressName } from './ui';
import { Overview } from './components/Overview';
import { Parameters } from './components/Parameters';
import { DatasetCatalog } from './components/DatasetCatalog';
import { CostAnalysis } from './components/CostAnalysis';
import { ForecastAnalysis } from './components/ForecastAnalysis';
import { History } from './components/History';
import { AssistantPanel } from './components/AssistantPanel';
import { EvidencePanel } from './components/EvidencePanel';
const navigation: {
    id: Page;
    label: string;
    icon: string;
}[] = [
    { id: 'workspace', label: '方案工作台', icon: 'chart' },
    { id: 'datasets', label: '数据目录', icon: 'data' },
    { id: 'costs', label: '费用对照', icon: 'grid' },
    { id: 'forecast', label: '预测验证', icon: 'spark' },
    { id: 'history', label: '运行记录', icon: 'history' },
];
export default function App() {
    const w = useWorkspace();
    const [drawer, setDrawer] = useState<'parameters' | 'assistant' | 'evidence' | null>(null);
    const [focus, setFocus] = useState<Citation | null>(null);
    const displayedDataset = w.result && w.page !== 'datasets' ? w.frozenDataset : w.dataset;
    const displayedConfig = w.result && w.page !== 'datasets' ? w.run?.config : w.config;
    useEffect(() => {
        if (focus && w.page === 'workspace')
            requestAnimationFrame(() => document.getElementById('timeline')?.scrollIntoView({ behavior: 'auto', block: 'start' }));
    }, [focus, w.page]);
    function cite(citation: Citation) {
        if (citation.run_id && citation.run_id !== w.result?.run_id) {
            w.setToast('引用绑定另一份运行，请先恢复该运行。');
            return;
        }
        setDrawer(null);
        setFocus(citation);
        if (citation.section === 'config')
            setDrawer('parameters');
        else if (citation.section === 'forecast')
            w.navigate('forecast');
        else if (citation.section === 'cost' || citation.section === 'report')
            w.navigate('costs');
        else if (citation.section === 'provenance' || citation.section === 'data')
            setDrawer('evidence');
        else
            w.navigate('workspace');
        w.setToast(`已定位证据：${citation.label}`);
    }
    function draft(patch: Partial<Config>) {
        if (!w.config)
            return;
        const next = { ...w.config };
        if (patch.battery)
            next.battery = { ...next.battery, ...patch.battery };
        if (patch.tariff)
            next.tariff = { ...next.tariff, ...patch.tariff };
        if (patch.risk_margin_scale !== undefined)
            next.risk_margin_scale = patch.risk_margin_scale;
        w.updateConfig(next);
        setDrawer('parameters');
        w.setToast('助手建议已放入参数草稿；尚未运行，也未改变已有结果。');
    }
    return <div className="app-shell">
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); const main = document.getElementById('main-content'); main?.focus(); main?.scrollIntoView({ block: 'start' }); }}>跳到主要内容</a>
    <header className="app-header">
    <button className="brand" onClick={() => w.navigate('workspace')} aria-label="能策 Pilot 方案工作台">
    <span className="brand-symbol">
    <Icon name="bolt" size={22}/>
    </span>
    <span>能策<span className="brand-latin">PILOT</span>
    </span>
    <span className="version-tag">03.1</span>
    </button>
    <div className="header-description">单站光储 · 决策工作台</div>
    <div className="header-actions">
    <span className="local-indicator">
    <i />本机计算</span>
    <button className={`assistant-launch ${drawer === 'assistant' ? 'is-active' : ''}`} onClick={() => setDrawer('assistant')}>
    <Icon name="spark" size={17}/>
    <span>证据助手</span>
    </button>
    </div>
    </header>
    <nav className="main-nav" aria-label="主要页面">{navigation.map(item => <button key={item.id} className={w.page === item.id ? 'is-active' : ''} aria-current={w.page === item.id ? 'page' : undefined} onClick={() => w.navigate(item.id)}>
        <Icon name={item.icon} size={16}/>{item.label}</button>)}<span className="nav-spacer"/>
    <button onClick={() => setDrawer('evidence')}>
    <Icon name="file" size={16}/>证据与导出</button>
    </nav>
    <main id="main-content" className="workspace" tabIndex={-1}>
      <div className="context-bar">
    <div>
    <span className="context-label">{w.result && w.page !== 'datasets' ? '本次结果' : '参数草稿'}</span>
    <strong>{displayedDataset?.name || '读取数据目录…'}</strong>{displayedDataset && <Badge>{displayedDataset.public_data === true ? '公开案例' : '本机数据'}</Badge>}<span className="context-period">{displayedConfig?.evaluation.start} → {displayedConfig?.evaluation.end}</span>{displayedConfig?.stress && displayedConfig.stress !== 'none' && <Badge tone="amber">{stressName(displayedConfig.stress)}</Badge>}</div>
    <Button variant="secondary" disabled={!w.config || w.loadingRun} onClick={() => setDrawer('parameters')}>
    <Icon name="sliders" size={16}/>参数与运行</Button>
    </div>
      {w.error && <div className="error-row">
        <Notice tone="danger">{w.error}</Notice>
        <Button variant="secondary" onClick={w.config ? () => void w.start() : w.retryConnection} disabled={w.working}>{w.config ? '重试当前草稿' : '重新连接'}</Button>
        <button className="icon-button" onClick={() => w.setError('')} aria-label="关闭错误提示">
        <Icon name="close" size={16}/>
        </button>
        </div>}
      {w.run?.legacy && w.result && <Notice title="V2 只读存档">该结果为原冻结产物迁入，原证据 ID：{w.run.original_run_id || w.result.run_id}。尚未按 V3 计算；新草稿运行将生成独立 V3 结果。</Notice>}
      {w.result && w.dirty && <div className="draft-banner">
        <Icon name="sliders" size={16}/>
        <span>参数草稿已更改，下面仍是已完成运行的结果。</span>
        <button className="text-button" onClick={() => setDrawer('parameters')}>查看变更并重算<Icon name="arrow" size={14}/>
        </button>
        </div>}
      {(w.working || w.loadingRun) && <section className="run-progress" aria-live="polite">
        <span className="spinner"/>
        <div>
        <strong>{w.loadingRun ? '正在恢复运行结果' : w.submitting ? '正在提交计算' : statusLabel(w.run?.stage || w.run?.status || 'queued')}</strong>
        <p>{w.loadingRun ? '读取该运行的冻结配置与证据。' : w.run?.message || '等待本地服务确认。'}</p>{!w.submitting && !w.loadingRun && <progress value={w.run?.progress || 0} max={100} aria-label="后端报告的计算进度"/>}</div>{!w.submitting && !w.loadingRun && <Button variant="secondary" disabled={w.cancelPending} onClick={() => void w.cancel()}>{w.cancelPending ? '等待取消确认' : '取消任务'}</Button>}</section>}
      {w.run && ['failed', 'cancelled'].includes(w.run.status) && !w.working && <Notice tone={w.run.status === 'failed' ? 'danger' : 'info'} title={statusLabel(w.run.status)}>{w.run.message || String(w.run.error || '本次运行未产生成功结果。')}<div>
        <Button variant="secondary" onClick={() => void w.start()}>重新运行当前草稿</Button>
        </div>
        </Notice>}
      {w.loading ? <div className="boot-state" role="status">
        <span className="spinner"/>正在连接本机服务，读取真实数据与运行记录…</div> : <>
        {w.page === 'workspace' && <Overview result={w.result} config={w.result ? w.run!.config : w.config} dataset={w.result ? w.frozenDataset : w.dataset} focus={focus} onConfigure={() => setDrawer('parameters')} onData={() => w.navigate('datasets')} onEvidence={() => setDrawer('evidence')} onAssistant={() => setDrawer('assistant')} onForecast={() => w.navigate('forecast')} onNotify={w.setToast}/>}
        {w.page === 'datasets' && <DatasetCatalog datasets={w.datasets} selectedId={w.config?.dataset_id} onChoose={dataset => { w.chooseDataset(dataset); setDrawer('parameters'); }} onImported={dataset => { w.imported(dataset); setDrawer('parameters'); }}/>}
        {w.page === 'costs' && <CostAnalysis result={w.result} focus={focus}/>}
        {w.page === 'forecast' && <ForecastAnalysis result={w.result}/>}
        {w.page === 'history' && w.config && <History runs={w.history} total={w.historyTotal} nextCursor={w.nextCursor} batch={w.batch} config={w.config} datasets={w.datasets} busy={w.working} onLoadMore={() => { if (w.nextCursor)
            void w.refreshHistory(w.nextCursor); }} onSelect={id => void w.selectRun(id)} onBatch={stresses => void w.startBatch(stresses)} onSiteBatch={configs => void w.startBatchConfigs(configs)}/>}
      </>}
      <footer className="app-footer">
    <span>能策 Pilot V3.1 · 本机研究与方案验证</span>
    <span>示例电价 · 无实机控制 · 不构成投资回报承诺</span>
    </footer>
    </main>
    <Drawer title="参数草稿" eyebrow="CONFIGURE / REVIEW / RUN" open={drawer === 'parameters'} onClose={() => setDrawer(null)}>{w.config && <Parameters key={w.config.dataset_id} config={w.config} frozen={w.run?.config} dataset={w.dataset} working={w.working} onChange={w.updateConfig} onReset={w.reset} onRun={async () => { const ok = await w.start(); if (ok)
        setDrawer(null); return ok; }}/>}</Drawer>
    <Drawer title="证据助手" eyebrow="ASK WITH EVIDENCE" open={drawer === 'assistant'} onClose={() => setDrawer(null)} className="assistant-drawer">
    <AssistantPanel result={w.result} status={w.assistantStatus} onCite={cite} onDraft={draft} open={drawer === 'assistant'}/>
    </Drawer>
    <Drawer title="本次运行的证据" eyebrow="IMMUTABLE RUN" open={drawer === 'evidence'} onClose={() => setDrawer(null)}>
    <EvidencePanel result={w.result} config={w.run?.config} dataset={w.frozenDataset}/>
    </Drawer>
    {w.toast && <div className="toast" role="status">
        <Icon name="check" size={17}/>{w.toast}<button className="icon-button" onClick={() => w.setToast('')} aria-label="关闭通知">
        <Icon name="close" size={14}/>
        </button>
        </div>}
  </div>;
}
