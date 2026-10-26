"""User-owned OpenAI-compatible endpoints. Secrets never enter project outputs.

Profiles are encrypted with Windows DPAPI for the current OS user. A profile
does not authorize sending private datasets. Cloud use needs explicit billing
acknowledgement; it is never an automatic fallback from the bundled free model.
"""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

import httpx

_LOCK = threading.RLock()


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('用户模型配置仅在已验收的 Windows DPAPI 环境启用')
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    target = Blob()
    lib = ctypes.WinDLL('crypt32', use_last_error=True)
    name = 'CryptUnprotectData' if decrypt else 'CryptProtectData'
    fn = getattr(lib, name)
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    # UI_FORBIDDEN: no credential prompt, and no machine-wide decryption flag.
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('用户模型配置加密或解密失败；未降级为明文存储')
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(target.pbData)


def store_path():
    default = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData'/'Local')))/'NengcePilotOpenSource'/'providers.dpapi'
    path = Path(os.environ.get('NENGCE_PROFILE_STORE', str(default))).resolve()
    project = Path(__file__).resolve().parents[3]
    if path == project or project in path.parents:
        raise ValueError('用户模型配置必须保存在项目与交付目录之外')
    return path


def _load():
    path = store_path()
    if not path.exists():
        return []
    try:
        rows = json.loads(crypt(path.read_bytes(), decrypt=True).decode('utf-8'))
        if not isinstance(rows, list):
            raise ValueError()
        return rows
    except (OSError, UnicodeError, ValueError, TypeError):
        raise ValueError('用户模型配置不可读取；未覆盖损坏或其他用户的配置') from None


def _save(rows):
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = crypt(json.dumps(rows, ensure_ascii=False).encode('utf-8'))
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_bytes(encrypted)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def public(row):
    return {**{k:v for k,v in row.items() if k != 'api_key'}, 'has_key':bool(row.get('api_key'))}


def profiles():
    with _LOCK:
        return [public(row) for row in _load()]


def endpoint(base_url, kind):
    if not isinstance(base_url, str) or len(base_url) > 500:
        raise ValueError('API 地址格式无效')
    try:
        parts = urlsplit(base_url.strip())
        host = parts.hostname
        _ = parts.port
    except ValueError:
        raise ValueError('API 地址格式无效') from None
    if not host or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('API 地址不得包含用户名、密钥、查询参数或片段')
    loopback = host.lower() == 'localhost'
    try:
        address = ipaddress.ip_address(host)
        loopback = address.is_loopback
        private = not address.is_global
    except ValueError:
        private = host.lower() in {'localhost', 'metadata.google.internal'} or host.lower().endswith(('.local', '.internal'))
    if kind == 'local':
        if not loopback or parts.scheme not in {'http', 'https'}:
            raise ValueError('本地模型只允许明确的 localhost 或回环 IP 地址')
    elif kind == 'cloud':
        if parts.scheme != 'https' or private:
            raise ValueError('云模型需使用 HTTPS 公网地址；本机接口请选择本地模型')
    else:
        raise ValueError('模型类型须为 cloud 或 local')
    path = parts.path.rstrip('/')
    if '\\' in path or re.search(r'/\.\.?(/|$)', path):
        raise ValueError('API 路径格式无效')
    if not path.endswith('/chat/completions'):
        path += '/chat/completions'
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))


