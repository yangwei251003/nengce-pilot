"""Run real core cases with outbound Python sockets denied, never disabling OS security."""
from pathlib import Path
import json
import socket
import sys
import time
import platform
import hashlib
import argparse
from datetime import datetime, timezone

root=Path(__file__).resolve().parents[1]
# This script can be copied to the same relative tools/ path in an isolated checkout.
sys.path.insert(0,str(root/'product'))
attempts=[]
def blocked(*args,**kwargs):
    attempts.append(repr(args)[:200])
    raise OSError('Network disabled for the offline core acceptance process')
socket.socket.connect=blocked
socket.socket.connect_ex=blocked
socket.create_connection=blocked
try:
    socket.create_connection(('example.com',443),timeout=.1)
except OSError:
    assert len(attempts)==1
attempts.clear()
from backend.v3.config import RunConfig
from backend.v3.core import run_experiment
from backend.v3.evidence import save_evidence

parser=argparse.ArgumentParser()
parser.add_argument('--out',type=Path,default=root/'offline-evidence')
parser.add_argument('--resume',action='store_true')
parser.add_argument('--months',action='store_true')
args=parser.parse_args()
out=args.out.resolve()
resume=args.resume
out.parent.mkdir(parents=True,exist_ok=True)
out.mkdir(exist_ok=resume)
started=time.perf_counter()
reports=[]
cases=[('uci-day','uci-steel-15min','2018-12-01','2018-12-01',0,'none'),
       ('rsf-day','rsf-hourly','2011-10-01','2011-10-01',0,'none')]
if args.months:
    cases += [(f'uci-{stress}','uci-steel-15min','2018-12-01','2018-12-31',30,stress)
              for stress in ['none','load_up_20','peak_price_up_20','forecast_bias_up_20','pv_drop_30']]
    cases += [('rsf-month','rsf-hourly','2011-10-01','2011-10-31',0,'none'),
              ('rsf-pv_drop_30','rsf-hourly','2011-10-01','2011-10-31',0,'pv_drop_30')]
for name,dataset,start,end,demand,stress in cases:
    t=time.perf_counter()
    config=RunConfig(dataset_id=dataset,evaluation={'start':start,'end':end},tariff={'demand_per_kw':demand},stress=stress,protocol_id='nengce-v3-data-20261004')
    print('START',name,flush=True)
    restored=False
    if resume and (out/name/'manifest.json').is_file():
        manifest=json.loads((out/name/'manifest.json').read_text(encoding='utf-8'))
        for filename,expected in manifest['sha256'].items():
            assert hashlib.sha256((out/name/filename).read_bytes()).hexdigest()==expected
        result=json.loads((out/name/'result.json').read_text(encoding='utf-8'))
        assert result['config']==config.model_dump()
        restored=True
    else:
        result=run_experiment(config,'offline-'+name)
        save_evidence(result,out/name)
    reports.append({'case':name,'status':'PASS','elapsed_seconds':time.perf_counter()-t,
                    'comparison_valid':result['summary']['comparison_valid'],
                    'physical_valid':result['summary']['physical_valid'],
                    'code_changed_during_run':result['reproducibility']['code_changed_during_run'],
                    'core_code_sha256':result['reproducibility']['code_sha256'],
                    'resumed_from_verified_immutable_artifact':restored,
                    'original_core_seconds':result['summary']['elapsed_seconds'],
                    'network_attempts':len(attempts)})
    print(json.dumps(reports[-1]),flush=True)
    (out/'checkpoint.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
report={'status':'PASS' if not attempts and not any(x['code_changed_during_run'] for x in reports) else 'FAIL',
        'created_at':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'platform':platform.platform(),
        'elapsed_seconds':time.perf_counter()-started,'network_guard_probe':'PASS',
        'scope':'All outbound sockets in this core process denied; OS/network settings untouched. Scientific infeasibility is reported, not discarded.',
        'cases':reports,'network_attempts':attempts}
(out/'offline-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
raise SystemExit(0 if report['status']=='PASS' else 1)
