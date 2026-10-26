/* V3 DOM regressions. Network is mocked; these are not browser or pixel evidence. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('typescript');
const { JSDOM } = require('jsdom');
for (const ext of ['.tsx', '.ts']) require.extensions[ext] = (mod, file) => {
  const out = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  mod._compile(out, file);
};
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://unit.test' });
for (const key of ['window', 'document', 'HTMLElement', 'HTMLInputElement', 'HTMLDialogElement', 'Event', 'MouseEvent', 'localStorage']) global[key] = dom.window[key];
Object.defineProperty(global, 'navigator', { value: dom.window.navigator, configurable: true });
global.IS_REACT_ACT_ENVIRONMENT = true;
global.requestAnimationFrame = callback => setTimeout(callback, 0);
HTMLElement.prototype.scrollIntoView = function () {};
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const App = require('../src/App.tsx').default;
const { configSignature } = require('../src/api.ts');
const { number } = require('../src/ui.tsx');
const { siteBatchConfigs } = require('../src/state/batchConfigs.ts');
const source = process.env.UI_RESULT_PATH || path.resolve(__dirname, 'fixtures/result.json');
const result = JSON.parse(fs.readFileSync(source, 'utf8'));
const config = structuredClone(result.config);
const recordConfig = structuredClone(config);
delete recordConfig.idempotency_key;
recordConfig.battery = Object.fromEntries(Object.entries(recordConfig.battery).reverse());
const existing = { run_id: result.run_id, status: 'succeeded', config: recordConfig, result, brief:{strategy:'B2',total_cost:null,comparison_valid:false} };
const dataset = { ...result.dataset, scope: { dispatch: true }, public_data: true };
const otherDataset = { ...dataset, dataset_id:'other-site', name:'独立站点测试夹具', interval_minutes:60, default_evaluation:{...dataset.default_evaluation,test_start:'2025-04-01',test_end:'2025-04-30',protocol_id:'other-protocol'} };
let batchBody = null;
let savedResult = result;
let submission = null;
let runStatus = 'queued';
let importBody = null;
let chatCount = 0;
let chatProvider = ''; 
let modelProfiles = [];
let modelSave = null;
let modelTestCount = 0;
let sessionMessages = [];
let currentQuestion = '';
let deferredSession = null;
let deferredTriggered = false;
let requests = [];
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
global.fetch = async (url, init = {}) => {
  requests.push({ url, init });
  if (url === '/api/v3/health') return response({ status: 'ok' });
  if (url === '/api/v3/defaults') return response(config);
  if (url === '/api/v3/datasets') return response({ datasets: [dataset, otherDataset, { ...dataset, dataset_id: 'channel-only', name: '通道审查数据', scope: { dispatch: false, reason: '单通道不可计算完整站点收益' } }] });
  if (url === '/api/v3/assistant/status') return response({ available: true, local_available:true, model: 'unit-model', public_only: true, manual_backups: [{ provider: 'openrouter', model: 'qwen/qwen3.8-27b:free', available:true }] });
  if (url === '/api/v3/assistant/providers' && !init.method) return response({profiles:modelProfiles,secret_storage:'windows_dpapi_user',default_provider:'local'});
  if (url === '/api/v3/assistant/providers' && init.method === 'POST') { modelSave=JSON.parse(init.body); const profile={...modelSave,id:'profile-ui-test',has_key:Boolean(modelSave.api_key),created_at:'2026-10-04T12:00:00'}; delete profile.api_key; modelProfiles=[profile]; return response(profile); }
  if (url === '/api/v3/assistant/providers/profile-ui-test/test') { modelTestCount++; return response({ok:true,model:modelProfiles[0].model,kind:modelProfiles[0].kind,elapsed_seconds:.25,message:'Unit connection test, no business data'}); }
  if (url === '/api/v3/assistant/providers/profile-ui-test' && init.method === 'PUT') { const body=JSON.parse(init.body); const profile={...modelProfiles[0],...body,has_key:body.api_key === '' ? false : modelProfiles[0].has_key}; delete profile.api_key; modelProfiles=[profile]; return response(profile); }
  if (url === '/api/v3/assistant/providers/profile-ui-test' && init.method === 'DELETE') { modelProfiles=[]; return response({deleted:true}); }
  if (url.startsWith('/api/v3/runs?')) return response({ runs: [existing], next_cursor: null });
  if (url === '/api/v3/runs' && init.method === 'POST') { submission = JSON.parse(init.body); return response({ run_id: 'unit-new-run', status: 'queued', config: submission }); }
  if (url === '/api/v3/runs/unit-new-run/cancel') { runStatus = 'cancelled'; return response({ status: 'cancelled' }); }
  if (url === '/api/v3/runs/unit-new-run') return response({ run_id: 'unit-new-run', status: runStatus, stage: runStatus, message: runStatus === 'cancelled' ? '用户取消运行' : 'unit pending', config: submission });
  if (url === `/api/v3/runs/${existing.run_id}`) return response({ ...existing, result: savedResult });
  if (url === '/api/v3/batches') { batchBody = JSON.parse(init.body); return response({batch_id:'unit-batch',status:'succeeded',runs:batchBody.configs.map((config,i)=>({run_id:'batch-run-'+i,config,status:'succeeded'}))},202); }
  if (url === '/api/v3/datasets/import') { importBody = JSON.parse(init.body); return response({ valid: false, errors: [{ row: 3, field: 'load_kw', reason: '用电值必须是非负有限数值' }] }); }
  if (url.endsWith('/quality')) return response({ detections: [{ id: 'jump', label: '负荷跳变', count: 1, threshold: 100, handling: '保留原值供核对', examples: [{ timestamp: result.series[0].timestamp, load_kw: 5, delta_kw: 120, source_row: 7 }] }] });
  if (url.startsWith('/api/v3/assistant/sessions?')) return response({ sessions: [] });
  if (url === '/api/v3/assistant/chat') { chatCount++; chatProvider = JSON.parse(init.body).provider; currentQuestion = JSON.parse(init.body).question; return response({ request_id: 'unit-chat', session_id: 'unit-session', status: 'queued' }, 202); }
  if (url === '/api/v3/assistant/requests/unit-chat') {
    sessionMessages = [{ role: 'user', content: currentQuestion }, { role: 'assistant', content: '本次结论使用冻结证据。', citations: [{ id: 'e1', label: '最大裁剪', run_id: result.run_id, section: 'replay', timestamp: result.series[2].timestamp, strategy: 'B2' }], draft_patch: { battery: { capacity_kwh: 120 } } }];
    return response({ request_id: 'unit-chat', session_id: 'unit-session', status: 'succeeded' });
  }
  if (url === '/api/v3/assistant/sessions/unit-session') { if (deferredSession) { deferredTriggered = true; return deferredSession; } return response({ id: 'unit-session', messages: sessionMessages }); }
  throw new Error(`Unexpected test API ${url}`);
};
const root = createRoot(document.getElementById('root'));
const body = () => document.body.textContent;
const button = text => [...document.querySelectorAll('button')].find(item => item.textContent.trim() === text);
const click = async element => { assert(element, 'element not found'); await act(async () => element.dispatchEvent(new MouseEvent('click', { bubbles: true }))); };
const settle = (ms = 30) => act(async () => await new Promise(resolve => setTimeout(resolve, ms)));
const includes = text => assert(body().includes(text), `Missing ${text}`);
const setValue = async (element, value) => act(async () => {
  Object.getOwnPropertyDescriptor(element instanceof HTMLInputElement ? HTMLInputElement.prototype : dom.window.HTMLTextAreaElement.prototype, 'value').set.call(element, String(value));
  element.dispatchEvent(new Event('input', { bubbles: true })); element.dispatchEvent(new Event('change', { bubbles: true }));
});
(async () => {
  const start = performance.now(), tests = [];
  localStorage.setItem('nengce.v3.run', existing.run_id);
  localStorage.setItem('nengce.v3.draft', JSON.stringify(config));
  await act(async () => { root.render(React.createElement(App)); await new Promise(resolve => setTimeout(resolve, 30)); });
  await settle();
  const siteConfigs = siteBatchConfigs({...config,tariff:{...config.tariff,demand_per_kw:31}},[dataset,otherDataset],[dataset.dataset_id,otherDataset.dataset_id],'day');
  assert.equal(siteConfigs[0].evaluation.start,dataset.default_evaluation.test_start.slice(0,10)); assert.equal(siteConfigs[1].evaluation.start,'2025-04-01'); assert.equal(siteConfigs[1].evaluation.end,'2025-04-01'); assert.equal(siteConfigs[1].tariff.demand_per_kw,31); assert.equal(siteConfigs[1].protocol_id,'other-protocol'); tests.push('Independent site configurations preserve their own dates and protocol without silently zeroing demand tariff');
  assert.equal(number(null), '—'); assert.equal(number(undefined), '—'); assert.equal(number(NaN), '—'); tests.push('Missing and nonfinite values never format as zero');
  assert.equal(configSignature(config), configSignature(recordConfig)); assert.notEqual(configSignature(config), configSignature({ ...config, risk_margin_scale: .5 })); assert(!body().includes('参数草稿已更改')); tests.push('Normalized business identity ignores transport keys and property order');
  includes(result.forecast.selection_reason); includes('15 分钟步长'); assert(!body().includes('NaN')); tests.push('Restored real V3 result shows actual model, interval and evidence');
  assert.equal(document.querySelector('[aria-label="选择时段"]').max, '95'); tests.push('Native 15-minute chart has 96 keyboard-selectable intervals');
  await click(button('定位最大裁剪')); const max = result.series.reduce((a, b) => (b.strategies.B2.clip_kwh || 0) > (a.strategies.B2.clip_kwh || 0) ? b : a); if (max.strategies.B2.clip_kwh > 0) assert.equal(document.querySelector('[aria-label="选择回放日期"]').value, max.timestamp.slice(0, 10)); tests.push('Anomaly locator reads selected strategy actual series');
  await click(button('运行记录')); includes('B2 费用 / 元'); const historyRow=document.querySelector('.history-table tbody tr'); assert(historyRow.textContent.includes('不可比')); assert.equal(historyRow.querySelectorAll('td')[3].childNodes[0].textContent,'—'); tests.push('History uses brief index, retaining null cost and invalid comparison');
  await click(document.querySelector(`[aria-label="批量选择 ${dataset.name}"]`)); await click(document.querySelector('[aria-label="批量选择 独立站点测试夹具"]')); includes('2025-04-01 → 2025-04-01'); await click(button('运行 2 个独立站点')); assert.equal(batchBody.configs.length,2); assert.equal(batchBody.configs[1].dataset_id,'other-site'); assert.equal(batchBody.configs[1].evaluation.start,'2025-04-01'); assert(batchBody.idempotency_key); tests.push('Multi-site UI submits independent configs with visible per-site periods');
  await click(button('费用对照')); assert.equal(document.querySelectorAll('.cost-row').length, result.strategies.length - 1); await click(document.querySelector('.check-label input')); assert.equal(document.querySelectorAll('.cost-row').length, result.strategies.length); tests.push('All eight strategies remain accessible with explicit hindsight toggle');
  for (const format of ['json', 'csv', 'html']) assert([...document.querySelectorAll('.export-links a')].some(item => item.getAttribute('href') === `/api/v3/runs/${result.run_id}/export/${format}`)); tests.push('Exports bind to same immutable API result');
  await click(button('预测验证')); includes('公开历史回归'.replace('公开', '')); await click(button('开发验证')); includes(number(result.forecast.validation[0].wape_pct, 2)); tests.push('Development validation and disclosed regression metrics stay separate');
  await click(button('数据目录')); await click([...document.querySelectorAll('.text-button')].find(item => item.textContent.includes('来源与审查'))); await settle(); includes('负荷跳变'); includes('保留原值供核对'); assert(button('仅可审查').disabled); tests.push('Source quality loads actual endpoint and channel-only case blocks dispatch');
  await click(button('导入私人 CSV')); await click(document.querySelector('.paste-csv summary')); await setValue(document.querySelector('[aria-label="CSV 内容"]'), 'timestamp,load_kw\n2025-01-01 00:00:00,-1'); await act(async () => document.querySelector('.csv-import form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); assert.equal(importBody, null); includes('请先确认拥有'); await click(document.querySelector('.authorization input')); await act(async () => document.querySelector('.csv-import form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); includes('原始 CSV 第 3 行'); assert.equal(importBody.interval_minutes, 60); tests.push('Private CSV authorization and original-row validation errors are preserved');
  await click(button('参数与运行')); assert(document.querySelector('dialog[open]')); const form = document.querySelector('.parameters-form'); const capacity = [...form.querySelectorAll('label')].find(item => item.textContent.includes('额定容量')).querySelector('input'); await setValue(capacity, 120); includes('参数草稿变更'); includes('参数草稿已更改'); tests.push('Real parameter edit exposes immutable-versus-draft diff');
  const realRects=HTMLElement.prototype.getClientRects; HTMLElement.prototype.getClientRects=function(){return [{}]}; const lastControl=[...form.querySelectorAll('button')].find(item=>item.textContent.includes('运行当前草稿')); const firstControl=document.querySelector('dialog[open] [aria-label="关闭侧栏"]'); lastControl.focus(); await act(async()=>lastControl.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}))); assert(document.activeElement === firstControl, 'Forward Tab did not wrap: '+document.activeElement.tagName+' / '+document.activeElement.textContent?.slice(0,70)+'; last disabled='+lastControl.disabled); await act(async()=>firstControl.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}))); assert(document.activeElement === lastControl, 'Reverse Tab did not wrap to last dialog control'); HTMLElement.prototype.getClientRects=realRects; tests.push('Modal Tab and Shift+Tab explicitly wrap enabled visible controls');
  const initial = [...form.querySelectorAll('label')].find(item => item.textContent.includes('初始 SOC')).querySelector('input'); await setValue(initial, 5); await act(async () => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); assert.equal(submission, null); includes('SOC 需要满足'); tests.push('Invalid cross-field SOC blocks request'); await setValue(initial, 50);
  await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); }); assert.equal(requests.filter(item => item.url === '/api/v3/runs' && item.init.method === 'POST').length, 1); assert.equal(submission.battery.capacity_kwh, 120); assert(submission.idempotency_key); tests.push('Repeated submit creates one real-shaped idempotent request');
  await click(button('取消任务')); await settle(1000); includes('已取消'); assert(!document.querySelector('.time-svg')); tests.push('Cancellation waits for terminal response and hides successful charts');
  await act(async () => { window.history.pushState(null, '', `#page=workspace&run=${existing.run_id}`); window.dispatchEvent(new dom.window.PopStateEvent('popstate')); }); await settle(); assert(document.querySelector('.time-svg')); tests.push('Browser history route restores immutable selected run');
  await click(button('证据助手')); includes('本机就绪'); assert.equal(document.querySelector('[aria-label="助手模型平台"]').value,'local'); tests.push('Assistant defaults to local evidence, honestly labelled without a language model'); assert(!document.querySelector('.assistant-context').textContent.includes('在线')); await act(async () => { const select = document.querySelector('[aria-label="助手模型平台"]'); Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype,'value').set.call(select,'openrouter'); select.dispatchEvent(new Event('change',{bubbles:true})); }); await setValue(document.querySelector('#assistant-question'), '解释风险'); await act(async () => { document.querySelector('.chat-composer').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); document.querySelector('.chat-composer').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); }); assert.equal(chatCount, 1); assert.equal(chatProvider, 'openrouter'); tests.push('Model platform selection is manual and carried in the backend request'); await settle(800); await settle(); includes('本次结论使用冻结证据'); tests.push('Assistant uses one asynchronous request, real state polling and persisted session');
  await click(document.querySelector('.model-settings-toggle')); await setValue(document.querySelector('[aria-label="模型配置名称"]'),'我的云模型'); await setValue(document.querySelector('[aria-label="模型 API 基础地址"]'),'https://example.invalid/v1'); await setValue(document.querySelector('[aria-label="模型标识"]'),'custom-model'); await setValue(document.querySelector('[aria-label="模型 API 密钥"]'),'unit-only-dummy-key'); assert.equal(modelTestCount,0); assert.equal(modelSave,null); await act(async()=>document.querySelector('.model-settings-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))); assert.equal(modelSave,null); includes('请确认自有服务的费用'); tests.push('Custom cloud provider requires explicit billing and data acknowledgment; entering credentials does not call a model');
  await click(document.querySelector('[aria-label="确认自有模型费用与数据范围"]')); await act(async()=>{document.querySelector('.model-settings-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));document.querySelector('.model-settings-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));}); await settle(); assert.equal(requests.filter(item=>item.url==='/api/v3/assistant/providers'&&item.init.method==='POST').length,1); assert.equal(modelSave.api_key,'unit-only-dummy-key'); assert.equal(document.querySelector('[aria-label="模型 API 密钥"]').value,''); assert(!body().includes('unit-only-dummy-key')); assert(!Object.values(localStorage).join(' ').includes('unit-only-dummy-key')); assert.equal(modelTestCount,0); tests.push('Custom provider saves once to backend, clears key field, keeps secrets out of page and localStorage and makes no implicit model call');
  await click(button('测试已保存连接')); assert.equal(modelTestCount,1); includes('连接测试通过'); await click(button('清除保存的密钥')); includes('保存的密钥已清除'); assert.equal(modelProfiles[0].has_key,false); await click(button('移除模型配置')); assert.equal(modelProfiles.length,0); includes('模型配置及其保存的密钥已移除'); await click(document.querySelector('.model-settings-toggle')); tests.push('User explicitly tests saved provider then clears its key and removes profile without hidden fallback');
  await click(document.querySelector('.model-settings-toggle')); await setValue(document.querySelector('[aria-label="模型 API 密钥"]'),'UNSAVED-DUMMY-KEY'); await click(document.querySelector('dialog[open] [aria-label="关闭侧栏"]')); await click(button('证据助手')); await click(document.querySelector('.model-settings-toggle')); assert.equal(document.querySelector('[aria-label="模型 API 密钥"]').value,''); await click(document.querySelector('.model-settings-toggle')); tests.push('Closing the assistant drawer clears an unsaved key from the retained component, including reopen');
  await click(button('最大裁剪')); assert.equal(document.querySelector('[aria-label="选择时段"]').value, '2'); tests.push('Evidence citation focuses matching strategy and interval');
  await click(button('证据助手')); await click(button('放入草稿并审查')); assert.equal([...document.querySelectorAll('.parameters-form label')].find(item => item.textContent.includes('额定容量')).querySelector('input').value, '120'); assert.equal(requests.filter(item => item.url === '/api/v3/runs' && item.init.method === 'POST').length, 1); tests.push('Assistant proposal only edits reviewable draft, never starts a run');
  await act(async () => root.unmount());
  const secondary = createRoot(document.getElementById('root'));
  const nullResult = structuredClone(result); nullResult.summary.recommended_strategy = null; nullResult.summary.comparison_valid = false; for (const strategy of nullResult.strategies) { strategy.total_cost = null; strategy.demand_cost = null; strategy.savings_vs_b0 = null; strategy.savings_pct = null; strategy.comparison_valid = false; }
  const { Overview } = require('../src/components/Overview.tsx'); const { CostAnalysis } = require('../src/components/CostAnalysis.tsx');
  await act(async () => secondary.render(React.createElement(Overview, { result: nullResult, config, onNotify() {} }))); includes('尚无可推荐的完整方案'); includes('待完整月核算'); tests.push('Null recommendation and incomplete demand bill cannot become a zero-cost winner');
  await act(async () => secondary.render(React.createElement(CostAnalysis, { result: nullResult }))); includes('无法计算完整月账'); includes('已知费用小计'); tests.push('Partial bills retain known subtotal and show comparison invalid');
  await act(async () => secondary.render(React.createElement(CostAnalysis, { result, focus: { id: 'test-citation', label: 'R2 cost', section: 'report', strategy: 'R2' } }))); assert(document.querySelector('.cost-row.is-selected').textContent.includes('R2')); tests.push('Cost citation selects the cited strategy rather than silently showing B2');
  const { AssistantPanel } = require('../src/components/AssistantPanel.tsx');
  await act(async () => secondary.render(React.createElement(AssistantPanel, { result: { ...result, dataset: { ...dataset, public_data: false } }, status: { available: true,local_available:true }, onCite() {}, onDraft() {} }))); assert(!document.querySelector('#assistant-question').disabled); await act(async()=>{const select=document.querySelector('[aria-label="助手模型平台"]');Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype,'value').set.call(select,'zhipu');select.dispatchEvent(new Event('change',{bubbles:true}));}); assert(document.querySelector('#assistant-question').disabled); tests.push('Private data permits pure local evidence but cannot be sent to any model API');
  let resolveLate; deferredSession = new Promise(resolve => { resolveLate = resolve; });
  localStorage.setItem(`nengce.v3.assistant.request.${result.run_id}`, 'unit-chat');
  await act(async () => secondary.render(React.createElement(AssistantPanel, { result: { ...result, run_id: result.run_id + '-other', dataset }, status: { available: true }, onCite() {}, onDraft() {} })));
  await act(async () => secondary.render(React.createElement(AssistantPanel, { result: { ...result, dataset }, status: { available: true }, onCite() {}, onDraft() {} })));
  await settle(); assert(deferredTriggered);
  await act(async () => secondary.render(React.createElement(AssistantPanel, { result: { ...result, run_id: 'new-run-race', dataset }, status: { available: true }, onCite() {}, onDraft() {} })));
  await act(async () => resolveLate(response({ id: 'unit-session', messages: [{ role: 'assistant', content: 'STALE PREVIOUS RUN ANSWER' }] })));
  await settle(); assert(!body().includes('STALE PREVIOUS RUN ANSWER')); tests.push('Late completed-session read cannot overwrite a different selected run');
  await act(async () => secondary.unmount());
  console.log(JSON.stringify({ status: 'PASS', passed: tests.length, failed: 0, source, elapsed_seconds: (performance.now() - start) / 1000, runtime: { node: process.version, platform: process.platform, architecture: process.arch }, tests, limits: 'DOM tests use mocked HTTP; not real browser, layout, online model, network or video evidence.' }, null, 2));
})().catch(error => { console.error(error.message); console.error(error.stack?.split('\n').slice(0,5).join('\n')); process.exitCode = 1; root.unmount(); });
