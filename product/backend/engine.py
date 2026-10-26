import json,time,hashlib,platform
from pathlib import Path
from importlib.metadata import version
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from .data import load_dataset
from .forecast import train_forecasts,metrics,MODEL_PARAMETERS,PROTOCOL_ID
from .planner import solve_plan,solve_risk_plan,execute_step

class Cancelled(Exception):pass

ASSUMPTIONS=[
'公开韩国钢厂2018负荷 + 合成CNY分时电价和100kWh默认电池；不是中国真实客户节费或投资回报。',
'UCI原始时区未知；午夜NSM=0日期后移一天为区间末是工程推断；以source-local区间始映射情景电价。',
'15分钟区间电量经能量守恒聚合成小时平均kW，不能代替15分钟需量计费和实机瞬态安全验证。',
'仅计算购电能量费与AC侧充放电总吞吐线性衰减代理；不含需量费、容量租赁、税费、投资摊销或真实寿命。',
'无光伏、禁止反送电、不设电网容量上限；电池容量、功率、效率恒定，无实机控制。',
'每个自然日全部电池策略使用相同初末SOC；不满足终端条件的回放不能作为公平收益结论。',
'B1固定谷段充电、峰段放电至初始SOC，21点后收敛终端；规则不看未来。B2/N1/L1/R1每小时滚动MILP只执行首动作。',
'O1使用未来实际负荷，是事后完美预知成本下界/收益上界，不可部署，不计为AI成绩。',
'压力情景保持存档日前预测，只扰动实际负荷/电价或所有部署策略预测；仅使用已完成小时误差因果校正，不代表长期漂移适应。',
'日内校正为上一小时误差的0.5倍指数衰减，不是重新训练；R1余量只由回放前开发验证校准，不能保证无裁剪。',
'2018年12月已公开：本版只是历史回归，缺少未参与选模的新站点或新时间窗泛化证据。',
'R1为候选风险措施，明确披露节费和吞吐代价；默认保持B2，不能按历史回归结果临时换赢家。']


def price_vector(index,tariff,stress):
    p=np.array([tariff.peak if h in tariff.peak_hours else tariff.offpeak if h in tariff.offpeak_hours else tariff.flat for h in index.hour],float)
    if stress=='peak_price_up_20':p[np.isin(index.hour,tariff.peak_hours)]*=1.2
    return p


def risk_discharge_limit(prediction,calibration,scale):
    prediction=np.asarray(prediction,dtype=float)
    margin=np.minimum(calibration['positive_overprediction_q75_kw'],calibration['cap_fraction']*prediction)*scale
    return np.maximum(0,prediction-margin),margin