def save(body, ident=None):
    if not isinstance(body, dict) or set(body)-{'name','kind','base_url','model','api_key','billing_ack','max_tokens'}:
        raise ValueError('模型配置字段无效')
    for field, limit in [('name',80),('base_url',500),('model',160)]:
        if not isinstance(body.get(field),str) or not body[field].strip() or len(body[field]) > limit:
            raise ValueError('模型名称、API 地址或模型标识缺失或超长')
    if any(char in body['model'] for char in '\r\n'):
        raise ValueError('模型标识格式无效')
    kind = body.get('kind')
    endpoint(body['base_url'], kind)
    key = body.get('api_key')
    if key is not None and (not isinstance(key,str) or len(key)>8192 or any(c in key for c in '\r\n')):
        raise ValueError('密钥格式无效；未保存')
    tokens = body.get('max_tokens',1200)
    if isinstance(tokens,bool) or not isinstance(tokens,int) or not 256<=tokens<=4096:
        raise ValueError('输出上限须在 256 到 4096 token 之间')
    if not isinstance(body.get('billing_ack',False),bool):
        raise ValueError('费用确认须为布尔值')
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        rows = _load()
        old = next((x for x in rows if x['id']==ident),None) if ident else None
        if ident and old is None:
            raise ValueError('模型配置不存在')
        if not old and len(rows)>=10:
            raise ValueError('最多保存十个自有模型配置')
        row = {'id':ident or 'profile-'+uuid.uuid4().hex[:12],
               'name':body['name'].strip(), 'kind':kind, 'base_url':body['base_url'].strip().rstrip('/'),
               'model':body['model'].strip(), 'api_key':key if key is not None else (old or {}).get('api_key',''),
               'billing_ack':body.get('billing_ack',False), 'max_tokens':tokens,
               'created_at':(old or {}).get('created_at',now), 'updated_at':now}
        rows = [x for x in rows if x['id'] != row['id']]+[row]
        _save(rows)
        return public(row)


def remove(ident):
    with _LOCK:
        rows = _load()
        if not any(row['id']==ident for row in rows):
            raise ValueError('模型配置不存在')
        _save([row for row in rows if row['id'] != ident])
    return {'deleted':True}


def get(ident):
    if not re.fullmatch(r'profile-[a-f0-9]{12}', ident):
        raise ValueError('模型配置编号无效')
    with _LOCK:
        row = next((x for x in _load() if x['id']==ident),None)
    if row is None:
        raise ValueError('模型配置不存在')
    return row


def require_call(row):
    endpoint(row['base_url'], row['kind'])
    if row['kind']=='cloud' and (not row.get('billing_ack') or not row.get('api_key')):
        raise ValueError('云模型调用需配置密钥并明确确认费用由你的服务商账户承担；未发出请求')


def complete(ident, messages, tools=None, cancelled=lambda:False):
    row = get(ident)
    require_call(row)
    if cancelled():
        raise InterruptedError('已取消助手请求')
    headers = {'Authorization':'Bearer '+row['api_key']} if row.get('api_key') else {}
    payload = {'model':row['model'],'messages':messages,'temperature':0.1,
               'max_tokens':row['max_tokens'],'stream':False}
    if tools:
        payload.update(tools=tools,tool_choice='auto')
    started = time.perf_counter()
    # No redirects, retries, model substitutions, searches or paid fallback.
    try:
        with httpx.Client(timeout=httpx.Timeout(70,connect=12),follow_redirects=False,trust_env=False) as client:
            response = client.post(endpoint(row['base_url'],row['kind']),headers=headers,json=payload)
    except httpx.HTTPError:
        raise ValueError('自有模型连接失败；请检查地址与服务状态，核心计算和本机证据解读可继续使用') from None
    if cancelled():
        raise InterruptedError('已取消助手请求；迟到响应已丢弃')
    if response.status_code != 200:
        raise ValueError(f'自有模型服务 HTTP {response.status_code}；未反射服务商响应内容，未切换模型')
    if len(response.content)>200000:
        raise ValueError('自有模型响应超过允许大小；未发布内容')
    try:
        data = response.json()
        message = data['choices'][0]['message']
        if not isinstance(message,dict):
            raise ValueError()
    except (ValueError,TypeError,KeyError,IndexError):
        raise ValueError('自有模型未返回兼容的 chat/completions 结构') from None
    from .provider import safe_message, safe_usage
    return {'message':safe_message(message,row.get('api_key','')),'usage':safe_usage(data.get('usage',{})),
            'elapsed_seconds':time.perf_counter()-started,'model':row['model']}


def test(ident):
    row = get(ident)
    response = complete(ident,[{'role':'user','content':'Connection test. Reply OK. No tools or business data.'}])
    return {'ok':bool(response['message'].get('content')), 'model':row['model'], 'kind':row['kind'],
            'elapsed_seconds':response['elapsed_seconds'],
            'message':'连接测试收到兼容响应；尚未证明工具调用、数值引用与业务问答质量。测试未包含业务数据。'}
