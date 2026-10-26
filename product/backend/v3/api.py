"""Local V3 API. Bounded compute queue, durable metadata, immutable evidence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import threading
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import RunConfig
from .store import Store
from .evidence import save_evidence
from . import assistant, provider, provider_profiles

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get('NENGCE_V3_OUTPUT', str(ROOT/'outputs'/'v3'))).resolve()
RUNS = OUTPUT/'runs'
RUNS.mkdir(parents=True, exist_ok=True)
store = Store(OUTPUT/'index.sqlite')
router = APIRouter(prefix='/api/v3', tags=['V3'])
compute_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='v3-compute')
chat_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='v3-assistant')
lock = threading.RLock()
futures = {}
cancel_flags = set()
TERMINAL = {'succeeded', 'failed', 'cancelled'}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def require(kind, ident):
    value = store.get(kind, ident)
    if value is None:
        raise HTTPException(404, '记录不存在')
    return value


def recover():
    for kind in ('run', 'chat'):
        for value in store.all(kind):
            if value['status'] not in TERMINAL:
                store.patch(kind, value['id'], status='failed', stage='interrupted',
                            message='服务重启中断了任务，请重新发起；未发布为成功结果', completed_at=now())


def read_result(ident):
    if not re.fullmatch(r'run-[a-f0-9]{12}',ident):
        raise HTTPException(404, '运行编号格式无效')
    record = require('run', ident)
    if record['status'] != 'succeeded':
        raise HTTPException(409, '运行尚未成功完成')
    folder = RUNS/ident
    try:
        manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        raw = (folder/'result.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest['sha256']['result.json']:
            raise ValueError('hash mismatch')
        return json.loads(raw)
    except (OSError, ValueError, KeyError):
        raise HTTPException(409, '冻结结果缺失或校验不一致，已阻止显示和导出') from None


def public_run(value, include_result=False):
    out = {k:v for k,v in value.items() if k not in ('body_hash','idempotency_key')}
    if include_result and value['status'] == 'succeeded':
        out['result'] = read_result(value['id'])
    return out


def check_key(kind, key, body_hash):
    existing = store.lookup_key(kind, key)
    if existing:
        previous, ident = existing
        if previous != body_hash:
            raise HTTPException(409, '同一请求标识已绑定其他配置，请创建新请求')
        return require(kind, ident)


def active_count(kind):
    return sum(x.get('status') not in TERMINAL for x in store.all(kind))


def run_record(config):
    body = config.model_dump(exclude={'idempotency_key'})
    ident = 'run-'+uuid.uuid4().hex[:12]
    return {'id':ident, 'run_id':ident, 'created_at':now(), 'status':'queued', 'stage':'queued',
            'progress':0, 'message':'等待本机计算', 'config':body, 'body_hash':digest(body),
            'idempotency_key':config.idempotency_key}


def execute(ident, config):
    def cancelled():
        return ident in cancel_flags or require('run', ident)['status'] == 'cancelled'

    def progress(stage, pct, message):
        with lock:
            if cancelled():
                raise InterruptedError('用户取消运行')
            store.patch('run', ident, status='running', stage=stage, progress=pct, message=message)

    try:
        if cancelled():
            return
        from .core import run_experiment
        result = run_experiment(config, ident, progress, cancelled)
        if cancelled():
            raise InterruptedError('用户取消运行')
        save_evidence(result, RUNS/ident)
        with lock:
            if cancelled():
                raise InterruptedError('用户取消运行；迟到结果未发布')
            selected = next(s for s in result['strategies'] if s['id']=='B2')
            store.patch('run', ident, status='succeeded', stage='succeeded', progress=100,
                        message='计算完成；请审阅比较有效性与数据边界', completed_at=now(),
                        brief={'strategy':'B2','total_cost':selected['total_cost'],
                               'comparison_valid':selected['comparison_valid']},
                        result_sha256=hashlib.sha256((RUNS/ident/'result.json').read_bytes()).hexdigest())
    except Exception as error:
        with lock:
            was_cancelled = cancelled() or isinstance(error, InterruptedError) or type(error).__name__ == 'Cancelled'
            store.patch('run', ident, status='cancelled' if was_cancelled else 'failed',
                        stage='cancelled' if was_cancelled else 'failed', completed_at=now(),
                        message='已取消；未发布成功结果' if was_cancelled else str(error)[:600], error_type=type(error).__name__)
    finally:
        with lock:
            cancel_flags.discard(ident)
            futures.pop(ident, None)


@router.get('/health')
def health():
    return {'status':'ok','version':'3.1.0','mode':'local_core_local_evidence_optional_public_summary_cloud','compute_workers':1,'max_unfinished_runs':20}


@router.get('/defaults')
def defaults():
    return RunConfig().model_dump()


@router.get('/datasets')
def datasets():
    from .data import list_datasets
    return {'datasets':list_datasets()}


class CSVImport(BaseModel):
    csv_text: str = Field(max_length=20_000_000)
    name: str = Field('用户授权负荷', max_length=160)
    timezone: str = Field('source-local-unknown', max_length=80)
    unit: str = Field('kW', max_length=16)
    authorized: bool = False
    interval_minutes: int = 60
    pv_column: str | None = None


@router.post('/datasets/import')
def upload(body: CSVImport):
    from .data import import_csv
    return import_csv(**body.model_dump())


@router.get('/protocols')
def protocols():
    paths = sorted((ROOT.parent/'docs').glob('protocol-v3*.md'))
    return {'protocols':[{'id':p.stem, 'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                          'text':p.read_text(encoding='utf-8')} for p in paths]}


@router.get('/datasets/{dataset_id}/quality')
def dataset_quality(dataset_id: str):
    from .quality import inspect_dataset
    try:
        return inspect_dataset(dataset_id)
    except ValueError as error:
        raise HTTPException(400,str(error)) from None


@router.get('/scenarios')
def scenarios():
    return {'scenarios':[{'id':key,'name':label} for key,label in [
        ('none','常态回放'),('load_up_20','实际负荷增加20%'),('peak_price_up_20','峰价增加20%'),
        ('forecast_bias_up_20','负荷预测偏高20%'),('pv_drop_30','实际光伏降低30%')]],
        'tariff':{'id':'illustrative-cny-v1','name':'人民币示例合同','real_customer_bill':False,
                  'demand_rule':'完整原生15分钟有效月份的实际最大进口功率×单价；每月只收一次'}}


@router.get('/runs')
def list_runs(limit: int = Query(30, ge=1, le=100), cursor: str | None = None):
    try:
        values, next_cursor = store.list('run', limit, cursor)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    return {'runs':[public_run(value) for value in values], 'next_cursor':next_cursor}


@router.post('/runs', status_code=202)
def start_run(config: RunConfig):
    value = run_record(config)
    with lock:
        previous = check_key('run', config.idempotency_key, value['body_hash'])
        if previous:
            return public_run(previous)
        if active_count('run') >= 20:
            raise HTTPException(429, '已有20个未终结任务，请等待或取消后再提交')
        store.reserve('run', config.idempotency_key, value['body_hash'], value)
        futures[value['id']] = compute_worker.submit(execute, value['id'], config)
    return public_run(value)


@router.get('/runs/{run_id}')
def get_run(run_id: str):
    return public_run(require('run', run_id), True)


@router.post('/runs/{run_id}/cancel')
def cancel_run(run_id: str):
    with lock:
        value = require('run', run_id)
        if value['status'] not in TERMINAL:
            cancel_flags.add(run_id)
            queued = value['status'] == 'queued'
            future = futures.get(run_id)
            if future and future.cancel():
                # A never-started future cannot execute its normal finally cleanup.
                futures.pop(run_id, None)
                cancel_flags.discard(run_id)
            value = store.patch('run', run_id, status='cancelled', stage='cancelled',
                                message='排队任务已取消' if queued else '已取消；正在丢弃本轮未完成计算', completed_at=now())
    return public_run(value)


@router.get('/runs/{run_id}/export/{format}')
def export_run(run_id: str, format: str):
    read_result(run_id)
    mapping = {'json':('result.json','application/json'), 'csv':('timeseries.csv','text/csv'), 'html':('report.html','text/html')}
    if format not in mapping:
        raise HTTPException(400, '仅支持JSON、CSV和HTML')
    name, media = mapping[format]
    folder = RUNS/run_id
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    file = folder/name
    if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != manifest['sha256'].get(name):
        raise HTTPException(409, '导出文件缺失或校验不一致')
    return FileResponse(file, media_type=media, filename=f'{run_id}-{name}')


class Batch(BaseModel):
    configs: list[RunConfig] = Field(min_length=1, max_length=20)
    idempotency_key: str | None = Field(None, max_length=128)


def public_batch(value):
    runs = [public_run(require('run', ident)) for ident in value['run_ids']]
    statuses = [r['status'] for r in runs]
    status = ('failed' if 'failed' in statuses else 'cancelled' if 'cancelled' in statuses else 'succeeded') if all(s in TERMINAL for s in statuses) else 'running'
    return {'batch_id':value['id'], 'created_at':value['created_at'], 'status':status, 'runs':runs,
            'scope':'每个站点独立计算；不是多站协同优化'}


@router.post('/batches', status_code=202)
def start_batch(body: Batch):
    body_hash = digest([c.model_dump(exclude={'idempotency_key'}) for c in body.configs])
    with lock:
        previous = check_key('batch', body.idempotency_key, body_hash)
        if previous:
            return public_batch(previous)
        if active_count('run') + len(body.configs) > 20:
            raise HTTPException(429, '批量任务超过剩余排队容量；未提交任何子任务')
        records = [run_record(c.model_copy(update={'idempotency_key':None})) for c in body.configs]
        value = {'id':'batch-'+uuid.uuid4().hex[:12], 'created_at':now(), 'run_ids':[r['id'] for r in records], 'body_hash':body_hash}
        # One SQLite transaction prevents a batch header with missing child records.
        with store.connect() as db:
            if body.idempotency_key:
                db.execute('INSERT INTO idempotency VALUES (?,?,?,?)', ('batch',body.idempotency_key,body_hash,value['id']))
            for kind,record in [('batch',value)]+[('run',r) for r in records]:
                db.execute('INSERT INTO records VALUES (?,?,?,?,?)', (kind,record['id'],record['created_at'],record.get('status'),json.dumps(record,ensure_ascii=False)))
        for record, config in zip(records, body.configs):
            futures[record['id']] = compute_worker.submit(execute, record['id'], config.model_copy(update={'idempotency_key':None}))
    return public_batch(value)


@router.get('/batches/{batch_id}')
def get_batch(batch_id: str):
    return public_batch(require('batch', batch_id))


@router.get('/assistant/status')
def assistant_status():
    return provider.status()


@router.get('/assistant/providers')
def assistant_providers():
    try:
        return {'profiles':provider_profiles.profiles(),'secret_storage':'windows_dpapi_user','default_provider':'local'}
    except ValueError as error:
        raise HTTPException(409,str(error)) from None


def profile_origin(request):
    # The app has no remote account/login system. Credential mutation is local
    # only, and an unrelated web origin cannot silently configure a paid API.
    from urllib.parse import urlsplit
    allowed={'localhost','127.0.0.1','::1','testclient'}
    if request.client and request.client.host not in allowed:
        raise HTTPException(403,'模型配置仅允许本机客户端操作')
    origin=request.headers.get('origin')
    if origin:
        try:host=urlsplit(origin).hostname
        except ValueError:host=None
        if host not in allowed:
            raise HTTPException(403,'拒绝来自其他网站的模型配置操作')


async def profile_body(request):
    profile_origin(request)
    if request.headers.get('content-type','').split(';')[0].strip() != 'application/json':
        raise HTTPException(400,'模型配置需要 JSON 请求')
    raw=await request.body()
    if len(raw)>30000:
        raise HTTPException(400,'模型配置请求超长；未保存')
    try:
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError()
        return value
    except (ValueError,UnicodeError):
        # Do not let Pydantic echo a credential-containing input in HTTP 422.
        raise HTTPException(400,'模型配置 JSON 格式无效；未保存') from None


@router.post('/assistant/providers')
async def add_provider(request: Request):
    body=await profile_body(request)
    try:return provider_profiles.save(body)
    except ValueError as error:raise HTTPException(400,str(error)) from None


@router.put('/assistant/providers/{profile_id}')
async def edit_provider(profile_id: str, request: Request):
    body=await profile_body(request)
    try:return provider_profiles.save(body,profile_id)
    except ValueError as error:raise HTTPException(400,str(error)) from None


@router.delete('/assistant/providers/{profile_id}')
def delete_provider(profile_id: str, request: Request):
    profile_origin(request)
    try:return provider_profiles.remove(profile_id)
    except ValueError as error:raise HTTPException(400,str(error)) from None


@router.post('/assistant/providers/{profile_id}/test')
def test_provider(profile_id: str, request: Request):
    profile_origin(request)
    try:return provider_profiles.test(profile_id)
    except ValueError as error:raise HTTPException(400,str(error)) from None


class Chat(BaseModel):
    run_id: str
    question: str | None = Field(None, max_length=2000)
    messages: list[dict] = Field(default_factory=list, max_length=30)
    session_id: str | None = None
    provider: str = Field('local',max_length=60)


def execute_chat(ident, result, question, session, provider_name='local'):
    def cancelled():
        return require('chat',ident)['status'] == 'cancelled'

    def progress(message):
        with lock:
            if cancelled():
                raise InterruptedError('已取消')
            store.patch('chat',ident,status='running',stage='evidence_query',message=message)

    try:
        progress('正在读取本机业务证据' if provider_name=='local' else '正在准备公开案例的必要摘要')
        response = assistant.answer(result, question, session['messages'], cancelled, progress, provider_name)
        with lock:
            if cancelled():
                return
            exchange = [{'role':'user','content':question}, {'role':'assistant','content':response['content'],
                        'citations':response.get('citations',[]), 'draft_patch':response.get('draft_patch'), 'mode':response.get('mode'),
                        'model':response.get('model'),'disclosure':response.get('disclosure')}]
            store.patch('session',session['id'],messages=(session['messages']+exchange)[-60:],updated_at=now())
            store.patch('chat',ident,**response,status='succeeded',stage='succeeded',completed_at=now())
    except Exception as error:
        with lock:
            if not cancelled():
                # Never publish provider response bodies, requests or credential paths.
                message = str(error)[:400] if isinstance(error, ValueError) else '模型请求未完成，请重试；核心计算不受影响'
                store.patch('chat',ident,status='failed',stage='failed',message=message,error_type=type(error).__name__,completed_at=now())


@router.post('/assistant/chat', status_code=202)
def chat(body: Chat):
    result = read_result(body.run_id)
    question = body.question or next((str(m.get('content','')) for m in reversed(body.messages) if m.get('role')=='user'), '')
    if not question.strip() or len(question)>2000:
        raise HTTPException(422, '请输入不超过2000字的问题')
    if body.provider=='local':
        selected_model=None
    elif body.provider in provider.MODELS:
        selected_model=provider.MODELS[body.provider]
    elif body.provider.startswith('profile-'):
        try:
            profile=provider_profiles.get(body.provider)
            provider_profiles.require_call(profile)
            selected_model=profile['model']
        except ValueError as error:
            raise HTTPException(400,str(error)) from None
    else:
        raise HTTPException(400,'请选择本机证据解读、内置免费模型或已保存的自有模型')
    result_hash = digest(result)
    with lock:
        if active_count('chat') >= 8:
            raise HTTPException(429, '助手队列已满，请稍后重试')
        if body.session_id:
            session = require('session',body.session_id)
            if session['run_id'] != body.run_id or session['result_sha256'] != result_hash:
                raise HTTPException(409, '会话绑定的是另一份运行结果，请开启新会话')
        else:
            session = store.put('session',{'id':'session-'+uuid.uuid4().hex[:12], 'created_at':now(),
                                          'run_id':body.run_id,'result_sha256':result_hash,'messages':[]})
        if any(c['session_id']==session['id'] and c['status'] not in TERMINAL for c in store.all('chat')):
            raise HTTPException(409, '当前会话已有待完成的问题')
        value = {'id':'chat-'+uuid.uuid4().hex[:12], 'created_at':now(), 'run_id':body.run_id, 'session_id':session['id'],
                 'status':'queued', 'stage':'queued','message':'等待证据助手','result_sha256':result_hash,
                 'provider':body.provider,'model':selected_model}
        value['request_id'] = value['id']
        store.put('chat',value)
        chat_worker.submit(execute_chat,value['id'],result,question,session,body.provider)
    return value


@router.get('/assistant/requests/{request_id}')
def get_chat(request_id: str):
    return require('chat',request_id)


@router.post('/assistant/requests/{request_id}/cancel')
def cancel_chat(request_id: str):
    with lock:
        value = require('chat',request_id)
        if value['status'] not in TERMINAL:
            value = store.patch('chat',request_id,status='cancelled',stage='cancelled',message='已取消；迟到回答将丢弃',completed_at=now())
    return value


@router.get('/assistant/sessions')
def list_sessions(run_id: str):
    require('run',run_id)
    sessions = [s for s in store.all('session') if s['run_id']==run_id]
    return {'sessions':sorted(sessions,key=lambda s:s['created_at'],reverse=True)}


@router.get('/assistant/sessions/{session_id}')
def get_session(session_id: str):
    return require('session',session_id)
