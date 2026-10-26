"""V3 exports: one result feeds JSON, interval CSV, monthly bills and local HTML."""
from pathlib import Path
import csv
import hashlib
import html
import json


def text(value):
    return html.escape(str(value))


def number(value):
    return '不适用' if value is None else f'{float(value):,.2f}'


def save_evidence(result, directory):
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'result.json').exists() or (folder/'manifest.json').exists():
        raise FileExistsError('冻结证据不可覆盖')
    with (folder/'.writing').open('x') as marker:
        marker.write('exclusive evidence writer')
    try:
        _write(result, folder)
    finally:
        (folder/'.writing').unlink(missing_ok=True)


def _write(result, folder):
    for name, value in [('result', result), ('config', result['config']),
                        ('metrics', {k:v for k,v in result.items() if k not in ('series','solver_audit','strategy_solver_audit')}),
                        ('solver_audit', result.get('strategy_solver_audit', result.get('solver_audit', [])))]:
        (folder/f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    rows = []
    for tick in result['series']:
        row = {k:v for k,v in tick.items() if isinstance(v, (int,float,str,bool)) or v is None}
        for strategy, values in tick['strategies'].items():
            row.update({f'{strategy}_{k}':v for k,v in values.items() if isinstance(v,(int,float,str,bool)) or v is None})
        rows.append(row)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with (folder/'timeseries.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fields); writer.writeheader(); writer.writerows(rows)
    money = result['config']['tariff'].get('currency','CNY')
    body = ''.join('<tr>'+''.join(f'<td>{text(v)}</td>' for v in [
        s['id'],s['name'],number(s.get('energy_cost')),number(s.get('demand_cost',0)),
        number(s.get('degradation_cost')),number(s['total_cost']),number(s.get('savings_vs_b0')),
        number(s.get('clip_kwh')), '有效' if s['comparison_valid'] else '不可比'])+'</tr>' for s in result['strategies'])
    summary = result['summary']
    report = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>能策 · 方案证据</title>
<style>body{{font:16px/1.7 system-ui,"Microsoft YaHei";max-width:1180px;margin:48px auto;padding:24px;color:#193d33;background:#f7f7f3}}h1{{font-size:40px;line-height:1.2}}h2{{margin-top:36px}}table{{border-collapse:collapse;width:100%;font-size:14px;background:white}}th,td{{text-align:left;padding:12px;border-bottom:1px solid #dbe2dc}}aside{{padding:20px;background:#e9efe9;border-left:4px solid #2f6755}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}}.table{{overflow:auto}}@media print{{body{{margin:0;background:white}}}}</style>
<p>能策 PILOT / 可复算方案证据</p><h1>把光储方案算清楚</h1><p>运行 {text(result['run_id'])} · {text(result.get('generated_at',''))}</p>
<aside>{text(summary.get('source_label','参数化示例计价'))}。本报告为间隔级仿真，不是实机控制安全认证。O1仅为完美预知诊断。</aside>
<h2>本次运行</h2><p>{text(summary['period_start'])} — {text(summary['period_end'])} · {text(len(result['series']))} 个间隔 · 计算 {number(summary['elapsed_seconds'])} 秒</p>
<p>实际预测模型：{text(summary['selected_model'])}。比较有效：{text(summary['comparison_valid'])}。</p>
<h2>费用与执行对照（{text(money)}）</h2><p>电费与吞吐代理分别核算；代理成本不是供电账单项目。完整月需量按实际15分钟进口峰值计算，范围以本次配置和数据资格为准。</p>
<div class="table"><table><thead><tr><th>编号</th><th>方案</th><th>购电能量费</th><th>需量费</th><th>吞吐代理</th><th>合计</th><th>较无储能节省</th><th>裁剪kWh</th><th>比较</th></tr></thead><tbody>{body}</tbody></table></div>
<h2>月账与计量依据</h2><pre>{text(json.dumps(result.get('monthly_bills',{}),ensure_ascii=False,indent=2))}</pre>
<h2>选模与风险代价</h2><pre>{text(json.dumps({k:result.get(k) for k in ['learning_ablation','risk_ablation','risk_ablations']},ensure_ascii=False,indent=2))}</pre>
<h2>限制与警告</h2><ul>{''.join('<li>'+text(v)+'</li>' for v in summary.get('warnings',[])+result.get('assumptions',[]))}</ul>
<h2>数据、协议与配置指纹</h2><pre>{text(json.dumps({'dataset':result.get('dataset'), 'reproducibility':result.get('reproducibility')},ensure_ascii=False,indent=2))}</pre>
<p>完整数值见同目录 result.json 与 timeseries.csv；本HTML与其读取同一运行产物。</p></html>'''
    (folder/'report.html').write_text(report,encoding='utf-8')
    names=['result.json','config.json','metrics.json','solver_audit.json','timeseries.csv','report.html']
    hashes={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in names}
    (folder/'manifest.json').write_text(json.dumps({'run_id':result['run_id'],'sha256':hashes},indent=2),encoding='utf-8')
