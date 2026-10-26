import argparse,json,uuid
from pathlib import Path
from .config import RunConfig
from .engine import run_experiment
from .evidence import save_evidence,assert_evidence_destination
from .data import ROOT

def main():
    p=argparse.ArgumentParser(description='能策 Pilot 可复算核心')
    p.add_argument('command',choices=['run','reproduce'],nargs='?',default='run')
    p.add_argument('--config');p.add_argument('--out',help='新的证据输出目录；已存在结果或清单时拒绝覆盖')
    p.add_argument('--start');p.add_argument('--end');p.add_argument('--stress',choices=['none','load_up_20','peak_price_up_20','forecast_bias_up_20'],default=None)
    args=p.parse_args();c=RunConfig.model_validate(json.loads(Path(args.config).read_text(encoding='utf-8'))) if args.config else RunConfig()
    if args.start:c.evaluation.start=args.start
    if args.end:c.evaluation.end=args.end
    if args.stress:c.stress=args.stress
    c=RunConfig.model_validate(c.model_dump())
    run_id='cli-'+uuid.uuid4().hex[:10]
    destination=assert_evidence_destination(args.out if args.out else ROOT/'outputs'/'cli-v2'/run_id)
    r=run_experiment(c,run_id,lambda s,p,m:print(f'[{p:3d}%] {s}: {m}',flush=True))
    save_evidence(r,destination)
    print(json.dumps({'output':str(destination),'summary':r['summary'],'forecast':r['forecast'],'strategies':r['strategies']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
