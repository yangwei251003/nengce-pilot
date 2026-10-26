"""Zero-price allowlist; credentials stay outside the project and model context."""
from pathlib import Path
import os
import re
import json
import time
import httpx

MODEL = 'glm-4.7-flash'
MODELS = {'zhipu':MODEL,'openrouter':'qwen/qwen3.8-27b:free'}
URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'


def safe_message(message, key=''):
    """Upstream fields are untrusted; even a provider echo cannot expose auth."""
    if not isinstance(message,dict):
        raise ValueError('模型返回消息结构无效')
    def scrub(value):
        if isinstance(value,str):return value.replace(key,'[已移除凭据]') if key else value
        if isinstance(value,list):return [scrub(x) for x in value]
        if isinstance(value,dict):return {k:scrub(v) for k,v in value.items()}
        return value
    return scrub({k:v for k,v in message.items() if k in {'role','content','tool_calls'}})


def safe_usage(value):
    if not isinstance(value,dict):return {}
    return {k:v for k,v in value.items() if k in {'prompt_tokens','completion_tokens','total_tokens'}
            and isinstance(v,int) and not isinstance(v,bool) and 0<=v<=1_000_000_000}


def credential(provider='zhipu'):
    configured_path = os.environ.get('NENGCE_CREDENTIAL_FILE')
    if not configured_path:
        raise ValueError('未显式配置 NENGCE_CREDENTIAL_FILE；内置云模型未启用')
    path = Path(configured_path)
    try:
        value = path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        raise ValueError('未找到可读取的外部模型配置；请在本机配置凭据文件') from None
    pattern = r'sk-or-v1-[A-Za-z0-9_-]+' if provider == 'openrouter' else r'(?<![A-Za-z0-9])([A-Za-z0-9]{16,}\.[A-Za-z0-9_-]{8,})(?![A-Za-z0-9])'
    match = re.search(pattern, value)
    if not match:
        raise ValueError('外部配置中未识别所选平台的密钥格式')
    return match.group(0)


def status():
    try:
        credential()
        configured = True
    except ValueError:
        configured = False
    try:
        credential('openrouter')
        backup_configured=True
    except ValueError:
        backup_configured=False
    from . import provider_profiles
    try:
        rows=provider_profiles.profiles()
        profile_message=None
    except ValueError as error:
        rows=[]
        profile_message=str(error)
    return {'available':configured,'provider':'智谱','model':MODEL,'public_only':True,
            'local_available':True,'default_provider':'local','profiles':rows,
            'secret_storage':'windows_dpapi_user','profile_message':profile_message,
            'builtin_providers':[{'id':'zhipu','name':'智谱免费模型','model':MODEL,'available':configured,'connection_verified':False},
                                 {'id':'openrouter','name':'OpenRouter 固定免费备选','model':MODELS['openrouter'],'available':backup_configured,'connection_verified':False}],
            'connection_verified':False,'manual_backups':[{'provider':'openrouter','model':MODELS['openrouter'],'name':'OpenRouter 固定免费备选','available':backup_configured}],
            'message':'外部凭据已配置；实际可用性以调用为准' if configured else '请配置外部凭据文件',
            'disclosure':'仅发送公开案例必要摘要；平台条款允许匿名化数据用于训练。核心计算留在本机。'}


def complete(messages, tools=None, cancelled=lambda:False, model=MODEL, provider='zhipu'):
    if provider.startswith('profile-'):
        from . import provider_profiles
        row=provider_profiles.get(provider)
        if model != row['model']:
            raise ValueError('自有模型配置在请求期间已改变；请重新提问，未切换模型')
        return provider_profiles.complete(provider,messages,tools,cancelled)
    if provider not in MODELS:
        raise ValueError('未授权的模型平台')
    if provider == 'zhipu' and model != MODEL:
        raise ValueError('仅允许已核验零单价的固定模型，禁止付费回退')
    if provider == 'openrouter' and model != 'qwen/qwen3.8-27b:free':
        raise ValueError('仅允许手动指定的固定免费备选')
    if cancelled():
        raise InterruptedError('已取消助手请求')
    key = credential(provider)
    url = URL if provider == 'zhipu' else 'https://openrouter.ai/api/v1/chat/completions'
    payload = {'model':model,'messages':messages,'temperature':0.1,'max_tokens':900,'stream':False}
    if provider == 'zhipu':
        payload['thinking']={'type':'disabled'}
        # Official text-completion schema supports JSON output alongside tools.
        # Local fact/semantic validation remains mandatory; JSON is only syntax.
        payload['response_format']={'type':'json_object'}
    else:
        # Live catalog is checked before every use. Never substitute a paid model.
        catalog=httpx.get('https://openrouter.ai/api/v1/models',timeout=20).json()
        entry=next((x for x in catalog.get('data',[]) if x['id']==model),None)
        if not entry or any(float(entry['pricing'].get(k,1 if k in ('prompt','completion') else 0)) != 0 for k in ('prompt','completion','request','internal_reasoning')):
            raise ValueError('免费备选的零单价无法确认，调用已停止')
        payload['provider']={'allow_fallbacks':False}
        if entry.get('reasoning',{}).get('mandatory') is False:
            payload['reasoning']={'enabled':False,'exclude':True}
    if tools:
        payload.update(tools=tools,tool_choice='auto')
    started=time.perf_counter()
    # Provider text is never reflected on errors, so no upstream request/secret can leak.
    with httpx.Client(timeout=httpx.Timeout(70,connect=15)) as client:
        for attempt in range(3):
            if cancelled():
                raise InterruptedError('已取消助手请求')
            response=client.post(url,headers={'Authorization':f'Bearer {key}'},json=payload)
            if response.status_code not in (429,502,503) or attempt==2:
                break
            # Bounded retry of the same free model. Poll cancellation during backoff.
            deadline=time.monotonic()+[2,6][attempt]
            while time.monotonic()<deadline:
                if cancelled():
                    raise InterruptedError('已取消助手请求')
                time.sleep(.1)
    if cancelled():
        key=None
        raise InterruptedError('已取消助手请求；迟到响应已丢弃')
    if response.status_code != 200:
        key=None
        try:
            code=re.sub(r'[^A-Za-z0-9_-]','',str(response.json().get('error',{}).get('code','unknown')))[:40]
        except Exception:
            code='unknown'
        raise ValueError(f'模型服务未完成请求（HTTP {response.status_code}，代码 {code}）；未切换模型或付费服务')
    data=response.json()
    if not data.get('choices'):
        raise ValueError('模型返回空结果')
    message=safe_message(data['choices'][0]['message'],key)
    key=None
    return {'message':message,'usage':safe_usage(data.get('usage',{})),
            'elapsed_seconds':time.perf_counter()-started,'model':model}
