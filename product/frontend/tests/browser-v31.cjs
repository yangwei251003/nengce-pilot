/* Installed Edge + actual local API. No model response mocks or cloud requests. */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const BASE = process.env.V31_URL || 'http://127.0.0.1:8003';
const RUN = process.env.V31_RUN || 'run-721138d82593';
const out = path.resolve(__dirname, '../../../qa/v31/frontend/browser');
fs.mkdirSync(out, { recursive: true });
const report = { started_at: new Date().toISOString(), browser: 'Installed Microsoft Edge via Playwright, real localhost API', url: BASE, run_id: RUN, cases: [], console: [], network_failures: [], limits: ['No live cloud model calls are performed. This verifies real local evidence and custom profile controls, not model quality.', 'Cloud save uses a disposable nonfunctional dummy key and never tests or calls that endpoint. All disposable profiles are removed.'] };
let browser;
let page;
const created = [];
async function record(name, action, critical = false) {
  const started = performance.now();
  try { await action(); report.cases.push({ name, status: 'PASS', elapsed_seconds: (performance.now() - started) / 1000 }); console.log(`PASS: ${name}`); }
  catch (error) { report.cases.push({ name, status: 'FAIL', error: error.message, elapsed_seconds: (performance.now() - started) / 1000 }); console.log(`FAIL: ${name}`); if (page) await page.screenshot({path:path.join(out,`failure-${report.cases.length}.png`),fullPage:true}).catch(()=>{}); if (critical) throw error; }
}
async function api(route, init) {
  const response = await fetch(`${BASE}/api/v3${route}`, { ...init, headers: { 'Content-Type': 'application/json' } });
  assert(response.ok, `API status ${response.status}: ${route}`);
  return response.json();
}
async function screenshot(name) { await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: false }); }
async function openAssistant() { if (!await page.getByRole('dialog', { name: '证据助手' }).isVisible()) await page.getByRole('button', { name: '证据助手', exact: true }).click(); }
async function ask(question) {
  const before = await page.locator('.chat-message--assistant').count();
  await page.locator('#assistant-question').fill(question);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.waitForFunction(n => document.querySelectorAll('.chat-message--assistant').length > n, before, { timeout: 30000 });
  return page.locator('.chat-message--assistant').last().innerText();
}
(async () => {
  const started = performance.now();
  try {
    await api('/health');
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    page = await context.newPage();
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => report.console.push(error.message));
    page.on('requestfailed', request => report.network_failures.push({ url: request.url().replace(/\?.*/, ''), reason: request.failure()?.errorText }));
    await page.goto(`${BASE}/#page=workspace&run=${RUN}`);
    await page.locator('.summary-grid').waitFor({ timeout: 60000 });
    await record('Default local evidence mode is labelled without an LLM and accepts questions', async () => {
      await openAssistant();
      assert.equal(await page.getByLabel('助手模型平台').inputValue(), 'local');
      assert((await page.locator('.assistant-context').innerText()).includes('无语言模型'));
      assert(await page.locator('#assistant-question').isEnabled());
      await screenshot('01-local-1440');
    });
    await record('Actual cost answer and follow-up cite the same frozen run', async () => {
      const first = await ask('B2 的实际回放费用是多少？');
      assert(/69[,.]?071[.,]59/.test(first.replace(/\s/g, '')), first);
      assert(await page.locator('.chat-message--assistant').last().locator('.citations button').count() > 0);
      const second = await ask('与无储能相比节省多少？');
      assert(/2[,.]?045[.,]60/.test(second.replace(/\s/g, '')), second);
      await screenshot('02-follow-up-1440');
    });
    await record('Profile save requires explicit cloud cost acknowledgment and never calls its endpoint', async () => {
      await page.locator('.model-settings-toggle').click();
      await page.getByLabel('模型配置名称').fill('V3.1 浏览器验收 · 临时云配置');
      await page.getByLabel('模型 API 基础地址').fill('https://example.invalid/v1');
      await page.getByLabel('模型标识', { exact: true }).fill('nonfunctional-test-model');
      await page.getByLabel('模型 API 密钥', { exact: true }).fill('NONFUNCTIONAL-DISPOSABLE-QA-KEY');
      await page.getByRole('button', { name: '保存模型配置', exact: true }).click();
      await page.locator('.model-settings-content .notice--danger').waitFor();
      assert((await page.locator('.model-settings-content .notice--danger').innerText()).includes('请确认自有服务的费用与公开摘要发送范围'));
      await page.getByLabel('确认自有模型费用与数据范围').check();
      const saved = page.waitForResponse(response => response.url().endsWith('/assistant/providers') && response.request().method() === 'POST');
      await page.getByRole('button', { name: '保存模型配置', exact: true }).click();
      const profile = await (await saved).json(); created.push(profile.id);
      await page.getByText('配置已保存。连接状态需由你点击测试确认；保存不会发起模型调用。', { exact: true }).waitFor();
      assert.equal(await page.getByLabel('模型 API 密钥', { exact: true }).inputValue(), '');
      const list = await api('/assistant/providers');
      const own = list.profiles.find(item => item.id === profile.id);
      assert(own.has_key); assert(!JSON.stringify(list).includes('NONFUNCTIONAL-DISPOSABLE-QA-KEY'));
      const storage = await page.evaluate(() => JSON.stringify(Object.fromEntries(Object.keys(localStorage).map(key => [key, localStorage.getItem(key)]))));
      assert(!storage.includes('NONFUNCTIONAL-DISPOSABLE-QA-KEY'));
      await page.getByLabel('助手模型平台').selectOption(profile.id);
      assert((await page.locator('.model-cost-disclosure').innerText()).includes('费用由该账户承担'));
      await screenshot('03-custom-model-1440');
    });
    await record('Saved key can be cleared; missing key disables cloud questions; profile can be deleted', async () => {
      await page.getByRole('button', { name: '清除保存的密钥', exact: true }).click();
      await page.getByText('保存的密钥已清除。云端提问将停用，直到重新配置密钥。', { exact: true }).waitFor();
      assert(await page.locator('#assistant-question').isDisabled());
      await page.getByRole('button', { name: '移除模型配置', exact: true }).click();
      await page.getByText('模型配置及其保存的密钥已移除。', { exact: true }).waitFor();
      assert.equal(await page.getByLabel('助手模型平台').inputValue(), 'local');
    });
    await record('Local API profile receives an explicit real failed connection test, without fake success', async () => {
      await page.getByLabel('模型服务位置').selectOption('local');
      await page.getByLabel('模型配置名称').fill('V3.1 浏览器验收 · 未启动本机服务');
      await page.getByLabel('模型 API 基础地址').fill('http://127.0.0.1:9/v1');
      await page.getByLabel('模型标识', { exact: true }).fill('nonfunctional-local-model');
      const saved = page.waitForResponse(response => response.url().endsWith('/assistant/providers') && response.request().method() === 'POST');
      await page.getByRole('button', { name: '保存模型配置', exact: true }).click();
      const profile = await (await saved).json(); created.push(profile.id);
      await page.getByText('配置已保存。连接状态需由你点击测试确认；保存不会发起模型调用。', { exact: true }).waitFor();
      await page.getByRole('button', { name: '测试已保存连接', exact: true }).click();
      await page.waitForFunction(() => document.body.innerText.includes('连接测试未通过') || document.body.innerText.includes('连接测试未成功'), { timeout: 30000 });
      assert(!(await page.locator('.model-settings-content').innerText()).includes('连接测试通过'));
      await screenshot('04-local-connection-failure-1440');
      await page.getByRole('button', { name: '移除模型配置', exact: true }).click();
      await page.getByText('模型配置及其保存的密钥已移除。', { exact: true }).waitFor();
    });
    for (const [width, height] of [[1280, 800], [390, 844]]) {
      await record(`Assistant and configuration layout ${width}×${height}`, async () => {
        await page.setViewportSize({ width, height });
        await screenshot(`05-settings-${width}`);
        const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth > innerWidth, drawer: document.querySelector('.assistant-drawer').scrollWidth > document.querySelector('.assistant-drawer').clientWidth }));
        assert(!overflow.page && !overflow.drawer, JSON.stringify(overflow));
        assert(await page.getByLabel('模型 API 基础地址').isVisible());
        assert(!await page.locator('.chat-composer').isVisible(), 'Chat input overlays the open model settings');
      });
    }
    await record('Returning from settings restores chat and clears the transient unsaved password', async () => {
      await page.getByLabel('模型 API 密钥', { exact: true }).fill('UNSAVED-DISPOSABLE-UI-KEY');
      await page.getByRole('button', { name: '返回证据提问', exact: true }).click();
      await page.locator('.chat-composer').waitFor({state:'visible'});
      assert(await page.locator('.chat-composer').isVisible());
      await page.locator('.model-settings-toggle').click();
      await page.getByLabel('模型 API 密钥', { exact: true }).waitFor({state:'visible'});
      assert.equal(await page.getByLabel('模型 API 密钥', { exact: true }).inputValue(), '');
      await screenshot('06-settings-return-390');
    });
    await record('Escape closes configuration drawer and returns focus to the assistant trigger', async () => {
      await page.keyboard.press('Escape');
      assert(!await page.getByRole('dialog', { name: '证据助手' }).isVisible());
      const focused = await page.evaluate(() => document.activeElement.textContent);
      assert(focused.includes('证据助手'));
    });
    assert.equal(report.console.length, 0, JSON.stringify(report.console));
    report.status = report.cases.every(item => item.status === 'PASS') ? 'PASS' : 'FAIL';
  } catch (error) {
    report.status = 'FAIL'; report.error = error.message;
    if (page) await screenshot('failure').catch(() => {});
  } finally {
    for (const id of created) await api(`/assistant/providers/${encodeURIComponent(id)}`, { method: 'DELETE' }).catch(() => {});
    if (browser) await browser.close();
    report.elapsed_seconds = (performance.now() - started) / 1000;
    report.completed_at = new Date().toISOString();
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    if (report.status !== 'PASS') process.exitCode = 1;
  }
})();
