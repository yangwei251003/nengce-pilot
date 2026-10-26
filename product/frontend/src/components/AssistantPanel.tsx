import { useEffect, useRef, useState } from 'react';
import type { AssistantRequest, AssistantStatus, ChatMessage, Citation, Config, ModelProfile, Result } from '../types';
import { active, forget, readSaved, request, save } from '../api';
import { Icon } from '../icons';
import { Badge, Button, Empty, Notice } from '../ui';
import { ModelSettings } from './ModelSettings';
type Session = {
    id: string;
    created_at: string;
    messages: ChatMessage[];
};
export function AssistantPanel({ result, status, onCite, onDraft, open = true }: {
    result?: Result;
    status: AssistantStatus;
    onCite: (citation: Citation) => void;
    onDraft: (patch: Partial<Config>) => void;
    open?: boolean;
}) {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [sessions, setSessions] = useState<Session[]>([]);
    const [sessionId, setSessionId] = useState('');
    const [question, setQuestion] = useState('');
    const [provider, setProvider] = useState('local');
    const [profiles, setProfiles] = useState<ModelProfile[]>([]);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [job, setJob] = useState<AssistantRequest | null>(null);
    const [sending, setSending] = useState(false);
    const [error, setError] = useState('');
    const [cancelPending, setCancelPending] = useState(false);
    const lock = useRef(false);
    const generation = useRef(0);
    const completed = useRef('');
    const privateRun = result?.dataset?.public_data !== true;
    const busy = sending || active(job);
    const profile = profiles.find(item => item.id === provider);
    const builtin = status.builtin_providers?.find(item => item.id === provider);
    const isLocalEvidence = provider === 'local';
    const configured = isLocalEvidence ? status.local_available === true : profile ? (profile.kind === 'local' || profile.has_key && profile.billing_ack) : builtin?.available ?? (provider === 'zhipu' ? status.available : status.manual_backups?.find(item => item.provider === provider)?.available === true);
    const privateBlocked = privateRun && !isLocalEvidence;
    const selectedModel = isLocalEvidence ? '本机证据解读 · 无语言模型' : profile?.model || builtin?.model || (provider === 'zhipu' ? status.model : status.manual_backups?.find(item => item.provider === provider)?.model) || '模型未配置';
    useEffect(() => {
        if (provider.startsWith('profile-') && !profiles.some(item => item.id === provider)) setProvider('local');
    }, [profiles]);
    useEffect(() => {
        const token = ++generation.current;
        setMessages([]);
        setSessionId('');
        setSessions([]);
        setJob(null);
        setError('');
        completed.current = '';
        if (!result)
            return;
        const run = result.api_run_id || result.run_id;
        request<{
            sessions: Session[];
        }>(`/assistant/sessions?run_id=${encodeURIComponent(run)}`).then(async (value) => {
            if (generation.current !== token)
                return;
            setSessions(value.sessions);
            if (value.sessions[0]) {
                setSessionId(value.sessions[0].id);
                setMessages(value.sessions[0].messages || []);
            }
            const pending = readSaved(`assistant.request.${run}`);
            if (pending) {
                const restored = await request<AssistantRequest>(`/assistant/requests/${encodeURIComponent(pending)}`);
                if (generation.current === token)
                    setJob(restored);
            }
        }).catch(issue => { if (generation.current === token)
            setError(`会话读取失败：${String(issue)}`); });
    }, [result?.run_id]);
    useEffect(() => {
        if (!job || !result)
            return;
        const token = generation.current;
        if (!active(job)) {
            if (job.status === 'succeeded' && completed.current !== job.request_id) {
                completed.current = job.request_id;
                if (job.session_id)
                    request<Session>(`/assistant/sessions/${encodeURIComponent(job.session_id)}`).then(session => {
                        if (generation.current === token && session.id === job.session_id) {
                            setMessages(session.messages);
                            setSessionId(session.id);
                            setSessions(previous => [{ ...session, created_at: session.created_at || '' }, ...previous.filter(item => item.id !== session.id)]);
                        }
                    }).catch(issue => { if (generation.current === token)
                        setError(String(issue)); });
            }
            if (job.status === 'failed')
                setError(job.message || '助手未生成经过核验的回答。');
            forget(`assistant.request.${result.api_run_id || result.run_id}`);
            setCancelPending(false);
            return;
        }
        let stopped = false;
        let timer: ReturnType<typeof setTimeout>;
        async function poll() {
            try {
                const next = await request<AssistantRequest>(`/assistant/requests/${encodeURIComponent(job!.request_id)}`);
                if (stopped)
                    return;
                setJob(next);
                setError('');
                if (active(next))
                    timer = setTimeout(poll, 1000);
            }
            catch (issue) {
                if (!stopped) {
                    setError(`助手进度暂不可用：${String(issue)}。正在重连。`);
                    timer = setTimeout(poll, 3000);
                }
            }
        }
        timer = setTimeout(poll, 650);
        return () => { stopped = true; clearTimeout(timer); };
    }, [job?.request_id, job?.status, result?.run_id]);
    async function send() {
        if (!result || !question.trim() || busy || lock.current || privateBlocked || !configured)
            return;
        lock.current = true;
        setSending(true);
        setError('');
        const text = question.trim(), token = generation.current;
        try {
            const next = await request<AssistantRequest>('/assistant/chat', { method: 'POST', body: JSON.stringify({ run_id: result.api_run_id || result.run_id, question: text, provider, messages: [...messages.map(({ role, content }) => ({ role, content })), { role: 'user', content: text }].slice(-30), session_id: sessionId || undefined }) });
            if (token !== generation.current)
                return;
            setSessionId(next.session_id || '');
            setJob(next);
            setQuestion('');
            setMessages(previous => [...previous, { role: 'user', content: text }]);
            save(`assistant.request.${result.api_run_id || result.run_id}`, next.request_id);
        }
        catch (issue) {
            if (token === generation.current)
                setError(`提问未确认：${String(issue)}。请先查看已有会话，避免重复请求。`);
        }
        finally {
            lock.current = false;
            setSending(false);
        }
    }
    if (!result)
        return <div className={`assistant-panel${settingsOpen ? ' is-configuring' : ''}`}><ModelSettings active={open} disabled={busy} onProfiles={setProfiles} onOpenChange={setSettingsOpen}/><Empty compact title="先完成一次计算">助手只讨论已保存的成功运行。参数草稿与尚未产生的费用不会被包装成计算结果。可以先连接你的模型，或计算后直接使用本机证据解读。</Empty></div>;
    return <div className={`assistant-panel${settingsOpen ? ' is-configuring' : ''}`}>
    <div className="assistant-context">
    <span className="round-icon">
    <Icon name="spark"/>
    </span>
    <div>
    <strong>绑定本次运行的证据助手</strong>
    <small>{result.run_id} · {selectedModel}</small>
    </div>
    <Badge tone={configured ? 'green' : 'amber'}>{configured ? isLocalEvidence ? '本机就绪' : '已配置' : '未配置'}</Badge>
    </div>
    <p className="caption">{isLocalEvidence ? '本机查询费用、对照、风险和参数草稿，支持这些任务的连续追问；超出已实现的证据查询范围会明确说明。它不是语言模型，数据不离开本机。' : '自由问答由所选模型理解；仅发送公开案例必要摘要。数值与引用由本机证据核验，连接状态以实际调用为准。'}</p>
    {!isLocalEvidence && <Notice tone="warning">在线模型为试用能力：完整业务问答验收尚未达标，请结合引用复核。免费服务可能过载，不会自动切换到自有或付费服务。</Notice>}
    <label className="field provider-choice">本次提问方式<select aria-label="助手模型平台" value={provider} disabled={busy} onChange={event => { setProvider(event.target.value); setError(''); }}>
    <option value="local">本机证据解读 · 无需 API</option>
    <option value="zhipu">智谱 · GLM-4.7-Flash（免费）</option>{status.manual_backups?.map(backup => <option key={backup.provider} value={backup.provider}>{backup.provider === 'openrouter' ? 'OpenRouter · Qwen3.8-27B 免费备选' : `${backup.name || backup.provider} · ${backup.model}`}</option>)}{profiles.map(item => <option key={item.id} value={item.id}>{item.name} · {item.model}{item.kind === 'cloud' ? '（自有云 API）' : '（本机 API）'}</option>)}</select>
    </label>
    <ModelSettings active={open} disabled={busy} onProfiles={setProfiles} onOpenChange={setSettingsOpen}/>
    {profile?.kind === 'cloud' && <p className="caption model-cost-disclosure">已选择你的云服务；费用由该账户承担。仅在点击发送时调用，不自动回退。</p>}
    {status.disclosure && <details>
        <summary>平台与数据使用说明</summary>
        <p className="caption">{status.disclosure}</p>
        </details>}
    {privateBlocked && <Notice tone="warning">本次为私人或未经公开性核验的数据，模型提问已停用。请选择本机证据解读；图表、回放与导出仍可使用。</Notice>}
    {!configured && <Notice>所选模型尚未配置好。可以使用本机证据解读，或在模型设置中保存并测试自己的服务。核心计算可独立使用。</Notice>}
    <div className="session-tools">
    <label>已保存会话<select aria-label="助手历史会话" value={sessionId} disabled={busy} onChange={async (event) => {
            const id = event.target.value;
            const token = ++generation.current;
            if (!id) {
                setSessionId('');
                setMessages([]);
                setJob(null);
                return;
            }
            try {
                const session = await request<Session>(`/assistant/sessions/${encodeURIComponent(id)}`);
                if (token === generation.current) {
                    setSessionId(id);
                    setMessages(session.messages);
                    setJob(null);
                }
            }
            catch (issue) {
                if (token === generation.current)
                    setError(String(issue));
            }
        }}>
    <option value="">新会话</option>{!sessions.some(session => session.id === sessionId) && sessionId && <option value={sessionId}>当前会话</option>}{sessions.map(session => <option key={session.id} value={session.id}>{session.created_at.slice(0, 16).replace('T', ' ')} · {session.id.slice(-6)}</option>)}</select>
    </label>
    </div>
    <div className="chat-messages" aria-live="polite">{messages.length === 0 && <div className="chat-starter">
        <h3>从一个具体问题开始</h3>{['本次节费中，有多少可以归因于学习预测？', '定位最大动作裁剪，并解释可能原因。', '把电池容量调整为 120 kWh，先给我参数草稿。'].map(prompt => <button key={prompt} disabled={privateBlocked || busy || !configured} onClick={() => setQuestion(prompt)}>{prompt}<Icon name="arrow" size={15}/>
            </button>)}</div>}{messages.map((message, index) => <article key={index} className={`chat-message chat-message--${message.role}`}>
        <span className="chat-author">{message.role === 'user' ? '你' : '能策 · 证据助手'}{message.model && <Badge>{message.model}</Badge>}</span>{message.content.split('\n\n').map((paragraph, n) => <p key={n}>{paragraph}</p>)}{message.citations?.length ? <div className="citations">{message.citations.map(citation => <button key={citation.id} onClick={() => onCite(citation)}>
                <Icon name="link" size={12}/>{citation.label}</button>)}</div> : null}{message.draft_patch && <div className="assistant-draft">
            <strong>参数建议 · 尚未计算</strong>
            <pre>{JSON.stringify(message.draft_patch, null, 2)}</pre>
            <Button variant="secondary" onClick={() => onDraft(message.draft_patch!)}>放入草稿并审查</Button>
            </div>}{message.disclosure && <details>
            <summary>模型与数据说明</summary>
            <p className="caption">{message.disclosure}</p>
            </details>}</article>)}</div>
    {busy && <div className="assistant-progress" role="status">
        <span className="spinner"/>
        <span>{sending ? '正在提交问题' : job?.message || '等待助手服务'}</span>
        <button className="text-button" disabled={sending || cancelPending} onClick={async () => { if (!job)
            return; setCancelPending(true); try {
            setJob(await request<AssistantRequest>(`/assistant/requests/${job.request_id}/cancel`, { method: 'POST' }));
        }
        catch (issue) {
            setCancelPending(false);
            setError(String(issue));
        } }}>{cancelPending ? '正在取消' : '取消'}</button>
        </div>}
    {job?.status === 'cancelled' && <p className="caption">本次提问已取消，迟到的回答不会加入结果。</p>}
    {error && <Notice tone="danger">{error}</Notice>}
    <form className="chat-composer" onSubmit={event => { event.preventDefault(); void send(); }}>
    <label className="sr-only" htmlFor="assistant-question">向证据助手提问</label>
    <textarea id="assistant-question" maxLength={2000} value={question} onChange={event => setQuestion(event.target.value)} placeholder="询问费用、风险、预测，或提出参数草稿…" disabled={privateBlocked || !configured}/>
    <div>
    <span className="caption">参数建议需要审查后另行运行</span>
    <Button type="submit" disabled={busy || !question.trim() || privateBlocked || !configured}>发送<Icon name="arrow" size={15}/>
    </Button>
    </div>
    </form>
  </div>;
}