def run_experiment(config,run_id,progress=None,cancelled=None):
    start_time=time.perf_counter()
    def stage(name,pct,message):
        if cancelled and cancelled():raise Cancelled('用户取消运行')
        if progress:progress(name,pct,message)
    stage('validating',3,'校验来源、单位、时间连续性和参数')
    frame,meta=load_dataset(config.dataset_id)
    reference_dataset=meta.get('dataset_id')=='uci-steel-hourly'
    assumptions=list(ASSUMPTIONS)
    if not reference_dataset:
        assumptions[0]='用户导入负荷由用户声明拥有使用授权；来源真实性、站点归属及原始计量未被独立核验，仿真不是已实现客户收益。'
        assumptions[1]=f"时间采用用户声明的 {meta.get('timezone','未声明')} 源日历，CSV为小时区间始；不对导入数据套用UCI午夜修正。"
        assumptions[2]='导入CSV每行代表一个完整小时，kW为平均功率或kWh为该小时能量；不等于15分钟需量计费或实机瞬态验证。'
        assumptions[-2]='导入CSV的当前评估默认探索性；尚无评测前独立冻结的数据划分和外部泛化验证证明。'
    stage('forecasting',10,'三个开发滚动窗验证；按预定门槛选模，历史回归独立报告')
    forecast,report=train_forecasts(frame,config.evaluation.start,config.evaluation.end)
    if not reference_dataset:
        report['evaluation_role']='exploratory_subperiod'
        report['notes']=[note for note in report['notes'] if not note.startswith('December 2018')]
        report['notes'].append('User-attested CSV evaluation is exploratory; source and preregistration not independently verified.')
    if config.stress=='load_up_20':forecast['load_kw']*=1.2
    if config.stress=='forecast_bias_up_20':
        forecast[['forecast_kw','hgb_kw','daily_naive_kw','weekly_naive_kw']]*=1.2
    prices=price_vector(forecast.index,config.tariff,config.stress)
    b=config.battery;initial=b.capacity_kwh*b.initial_soc
    traces={key:[] for key in ['B0','B1','B2','N1','O1','L1','R1']}
    names={'B0':'无储能','B1':'固定峰谷规则','B2':'开发验证所选预测 + 滚动优化','N1':'周朴素预测 + 同一滚动优化器','O1':'事后完美预知上界，不可部署','L1':'固定HGB学习预测 + 同一优化器','R1':'所选预测 + 验证误差安全余量'}
    status_counts={k:{'optimal':0,'feasible':0,'failed':0,'margin_plan_failed':0,'fallback':0} for k in traces}
    plan_costs={k:0.0 for k in traces};terminal_errors={k:[] for k in traces};solver_audit=[];strategy_solver_audit=[]
    days=list(forecast.groupby(forecast.index.normalize()))
    rolling_keys=('B2','N1','L1','R1')
    for day_number,(date,day) in enumerate(days):
        stage('replaying',20+int(65*day_number/len(days)),f'回放第 {day_number+1}/{len(days)} 天：{date.date()}')
        actual=day.load_kw.to_numpy();p=price_vector(day.index,config.tariff,config.stress)
        bases={'B2':day.forecast_kw.to_numpy(),'N1':day.weekly_naive_kw.to_numpy(),'L1':day.hgb_kw.to_numpy(),'R1':day.forecast_kw.to_numpy()}
        energies={k:initial for k in traces};errors={k:0. for k in rolling_keys}
        oracle=solve_plan(actual,p,b)
        if not oracle['feasible']:raise ValueError('事后参照求解失败：'+oracle['message'])
        status_counts['O1']['optimal' if oracle['optimal'] else 'feasible']+=1
        plan_costs['O1']+=oracle['forecast_plan_cost']
        for h,timestamp in enumerate(day.index):
            if cancelled and cancelled():raise Cancelled('用户取消运行')
            actions={'B0':(0.,0.),'O1':(oracle['charge_kw'][h],oracle['discharge_kw'][h])}
            for key in rolling_keys:
                prediction=np.maximum(0,bases[key][h:]+.5*errors[key]*np.exp(-np.arange(len(day)-h)/6))
                limits,margin=risk_discharge_limit(prediction,report['risk_calibration'],config.risk_margin_scale if key=='R1' else 0.)
                if key=='R1' and config.risk_margin_scale>0:
                    plan=solve_risk_plan(prediction,p[h:],b,limits,initial_kwh=energies[key],target_kwh=initial)
                else:
                    plan=solve_plan(prediction,p[h:],b,initial_kwh=energies[key],target_kwh=initial)
                if plan.get('margin_plan_failed'):status_counts[key]['margin_plan_failed']+=1
                if plan.get('fallback_used'):status_counts[key]['fallback']+=1
                status_counts[key]['optimal' if plan['optimal'] else 'feasible' if plan['feasible'] else 'failed']+=1
                if h==0 and plan['feasible']:plan_costs[key]+=plan['forecast_plan_cost']
                audit={'strategy':key,'timestamp':str(timestamp),'horizon_hours':len(day)-h,'initial_kwh':energies[key],
                    'status':plan['status'],'mip_gap':plan['mip_gap'],'elapsed_seconds':plan['elapsed_seconds'],
                    'forecast_origin':str(timestamp),'latest_observation':str(timestamp-pd.Timedelta(hours=1)),
                    'target_kwh':initial,'first_forecast_kw':float(prediction[0]),
                    'first_discharge_limit_kw':float(prediction[0] if plan.get('margin_plan_failed') else limits[0]),
                    'first_safety_margin_kw':float(0 if plan.get('margin_plan_failed') else margin[0]),
                    'requested_discharge_limit_kw':float(limits[0]),'requested_safety_margin_kw':float(margin[0]),
                    'margin_plan_status':plan.get('margin_plan_status'),'margin_plan_failed':bool(plan.get('margin_plan_failed',False)),
                    'fallback_used':bool(plan.get('fallback_used',False)),'margin_failure_message':plan.get('margin_failure_message'),
                    'margin_attempt_elapsed_seconds':plan.get('margin_attempt_elapsed_seconds'),
                    'first_charge_kw':float(plan['charge_kw'][0]) if plan['feasible'] else None,'first_discharge_kw':float(plan['discharge_kw'][0]) if plan['feasible'] else None}
                strategy_solver_audit.append(audit)
                if key=='B2':solver_audit.append(audit)
                actions[key]=(plan['charge_kw'][0],plan['discharge_kw'][0]) if plan['feasible'] else (0.,0.)
            e=energies['B1'];charge=discharge=0.
            if h in config.tariff.offpeak_hours and h<7:charge=min(b.power_kw,max(0,(b.capacity_kwh*b.max_soc-e)/b.charge_efficiency))
            elif h in config.tariff.peak_hours or h>=21:discharge=min(b.power_kw,max(0,(e-initial)*b.discharge_efficiency))
            if h>=22 and e<initial:charge=min(b.power_kw,(initial-e)/b.charge_efficiency);discharge=0.
            actions['B1']=(charge,discharge)
            for key,(charge,discharge) in actions.items():
                row=execute_step(actual[h],charge,discharge,energies[key],b)
                row['energy_cost']=row['grid_kw']*p[h]
                row['degradation_cost']=(row['charge_kw']+row['discharge_kw'])*b.degradation_per_kwh
                row['total_cost']=row['energy_cost']+row['degradation_cost']
                row['cumulative_cost']=(traces[key][-1]['cumulative_cost'] if traces[key] else 0)+row['total_cost']
                row['timestamp']=str(timestamp);row['soc_pct']=row['soc_kwh']/b.capacity_kwh*100
                row['planned_charge_kw']=float(charge);row['planned_discharge_kw']=float(discharge)
                row['clip_retained_energy_kwh']=row['clip_discharge_kwh']/b.discharge_efficiency-row['clip_charge_kwh']*b.charge_efficiency
                # Local comparison of requested vs executed action, not a feasible counterfactual trajectory.
                row['clip_local_cost_delta']=row['clip_discharge_kwh']*(p[h]-b.degradation_per_kwh)-row['clip_charge_kwh']*(p[h]+b.degradation_per_kwh)
                traces[key].append(row);energies[key]=row['soc_kwh']
            for key in rolling_keys:errors[key]=float(actual[h]-bases[key][h])
        for key in traces:terminal_errors[key].append(abs(energies[key]-initial))
    stage('evaluating',89,'复算七策略费用、裁剪归因、日终SOC及公平性')
    strategies=[];b0=sum(r['total_cost'] for r in traces['B0'])
    for key,rows in traces.items():
        total=sum(r['total_cost'] for r in rows);terminal=max(terminal_errors[key])
        simul=sum(r['charge_kw']>1e-6 and r['discharge_kw']>1e-6 for r in rows)
        violation=max(r['soc_violation_kwh'] for r in rows);grid_violation=sum(max(0,-r['grid_kw']) for r in rows)
        balance=max(r['balance_error_kwh'] for r in rows)
        valid=terminal<1e-5 and simul==0 and violation<1e-5 and grid_violation<1e-5 and balance<1e-5 and status_counts[key]['failed']==0
        if key=='L1' and not report['hgb_available']:valid=False
        planned=plan_costs[key] if key in (*rolling_keys,'O1') else None
        s={'id':key,'name':names[key],'energy_cost':sum(r['energy_cost'] for r in rows),'degradation_cost':sum(r['degradation_cost'] for r in rows),'total_cost':total,
            'savings_vs_b0':b0-total,'savings_pct':(b0-total)/b0*100 if b0 else None,'peak_grid_kw':max(r['grid_kw'] for r in rows),
            'charge_kwh':sum(r['charge_kw'] for r in rows),'discharge_kwh':sum(r['discharge_kw'] for r in rows),'throughput_kwh':sum(r['charge_kw']+r['discharge_kw'] for r in rows),
            'terminal_error_kwh':terminal,'terminal_errors_by_day_kwh':terminal_errors[key],'max_soc_violation_kwh':violation,'simultaneous_count':int(simul),'grid_violation_kwh':grid_violation,
            'max_balance_error_kwh':balance,'clip_kwh':sum(r['clip_kwh'] for r in rows),'forecast_plan_cost':planned,'plan_replay_gap':total-planned if planned is not None else None,
            'forecast_plan_cost_scope':'Sum of midnight day-ahead plans; prediction base cost differs from observed base cost, gap is NOT clipping cost' if key in rolling_keys else 'Actual oracle objective' if key=='O1' else None,
            'solver':status_counts[key],'margin_plan_failures':status_counts[key]['margin_plan_failed'],'fallback_count':status_counts[key]['fallback'],'comparison_valid':bool(valid)}
        for field in ('clip_no_export_kwh','clip_soc_kwh','clip_power_kwh','clip_charge_kwh','clip_discharge_kwh','clip_retained_energy_kwh','clip_local_cost_delta'):s[field]=sum(r[field] for r in rows)
        strategies.append(s)
    series=[]
    for i,(timestamp,row) in enumerate(forecast.iterrows()):
        series.append({'timestamp':str(timestamp),'actual_kw':float(row.load_kw),'forecast_kw':float(row.forecast_kw),'hgb_kw':float(row.hgb_kw),'daily_naive_kw':float(row.daily_naive_kw),'weekly_naive_kw':float(row.weekly_naive_kw),'lower_kw':float(row.lower_kw),'upper_kw':float(row.upper_kw),'price':float(prices[i]),
            'strategies':{k:{kk:float(vv) if isinstance(vv,(float,int,np.floating,np.integer)) else vv for kk,vv in traces[k][i].items()} for k in traces}})
    daily=[]
    for di,(date,_) in enumerate(days):
        item={'date':str(date.date())}
        for key in traces:
            item[key+'_cost']=sum(r['total_cost'] for r in traces[key][di*24:(di+1)*24]);item[key+'_terminal_error_kwh']=terminal_errors[key][di]
        item['B2_savings']=item['B0_cost']-item['B2_cost'];daily.append(item)
    warnings=[]
    if report['selected_model']!='HistGradientBoosting':warnings.append(report['selection_reason'])
    if report['improvement_vs_weekly_pct'] is not None and report['improvement_vs_weekly_pct']<0:warnings.append('HGB在历史回归劣于周朴素；不支持AI泛化提升。')
    valid=all(x['comparison_valid'] for x in strategies)
    if not valid:warnings.append('至少一个策略终端SOC、建模约束、学习模型或求解失败；请按各策略有效标记解读，不能作整体公平收益结论。')
    if status_counts['R1']['margin_plan_failed']:warnings.append(f"R1安全余量求解失败{status_counts['R1']['margin_plan_failed']}次，其中{status_counts['R1']['fallback']}次按原约束从相同实际SOC降级求解；风险措施验收仍判失败。")
    if config.stress!='none':warnings.append('合成压力情景；原始预测评分在扰动前计算，另附压力回放误差。')
    warnings.append('十二月是已公开历史回归；其他时段默认探索，均不是新的独立泛化验证。' if reference_dataset else '导入CSV按探索性区间评估；用户授权声明不等于来源真实性或独立泛化证据。')
    report['interval_coverage_scope']='Unperturbed historical/exploratory evaluation only; not stress coverage'
    report['replay_forecast_metrics']=metrics(forecast.load_kw,forecast.forecast_kw,'Selected forecast under replay stress')
    protocol=Path(__file__).resolve().parents[2]/'docs'/'evaluation-protocol-v2.md'
    result={'schema_version':'2.0.0','run_id':run_id,'generated_at':datetime.now(timezone.utc).isoformat(),
        'summary':{'period_start':str(forecast.index[0]),'period_end':str(forecast.index[-1]),'hours':len(forecast),'days':len(days),'source_label':'真实公开负荷 + 合成电池/电价情景' if reference_dataset else '用户声明授权负荷 + 参数化电池/电价情景','warnings':warnings,'elapsed_seconds':time.perf_counter()-start_time,'selected_model':report['selected_model'],'recommended_strategy':'B2','comparison_valid':bool(valid)},
        'config':config.model_dump(),'dataset':meta,'forecast':report,'strategies':strategies,'series':series,'daily':daily,'solver_audit':solver_audit,'strategy_solver_audit':strategy_solver_audit,'assumptions':assumptions,
        'reproducibility':{'python':platform.python_version(),'platform':platform.platform(),'cpu':platform.processor(),'package_versions':{name:version(name) for name in ['numpy','pandas','scipy','scikit-learn','fastapi','pydantic']},'code_sha256':hashlib.sha256(b''.join(p.name.encode()+p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest(),'thread_limit':'sklearn threadpool_limits(1); OMP/OpenBLAS/MKL=1 requested; solver runtime environment','seed':42,'model_parameters':MODEL_PARAMETERS,'evaluation_protocol_id':PROTOCOL_ID,'evaluation_protocol_sha256':hashlib.sha256(protocol.read_bytes()).hexdigest() if protocol.exists() else None,'config_sha256':hashlib.sha256(json.dumps(config.model_dump(exclude={'idempotency_key'}),sort_keys=True).encode()).hexdigest()},
        'artifacts':{ext:f'/api/runs/{run_id}/export/{ext}' for ext in ['json','csv','html']}}
    byid={s['id']:s for s in strategies}
    def ablation(candidate,baseline):
        inc=byid[baseline]['total_cost']-byid[candidate]['total_cost']
        return {'baseline':baseline,'candidate':candidate,'incremental_savings':inc,'incremental_savings_pct':inc/byid[baseline]['total_cost']*100 if byid[baseline]['total_cost'] else None,'comparison_valid':byid[baseline]['comparison_valid'] and byid[candidate]['comparison_valid'],'conclusion':'Same optimizer and causal correction isolate forecast choice, not total battery arbitrage benefit.','actions_changed_hours':sum(abs(a['charge_kw']-n['charge_kw'])+abs(a['discharge_kw']-n['discharge_kw'])>1e-5 for a,n in zip(traces[candidate],traces[baseline]))}
    result['ablation']=ablation('B2','N1');result['learning_ablation']=ablation('L1','N1')
    base=byid['B2'];risk=byid['R1'];reduction=base['clip_kwh']-risk['clip_kwh']
    retained=risk['savings_vs_b0']/base['savings_vs_b0']*100 if base['savings_vs_b0']>0 else None
    activity=risk['throughput_kwh']/base['throughput_kwh'] if base['throughput_kwh']>1e-9 else None
    reduction_pct=reduction/base['clip_kwh']*100 if base['clip_kwh']>1e-9 else None
    risk_valid=base['comparison_valid'] and risk['comparison_valid']
    gate=bool(risk_valid and risk['margin_plan_failures']==0 and reduction_pct is not None and reduction_pct>=10 and retained is not None and retained>=90 and activity is not None and activity>=.8)
    result['risk_ablation']={'baseline':'B2','candidate':'R1','margin_scale':config.risk_margin_scale,'clip_reduction_kwh':reduction,'clip_reduction_pct':reduction_pct,'cost_increase':risk['total_cost']-base['total_cost'],'retained_savings_pct':retained,'throughput_ratio':activity,'comparison_valid':risk_valid,'margin_plan_failures':risk['margin_plan_failures'],'fallback_count':risk['fallback_count'],'predefined_gate_passed':gate,'thresholds':{'min_clip_reduction_pct':10,'min_retained_savings_pct':90,'min_throughput_ratio':.8,'max_margin_plan_failures':0},'conclusion':'该回归情景达到预定风险/代价阈值，仍不构成独立泛化证据或自动部署推荐。' if gate else '未达到全部预定风险/代价阈值或发生余量降级；保留失败与收益损失，不推荐切换。'}
    hgb_improvement=report['improvement_vs_weekly_pct']
    checks=[{'id':'constraint_comparison','triggered':not valid,'evidence':'存在无效策略，须逐项核对' if not valid else '全部策略建模约束与每日终端通过'},
        {'id':'holdout_ai_improvement','triggered':hgb_improvement is None or hgb_improvement<=0,'evidence':f'HGB相对周朴素历史回归WAPE改善={hgb_improvement}%；此回归不是新泛化证据'},
        {'id':'action_clipping','triggered':base['clip_kwh']>1e-6,'evidence':f"B2裁剪={base['clip_kwh']:.6f}kWh，其中禁止反送电={base['clip_no_export_kwh']:.6f}kWh；局部费用影响不是全轨迹损失"},
        {'id':'positive_scenario_savings','triggered':base['savings_vs_b0']<=0,'evidence':f"B2相对无储能节费={base['savings_vs_b0']:.6f}"}]
    for check in checks:check['triggered']=bool(check['triggered'])
    result['validation_conclusion']={'verdict':'存在无效策略，不能作整体公平收益结论' if not valid else '历史情景计算完成；仅支持继续影子验证，尚无新独立泛化证据',
        'rules':checks,'policy':'透明工程验收，不是实机认证或投资建议；任一裁剪均需复核。','next_steps':['取得授权站点的新时间窗，在首次查看之前冻结协议与哈希。','独立核对学习模型增量和风险余量的节费/吞吐代价。','真实设备只可在另行授权并完成现场安全验证后讨论接入。'],'hardware_control':False,'safety_certification':False}
    stage('exporting',96,'保存可复算JSON、逐小时CSV和独立HTML报告')
    return result
