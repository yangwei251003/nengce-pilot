"""CPU-only command line replay. Outputs are never overwritten."""
import argparse
import json
from pathlib import Path
import uuid
from .config import RunConfig
from .core import run_experiment
from .evidence import save_evidence


def main():
    parser=argparse.ArgumentParser(description='能策V3 可复算光储方案')
    parser.add_argument('--config')
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    directory=Path(args.out).resolve()
    if any((directory/name).exists() for name in ('result.json','manifest.json','.writing')):
        parser.error('输出含已有证据，请选择新的空目录')
    config=RunConfig.model_validate(json.loads(Path(args.config).read_text(encoding='utf-8-sig'))) if args.config else RunConfig()
    result=run_experiment(config,'run-'+uuid.uuid4().hex[:12],lambda s,p,m:print(f'{p:.0f}% {m}',flush=True))
    save_evidence(result,directory)
    print(json.dumps({'output':str(directory),'summary':result['summary']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
