from pathlib import Path
import json,csv,html,hashlib

def fmt(value, places=2):
    return f"{value:.{places}f}" if value is not None else "N/A（分母为零）"

def assert_evidence_destination(directory):
    """Never overwrite a completed or partially written evidence result."""
    directory=Path(directory)
    if any((directory/name).exists() for name in ('result.json','manifest.json')):
        raise FileExistsError('证据目录已有结果或清单，拒绝覆盖；请选择新的输出目录：'+str(directory))
    return directory


def save_evidence(result,directory):
    directory=assert_evidence_destination(directory)
    directory.mkdir(parents=True,exist_ok=True)
    # The API may already have state.json here. Only evidence writers reserve
    # this marker; exclusive creation also prevents concurrent CLI overwrites.
    marker=directory/'.evidence-writing'
    with marker.open('x',encoding='utf-8') as handle:
        handle.write(str(result['run_id']))
    try:
        assert_evidence_destination(directory)
        _write_evidence(result,directory)
    finally:
        marker.unlink(missing_ok=True)


def _write_evidence(result,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    fields=['timestamp','actual_kw','forecast_kw','hgb_kw','daily_naive_kw','weekly_naive_kw','price']
    sub=['grid_kw','charge_kw','discharge_kw','soc_kwh','planned_charge_kw','planned_discharge_kw','clip_kwh','energy_cost','degradation_cost','total_cost','cumulative_cost']
    for field in ['clip_no_export_kwh','clip_soc_kwh','clip_power_kwh','clip_charge_kwh','clip_discharge_kwh','clip_retained_energy_kwh','clip_local_cost_delta']:
        if all(field in v for row in result['series'] for v in row['strategies'].values()):sub.append(field)
    strategy_ids=[s['id'] for s in result['strategies']]
    fields += [f'{k}_{x}' for k in strategy_ids for x in sub]
    with (directory/'timeseries.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fields);w.writeheader()
        for r in result['series']:
            row={k:r[k] for k in fields[:7]}
            for k in strategy_ids:
                for x in sub:row[k+'_'+x]=r['strategies'][k][x]
            w.writerow(row)
    metric_keys=['run_id','summary','forecast','strategies','config','dataset','reproducibility','ablation','validation_conclusion','risk_ablation','learning_ablation']
    (directory/'metrics.json').write_text(json.dumps({k:result[k] for k in metric_keys if k in result},ensure_ascii=False,indent=2),encoding='utf-8')
    (directory/'solver_audit.json').write_text(json.dumps(result['solver_audit'],ensure_ascii=False,indent=2),encoding='utf-8')
    if 'strategy_solver_audit' in result:
        (directory/'strategy_solver_audit.json').write_text(json.dumps(result['strategy_solver_audit'],ensure_ascii=False,indent=2),encoding='utf-8')
    rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(x))}</td>' for x in [s['id'],s['name'],f"{s['energy_cost']:.2f}",f"{s['degradation_cost']:.2f}",f"{s['total_cost']:.2f}",fmt(s['savings_pct'])+"%",s['comparison_valid']])+'</tr>' for s in result['strategies'])
    frows=''.join(f"<tr><td>{s['name']}</td><td>{s['mae_kw']:.4f}</td><td>{fmt(s['wape_pct'],3)}%</td><td>{s['n']}</td></tr>" for s in result['forecast']['models'])
    conclusion=result.get('validation_conclusion',{})
    verdict=html.escape(conclusion.get('verdict','未生成验证结论'))
    next_steps=''.join('<li>'+html.escape(v)+'</li>' for v in conclusion.get('next_steps',[]))
    source_label=html.escape(result['summary'].get('source_label','负荷 + 参数化电池/电价情景'))
    evaluation_role=result['forecast'].get('evaluation_role','unknown')
    evaluation_note=('本次为已公开的2018年12月历史回归；没有新的独立泛化证据。' if evaluation_role=='historical_regression' else
        '本次为探索性区间；来源与评测前独立冻结情况未被独立核验，不能称为新盲测。' if evaluation_role=='exploratory_subperiod' else
        '评估角色以结果记录为准；没有在本报告中声明新的独立泛化证据。')
    report=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>能策Pilot 验证证据</title><style>body{{font:16px system-ui;max-width:1080px;margin:50px auto;color:#17312c;line-height:1.7;padding:20px}}h1{{font-size:38px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;border-bottom:1px solid #cbd8d4;text-align:left}}aside{{background:#fff4dc;padding:18px}}code{{word-break:break-all}}@media print{{body{{margin:0}}}}</style><h1>能策Pilot · 真实计算验证报告</h1><p>运行 {result['run_id']} · {result['generated_at']}</p><aside>{source_label}。不是客户实测收益。O1为事后收益上界，不可部署。</aside><h2>评估范围</h2><p>{result['summary']['period_start']} 至 {result['summary']['period_end']}，{result['summary']['hours']}小时；{result['summary']['elapsed_seconds']:.2f}秒。比较有效：{result['summary']['comparison_valid']}</p><h2>完整期间预测对照</h2><table><tr><th>模型</th><th>MAE kW</th><th>WAPE</th><th>小时数</th></tr>{frows}</table><h2>同口径费用（{html.escape(result['config']['tariff']['currency'])}）</h2><table><tr><th>编号</th><th>策略</th><th>购电能量费</th><th>衰减代理费</th><th>总费用</th><th>较无储能节省</th><th>比较有效</th></tr>{rows}</table><h2>验证结论与下一步</h2><aside>{verdict}</aside><ol>{next_steps}</ol><p>规则：约束或终端不通过则比较无效；HGB本次评估未胜朴素或发生动作裁剪则继续影子验证。不是实机安全认证或投资建议。</p><h2>限制与假设</h2><ul>{''.join('<li>'+html.escape(s)+'</li>' for s in result['assumptions'])}</ul><h2>数据指纹</h2><code>{html.escape(json.dumps(result['dataset']['provenance'],ensure_ascii=False))}</code><h2>警告</h2><p>{html.escape('；'.join(result['summary']['warnings']) or '本次建模约束验收无警告，仍受上述业务限制。')}</p><p>完整逐小时和求解证据见同目录 result.json、timeseries.csv、solver_audit.json。可用 python -m backend.cli reproduce --config config.json 独立重跑。</p></html>'''
    risk_rows=''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in [s['id'],fmt(s.get('forecast_plan_cost')),fmt(s['total_cost']),fmt(s['clip_kwh']),fmt(s['terminal_error_kwh'],6),fmt(s['charge_kwh']+s['discharge_kwh'])])+'</tr>' for s in result['strategies'])
    audit_section=f'''<h2>计划与实际执行</h2><p>计划费用是各日午夜计划之和，不是逐小时重复目标之和。裁剪单位为每小时功率差乘1小时后的kWh；吞吐为AC侧充放电之和。</p><table><tr><th>策略</th><th>计划费用</th><th>回放费用</th><th>裁剪 kWh</th><th>最大日终误差 kWh</th><th>吞吐 kWh</th></tr>{risk_rows}</table><h2>选模与风险消融</h2><p>实际选模：{html.escape(result['forecast']['selected_model'])}。角色：{html.escape(result['forecast'].get('evaluation_role','unknown'))}。{evaluation_note}</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{html.escape(json.dumps({k:result[k] for k in ['risk_ablation','learning_ablation'] if k in result},ensure_ascii=False,indent=2))}</pre>'''
    report=report.replace('</html>',audit_section+'</html>')
    (directory/'report.html').write_text(report,encoding='utf-8')
    (directory/'config.json').write_text(json.dumps(result['config'],ensure_ascii=False,indent=2),encoding='utf-8')
    artifact_names=['result.json','timeseries.csv','metrics.json','solver_audit.json','report.html','config.json']
    if 'strategy_solver_audit' in result:artifact_names.append('strategy_solver_audit.json')
    # Mutable API state/progress is deliberately outside the immutable evidence manifest.
    manifest={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in artifact_names}
    (directory/'manifest.json').write_text(json.dumps({'run_id':result['run_id'],'sha256':manifest},indent=2),encoding='utf-8')
