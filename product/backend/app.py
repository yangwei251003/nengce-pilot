"""Single local API + immutable filesystem run store; no authentication or hardware control."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from threading import Lock
from contextlib import asynccontextmanager
import hashlib,json,uuid,traceback,os
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .config import RunConfig
from .data import ROOT,datasets,import_csv
from .engine import run_experiment,Cancelled
from .evidence import save_evidence

@asynccontextmanager
async def lifespan(application):
    # Importing a module for tests or CLI use must not interrupt a running service.
    recover_legacy()
    from .v3.api import recover
    recover()
    yield

app=FastAPI(title='能策Pilot',version='3.1.0',lifespan=lifespan,description='Local, auditable load/PV planning and replay. No hardware control.')
RUNS=Path(os.environ.get('NENGCE_RUNS_DIR',str(ROOT/'outputs'/'runs-v2'))).resolve();RUNS.mkdir(parents=True,exist_ok=True)
worker=ThreadPoolExecutor(max_workers=1)
lock=Lock();states={};keys={};cancel_flags=set()

def write_state(state):
    p=RUNS/state['run_id'];p.mkdir(exist_ok=True)
    temp=p/'state.tmp';temp.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8');temp.replace(p/'state.json')

def public_state(state,include_result=True):
    out=dict(state)
    if include_result and state['status']=='succeeded':
        p=RUNS/state['run_id']/'result.json'
        if p.exists():out['result']=json.loads(p.read_text(encoding='utf-8'))
    return out

def recover_legacy():
    for p in RUNS.glob('*/state.json'):
        try:
            s=json.loads(p.read_text(encoding='utf-8'))
            if s['status'] not in ('succeeded','failed','cancelled'):
                s.update(status='failed',stage='interrupted',message='服务重启中断了运行，请重新计算',progress=0)
                write_state(s)
            states[s['run_id']]=s
            if s.get('idempotency_key'):keys[s['idempotency_key']]=(s['body_hash'],s['run_id'])
        except Exception:pass

def execute(run_id,config):
    def progress(stage,pct,message):
        with lock:
            states[run_id].update(stage=stage,status=stage,progress=pct,message=message);write_state(states[run_id])
    try:
        result=run_experiment(config,run_id,progress,lambda:run_id in cancel_flags)
        if run_id in cancel_flags:raise Cancelled('用户取消运行')
        save_evidence(result,RUNS/run_id)
        with lock:
            if run_id in cancel_flags:raise Cancelled('用户取消运行；已生成的中间证据不作为成功结果发布')
            states[run_id].update(status='succeeded',stage='succeeded',progress=100,message='回放完成。请同时审阅约束校验与限制。',completed_at=datetime.now(timezone.utc).isoformat());write_state(states[run_id])
    except Cancelled as e:
        with lock:states[run_id].update(status='cancelled',stage='cancelled',message=str(e));write_state(states[run_id])
    except Exception as e:
        with lock:states[run_id].update(status='failed',stage='failed',message=str(e),error_type=type(e).__name__);write_state(states[run_id])
        (RUNS/run_id/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        with lock:cancel_flags.discard(run_id)

@app.get('/api/health')
def health():return {'status':'ok','version':'3.1.0','mode':'local_research_no_hardware_control'}
@app.get('/api/defaults')
def defaults():return RunConfig().model_dump()
@app.get('/api/datasets')
def list_datasets():return {'datasets':datasets()}
class CSVImport(BaseModel):
    csv_text:str=Field(max_length=20_000_000)
    name:str='用户授权小时负荷'
    timezone:str='source-local-unknown'
    unit:str='kW'
    authorized:bool=False
@app.post('/api/datasets/import')
def upload(body:CSVImport):return import_csv(**body.model_dump())
@app.get('/api/runs')
def list_runs():
    with lock:return {'runs':[public_state(s,False) for s in sorted(states.values(),key=lambda x:x['created_at'],reverse=True)]}
@app.post('/api/runs',status_code=202)
def start_run(config:RunConfig):
    body=config.model_dump(exclude={'idempotency_key'});hashed=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    with lock:
        key=config.idempotency_key
        if key and key in keys:
            prev,id=keys[key]
            if prev!=hashed:raise HTTPException(409,'同一个请求标识不能绑定不同配置')
            return public_state(states[id],False)
        run_id='run-'+uuid.uuid4().hex[:12]
        s={'run_id':run_id,'status':'queued','stage':'queued','progress':0,'message':'等待单计算worker',
            'created_at':datetime.now(timezone.utc).isoformat(),'config':body,'body_hash':hashed,'idempotency_key':key}
        states[run_id]=s
        if key:keys[key]=(hashed,run_id)
        write_state(s)
        worker.submit(execute,run_id,config)
        return public_state(s,False)
@app.get('/api/runs/{run_id}')
def get_run(run_id:str):
    with lock:
        if run_id not in states:raise HTTPException(404,'运行不存在')
        return public_state(states[run_id])
@app.post('/api/runs/{run_id}/cancel')
def cancel_run(run_id:str):
    with lock:
        if run_id not in states:raise HTTPException(404,'运行不存在')
        if states[run_id]['status'] not in ('succeeded','failed','cancelled'):cancel_flags.add(run_id)
        return public_state(states[run_id],False)
@app.get('/api/runs/{run_id}/export/{format}')
def export_run(run_id:str,format:str):
    if run_id not in states:raise HTTPException(404,'运行不存在')
    if states[run_id]['status']!='succeeded':raise HTTPException(409,'未成功完成的运行不可导出成功报告')
    files={'json':('result.json','application/json'),'csv':('timeseries.csv','text/csv'),'html':('report.html','text/html')}
    if format not in files:raise HTTPException(400,'仅支持json/csv/html')
    name,media=files[format]
    return FileResponse(RUNS/run_id/name,media_type=media,filename=f'{run_id}-{name}')

# Register API first; all remaining URLs serve compiled frontend.
from .v3.api import router as v3_router
app.include_router(v3_router)
app.version='3.0.0'
frontend=ROOT/'frontend'/'dist'
if frontend.exists():app.mount('/',StaticFiles(directory=frontend,html=True),name='frontend')
else:
    @app.get('/')
    def home():return {'message':'API ready. Build frontend with npm run build; then restart server.','docs':'/docs'}
