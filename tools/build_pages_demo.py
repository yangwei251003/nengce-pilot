"""Publish a minimal read-only view of an actual public-data CPU replay."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    raw = args.result.read_bytes()
    result = json.loads(raw)
    dataset = result['dataset']
    if dataset.get('public_data') is not True or dataset.get('privacy') != 'public':
        raise ValueError('Only explicitly public datasets may enter the Pages artifact')
    points = []
    for tick in result['series']:
        points.append({key:tick[key] for key in ['timestamp','actual_kw','forecast_kw','pv_kw','price']})
        points[-1]['strategies'] = {
            name:{key:value.get(key) for key in ['grid_kw','soc_kwh','charge_kw','discharge_kw','clip_kwh']}
            for name,value in tick['strategies'].items()
        }
    data = {
        'mode':'read-only-precomputed-public-case',
        'notice':'只读预计算公开案例；GitHub Pages 不运行 Python、不接收文件、不调用模型。',
        'sourceResultSha256':hashlib.sha256(raw).hexdigest(),
        'runId':result['run_id'],
        'generatedAt':result['generated_at'],
        'summary':result['summary'],
        'dataset':{key:dataset.get(key) for key in ['dataset_id','name','privacy','public_data','interval_minutes','timezone','source_id']},
        'provenance':{key:dataset['provenance'].get(key) for key in ['source_url','license','doi','attribution','transformation','warning']},
        'strategies':result['strategies'],
        'points':points,
        'limitations':['公开韩国钢厂历史负荷与人民币示例电价，不是客户真实账单或收益。',
                       '15分钟数据与源时区未知的工程时间推断均保留；此处只有单日，不认证完整月需量。',
                       '完美预知 O1 是事后诊断参照，不可部署。',
                       '原报告保留BDG2外部预测负结果、N1压力案例不可行、R2未优于R1与云端助手验收失败；见README及冻结报告。',
                       '未连接储能设备，不构成设备安全认证或真实投资回报验证。']
    }
    target=ROOT/'pages'
    target.mkdir(exist_ok=True)
    (target/'case.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'publicDataset':dataset['dataset_id'],'intervals':len(points),'sourceResultSha256':data['sourceResultSha256']}))


if __name__=='__main__':
    main()
