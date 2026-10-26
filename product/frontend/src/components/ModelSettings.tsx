import { useEffect, useRef, useState } from 'react';
import { request } from '../api';
import type { ModelConnectionTest, ModelProfile, ModelProfilePage } from '../types';
import { Badge, Button, Notice } from '../ui';
import { Icon } from '../icons';

type ProfileDraft = {
  name: string;
  kind: 'cloud' | 'local';
  base_url: string;
  model: string;
  api_key: string;
  billing_ack: boolean;
  max_tokens: number;
};
const emptyDraft = (): ProfileDraft => ({ name: '', kind: 'cloud', base_url: '', model: '', api_key: '', billing_ack: false, max_tokens: 1200 });

export function ModelSettings({ active = true, disabled, onProfiles, onOpenChange }: { active?: boolean; disabled?: boolean; onProfiles: (profiles: ModelProfile[]) => void; onOpenChange?: (open: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [editing, setEditing] = useState('');
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft);
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [test, setTest] = useState<ModelConnectionTest | null>(null);
  const alive = useRef(true);
  const actionLock = useRef(false);
  const loadGeneration = useRef(0);
  const callback = useRef(onProfiles);
  callback.current = onProfiles;
  const openCallback = useRef(onOpenChange);
  openCallback.current = onOpenChange;
  const selected = profiles.find(profile => profile.id === editing);
  const locked = Boolean(disabled || pending);
  const dirty = Boolean(selected && (draft.name !== selected.name || draft.kind !== selected.kind || draft.base_url !== selected.base_url || draft.model !== selected.model || draft.billing_ack !== selected.billing_ack || draft.max_tokens !== selected.max_tokens || draft.api_key));

  async function load() {
    const token = ++loadGeneration.current;
    const response = await request<ModelProfilePage>('/assistant/providers');
    if (!alive.current || token !== loadGeneration.current) return;
    setProfiles(response.profiles);
    callback.current(response.profiles);
  }
  useEffect(() => {
    alive.current = true;
    load().catch(() => { if (alive.current) setError('模型配置未能读取。请重试；本机证据解读仍可独立使用。'); });
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    if (!active) {
      setOpen(false);
      setDraft(previous => ({ ...previous, api_key: '' }));
    }
  }, [active]);
  useEffect(() => { openCallback.current?.(open); }, [open]);

  function edit(profile?: ModelProfile) {
    setEditing(profile?.id || '');
    setDraft(profile ? { name: profile.name, kind: profile.kind, base_url: profile.base_url, model: profile.model, api_key: '', billing_ack: profile.billing_ack, max_tokens: profile.max_tokens } : emptyDraft());
    setError(''); setNotice(''); setTest(null);
  }
  function close() {
    setOpen(false);
    setDraft(previous => ({ ...previous, api_key: '' }));
  }
  async function saveProfile() {
    if (locked || actionLock.current) return;
    setError(''); setNotice(''); setTest(null);
    if (draft.kind === 'cloud' && !draft.billing_ack) { setError('请确认自有服务的费用与公开摘要发送范围，再保存云端配置。'); return; }
    if (draft.kind === 'cloud' && !draft.api_key.trim() && !selected?.has_key) { setError('云端模型需要 API 密钥。密钥只会交给本机后端加密保存。'); return; }
    if (!draft.name.trim() || !draft.model.trim() || !draft.base_url.trim() || !Number.isInteger(draft.max_tokens) || draft.max_tokens < 256 || draft.max_tokens > 4096) { setError('请填写名称、API 地址和精确模型标识；输出上限需为 256–4096 的整数。'); return; }
    actionLock.current = true;
    setPending('save');
    // The secret is sent once to the local backend; it is never persisted by the browser.
    const payload: Omit<ProfileDraft, 'api_key'> & { api_key?: string } = { name: draft.name.trim(), kind: draft.kind, base_url: draft.base_url.trim(), model: draft.model.trim(), billing_ack: draft.kind === 'cloud' && draft.billing_ack, max_tokens: draft.max_tokens };
    if (draft.api_key.trim()) payload.api_key = draft.api_key.trim();
    setDraft(previous => ({ ...previous, api_key: '' }));
    try {
      const profile = await request<ModelProfile>(editing ? `/assistant/providers/${encodeURIComponent(editing)}` : '/assistant/providers', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      await load();
      if (alive.current) { edit(profile); setNotice('配置已保存。连接状态需由你点击测试确认；保存不会发起模型调用。'); }
    } catch { if (alive.current) setError('保存失败。请检查地址、模型名及网络；密钥输入已清空，若需重试请重新填写。'); }
    finally { actionLock.current = false; if (alive.current) setPending(''); }
  }
  async function testConnection() {
    if (!editing || locked || actionLock.current) return;
    actionLock.current = true;
    setPending('test'); setError(''); setNotice(''); setTest(null);
    try {
      const value = await request<ModelConnectionTest>(`/assistant/providers/${encodeURIComponent(editing)}/test`, { method: 'POST' });
      if (alive.current) setTest(value);
    } catch { if (alive.current) setError('连接测试未成功。请核对服务地址、模型能力与账户额度；本机计算不受影响。'); }
    finally { actionLock.current = false; if (alive.current) setPending(''); }
  }
  async function removeProfile() {
    if (!editing || locked || actionLock.current) return;
    actionLock.current = true;
    setPending('delete'); setError(''); setNotice('');
    try {
      await request(`/assistant/providers/${encodeURIComponent(editing)}`, { method: 'DELETE' });
      await load();
      if (alive.current) { edit(); setNotice('模型配置及其保存的密钥已移除。'); }
    } catch { if (alive.current) setError('配置未能移除，请重试。'); }
    finally { actionLock.current = false; if (alive.current) setPending(''); }
  }
  async function clearKey() {
    if (!selected || locked || actionLock.current) return;
    actionLock.current = true;
    setPending('key'); setError(''); setNotice(''); setTest(null);
    try {
      await request(`/assistant/providers/${encodeURIComponent(editing)}`, { method: 'PUT', body: JSON.stringify({ name: selected.name, kind: selected.kind, base_url: selected.base_url, model: selected.model, billing_ack: selected.billing_ack, max_tokens: selected.max_tokens, api_key: '' }) });
      await load();
      if (alive.current) { setDraft(previous => ({ ...previous, api_key: '' })); setNotice('保存的密钥已清除。云端提问将停用，直到重新配置密钥。'); }
    } catch { if (alive.current) setError('密钥清除未确认，请重试。'); }
    finally { actionLock.current = false; if (alive.current) setPending(''); }
  }

  return <section className="model-settings" aria-label="自定义模型设置">
    <button type="button" className="model-settings-toggle" aria-expanded={open} aria-controls="model-settings-content" onClick={() => open ? close() : setOpen(true)}>
      <span><Icon name="sliders" size={16}/>自定义模型与 API</span><span>{profiles.length ? `${profiles.length} 个配置` : '连接你的模型'}<Icon name="arrow" size={14}/></span>
    </button>
    {open && <div id="model-settings-content" className="model-settings-content">
      <p className="caption">支持 OpenAI 兼容接口。可连接自有云服务，或本机 localhost 模型服务。密钥由本机后端按当前 Windows 用户加密保存，页面不会读回密钥。</p>
      <div className="model-profile-list" aria-label="已保存的模型配置">
        {profiles.map(profile => <button key={profile.id} type="button" disabled={locked} aria-pressed={editing === profile.id} className={editing === profile.id ? 'is-selected' : ''} onClick={() => edit(profile)}>
          <span><strong>{profile.name}</strong><small>{profile.model}</small></span><Badge tone={profile.kind === 'local' || profile.has_key ? 'green' : 'amber'}>{profile.kind === 'local' ? '本机服务' : profile.has_key ? '密钥已保存' : '缺少密钥'}</Badge>
        </button>)}
        <button type="button" className="new-model-profile" disabled={locked} onClick={() => edit()}>＋ 新增模型配置</button>
      </div>
      <form className="model-settings-form" onSubmit={event => { event.preventDefault(); void saveProfile(); }}>
        <fieldset disabled={locked}>
          <legend>{editing ? '编辑模型配置' : '新增模型配置'}</legend>
          <div className="model-settings-grid">
            <label className="field">显示名称<input aria-label="模型配置名称" maxLength={60} required value={draft.name} onChange={event => setDraft(previous => ({ ...previous, name: event.target.value }))} placeholder="我的方案助手"/></label>
            <label className="field">服务位置<select aria-label="模型服务位置" value={draft.kind} onChange={event => { setDraft(previous => ({ ...previous, kind: event.target.value as 'cloud' | 'local', billing_ack: false })); setTest(null); }}><option value="cloud">自有云 API</option><option value="local">本机模型 API</option></select></label>
          </div>
          <label className="field">API 基础地址<input aria-label="模型 API 基础地址" type="url" maxLength={500} required value={draft.base_url} onChange={event => setDraft(previous => ({ ...previous, base_url: event.target.value }))} placeholder={draft.kind === 'local' ? 'http://localhost:1234/v1' : 'https://你的服务地址/v1'}/></label>
          <label className="field">模型标识<input aria-label="模型标识" maxLength={160} required value={draft.model} onChange={event => setDraft(previous => ({ ...previous, model: event.target.value }))} placeholder="填写服务商的精确模型名"/></label>
          <label className="field">API 密钥{selected?.has_key && <small className="saved-key-note">已加密保存；留空可保留原密钥</small>}<input aria-label="模型 API 密钥" type="password" autoComplete="off" spellCheck={false} maxLength={4096} value={draft.api_key} onChange={event => setDraft(previous => ({ ...previous, api_key: event.target.value }))} placeholder={draft.kind === 'local' ? '本机服务可留空' : selected?.has_key ? '留空保留已保存的密钥' : '密钥仅交给本机后端'}/></label>
          <label className="field">单次输出上限 · tokens<input aria-label="模型输出 token 上限" type="number" min={256} max={4096} step={1} required value={draft.max_tokens} onChange={event => setDraft(previous => ({ ...previous, max_tokens: Number(event.target.value) }))}/></label>
          {draft.kind === 'cloud' ? <label className="model-billing-ack"><input type="checkbox" aria-label="确认自有模型费用与数据范围" checked={draft.billing_ack} onChange={event => setDraft(previous => ({ ...previous, billing_ack: event.target.checked }))}/><span>我确认使用自己的服务账户并承担其费用。在线提问只发送公开案例必要摘要；私人客户数据保持本机。系统不会自动切换到该服务。</span></label> : <p className="caption">本机地址限定 localhost / 回环地址。模型需支持工具调用，且你已在本机启动对应服务。</p>}
          {dirty && <p className="caption">配置已有未保存的更改，请先保存，再测试连接。</p>}
          <div className="model-settings-actions"><Button type="submit">{pending === 'save' ? '正在保存' : '保存模型配置'}</Button><Button variant="secondary" disabled={!editing || dirty} onClick={() => void testConnection()}>{pending === 'test' ? '测试连接中' : '测试已保存连接'}</Button></div>
          {editing && <div className="model-settings-remove">{selected?.has_key && <Button variant="ghost" onClick={() => void clearKey()}>清除保存的密钥</Button>}<Button variant="danger" onClick={() => void removeProfile()}>移除模型配置</Button></div>}
        </fieldset>
      </form>
      <p className="caption">连接测试仅发送简短测试提示，不包含业务数据。云端测试可能使用你账户的额度。修改后请先保存；测试只检查已保存配置。</p>
      {error && <Notice tone="danger">{error}<button type="button" className="text-button" disabled={locked} onClick={() => { setError(''); void load().catch(() => setError('模型配置仍无法读取，请检查本机服务。')); }}>重新读取配置</button></Notice>}
      {notice && <p className="model-setting-feedback" role="status">{notice}</p>}
      {test && !dirty && <Notice tone={test.ok ? 'info' : 'warning'}>{test.ok ? '连接测试通过' : '连接测试未通过'} · {test.model} · {test.elapsed_seconds.toFixed(2)} 秒<p className="caption">{test.message}</p></Notice>}
      <Button variant="ghost" className="model-settings-return" onClick={close}>返回证据提问<Icon name="arrow" size={14}/></Button>
    </div>}
  </section>;
}
