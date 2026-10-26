"""Optional Chrome/Playwright smoke test; only a new public-data run and local evidence query."""
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import hashlib,json,os,socket,subprocess,threading,time,urllib.request,sys,uuid,tempfile
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'product/outputs'/('public-smoke-'+uuid.uuid4().hex[:12])
RUNTIME.mkdir(parents=True,exist_ok=False)
PYTHON=Path(sys.executable)
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
url=f'http://127.0.0.1:{port}'
env={**os.environ,'PYTHONIOENCODING':'utf-8','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
'NENGCE_V3_OUTPUT':str(RUNTIME/'http-runtime/v3'),'NENGCE_RUNS_DIR':str(RUNTIME/'http-runtime/v2'),
'NENGCE_PROFILE_STORE':str(Path(tempfile.gettempdir())/('nengce-smoke-profiles-'+uuid.uuid4().hex)/'providers.dpapi'),'NENGCE_CREDENTIAL_FILE':str(RUNTIME/'no-model-credentials.txt')}
log=(RUNTIME/'http-server.log').open('w',encoding='utf8')
server=subprocess.Popen([str(PYTHON),'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT/'product',env=env,stdout=log,stderr=subprocess.STDOUT)
def request(path,body=None):
 raw=None if body is None else json.dumps(body).encode()
 req=urllib.request.Request(url+path,data=raw,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=60) as r:return json.loads(r.read())
def wait(path,seconds=120):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  value=request(path)
  if value['status'] in ['succeeded','failed','cancelled']:return value
  time.sleep(.3)
 raise RuntimeError('Local computation did not reach a terminal state')
class Pages(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if not self.path.startswith('/nengce-pilot/'):self.send_error(404);return
  self.path=self.path[len('/nengce-pilot'):];super().do_GET()
 def do_HEAD(self):
  if not self.path.startswith('/nengce-pilot/'):self.send_error(404);return
  self.path=self.path[len('/nengce-pilot'):];super().do_HEAD()
httpd=None
try:
 for _ in range(150):
  try:
   if request('/api/v3/health')['status']=='ok':break
  except Exception:time.sleep(.1)
 else:raise RuntimeError('Local API did not start')
 datasets=request('/api/v3/datasets')['datasets'];assert len(datasets)==32
 rsf=next(item for item in datasets if item['dataset_id']=='rsf-hourly')
 config=request('/api/v3/defaults');config['idempotency_key']='release-http-verified-uci'
 created=request('/api/v3/runs',config);run=wait('/api/v3/runs/'+created['id'])
 assert run['status']=='succeeded',run.get('message')
 assert run['result']['dataset']['public_data'] is True
 assert len(run['result']['series'])==96
 with urllib.request.urlopen(url+'/api/v3/runs/'+run['id']+'/export/json') as response:exported=response.read()
 assert hashlib.sha256(exported).hexdigest()==run['result_sha256']
 assert json.loads(exported)['run_id']==run['id']
 status=request('/api/v3/assistant/status');assert status['local_available'] is True
 chat=request('/api/v3/assistant/chat',{'run_id':run['id'],'provider':'local','question':'本次结果的计费边界是什么？'})
 answer=wait('/api/v3/assistant/requests/'+chat['id'])
 assert answer['status']=='succeeded',answer.get('message')
 (RUNTIME/'http-run.json').write_text(json.dumps({'runId':run['id'],'resultSha256':run['result_sha256'],'status':run['status'],'localEvidenceAssistant':answer['status']},ensure_ascii=False,indent=2),encoding='utf8')
 (RUNTIME/'images').mkdir(parents=True,exist_ok=True)
 with sync_playwright() as p:
  browser=p.chromium.launch(channel='chrome',headless=True)
  page=browser.new_page(viewport={'width':1440,'height':1000},locale='zh-CN',reduced_motion='reduce')
  errors=[];http_errors=[];external=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.on('response',lambda r:http_errors.append(r.status) if r.status>=400 else None)
  page.on('request',lambda r:external.append(r.url) if r.url.startswith('http') and not r.url.startswith('http://127.0.0.1:') else None)
  response=page.goto(url+'/#page=workspace&run='+run['id'],wait_until='networkidle');assert response.status==200
  expect(page.get_by_label('选择回放策略')).to_be_visible()
  assert page.locator('main').inner_text().find('2018-12-01')>=0
  page.screenshot(path=str(RUNTIME/'images/nengce-local-workbench.png'))
  page.get_by_role('button',name='费用对照',exact=True).click()
  expect(page.get_by_role('heading',name='每一笔费用，都有边界')).to_be_visible()
  page.screenshot(path=str(RUNTIME/'images/nengce-local-costs.png'))
  page.get_by_role('button',name='数据目录',exact=True).click()
  page.get_by_label('搜索数据目录').fill('rsf-hourly')
  if rsf.get('runtime_ready') is False:
   expect(page.get_by_role('button',name='需补齐公开原件')).to_be_disabled()
  page.get_by_role('button',name='方案工作台',exact=True).click()
  page.set_viewport_size({'width':390,'height':844})
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  page.screenshot(path=str(RUNTIME/'images/nengce-local-mobile.png'))
  httpd=ThreadingHTTPServer(('127.0.0.1',0),partial(Pages,directory=str(ROOT/'pages')))
  threading.Thread(target=httpd.serve_forever,daemon=True).start()
  pages_url=f'http://127.0.0.1:{httpd.server_port}/nengce-pilot/'
  page.set_viewport_size({'width':1440,'height':1000});response=page.goto(pages_url,wait_until='networkidle');assert response.status==200
  expect(page.locator('#case-content')).to_be_visible()
  assert page.locator('#strategy option').count()==8
  page.locator('#strategy').select_option('R2')
  page.locator('#time').fill('20')
  expect(page.locator('#timestamp')).to_have_text('2018-12-01 05:00:00')
  page.screenshot(path=str(RUNTIME/'images/nengce-pages-demo.png'))
  page.get_by_role('button',name='▥ 费用对照').click()
  assert page.locator('#strategy-costs tr').count()==8
  page.get_by_role('button',name='▤ 来源与边界').click()
  assert page.locator('#limitations li').count()==5
  assert '不运行 Python' in page.locator('.scope-banner').inner_text()
  page.get_by_role('button',name='◈ 方案回放').click()
  page.set_viewport_size({'width':390,'height':844})
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  page.screenshot(path=str(RUNTIME/'images/nengce-pages-mobile.png'))
  assert not errors,errors
  assert not http_errors,http_errors
  assert not external,external
  result={'status':'PASS','browser':browser.version,'localApi':True,'actualPublicUciRun':True,'nativeIntervals':96,'immutableJsonExportSha256':True,'localEvidenceAssistant':True,'viewports':[1440,390],'pagesNestedPath':'/nengce-pilot/','pagesStrategies':8,'scriptErrors':errors,'httpErrors':http_errors,'externalRequests':external,'realModelCalled':False,'hardwareConnected':False,'remoteDeploymentTested':False}
  browser.close()
 (RUNTIME/'browser-http-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(result,ensure_ascii=False))
finally:
 if httpd:httpd.shutdown();httpd.server_close()
 if os.name=='nt':subprocess.run(['taskkill','/PID',str(server.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 else:server.terminate()
 try:server.wait(timeout=10)
 except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
 log.close()
