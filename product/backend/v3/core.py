"""V3 experiment orchestration. Results preserve physical and scientific verdicts."""
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from .billing import local_index, monthly_bills, price_vector
from .forecast import MODEL_PARAMETERS, metrics, train_forecasts
from .planner import execute_step, solve_plan, solve_risk_plan, terminal_action


class Cancelled(Exception):
    pass


NAMES = {'B0': '无储能', 'B1': '固定峰谷规则', 'B2': '开发验证所选预测 + 滚动优化',
         'N1': '周朴素预测 + 同一滚动优化器', 'L1': '固定HGB学习预测 + 同一优化器',
         'O1': '逐日完美预知诊断，不可部署', 'R1': '所选预测 + 固定误差余量',
         'R2': '所选预测 + 终端可达余量预算'}

ASSUMPTIONS = [
    '公开数据或用户声明授权数据配示例人民币电价和电池；不是已实现客户收益。',
    '仅含分时购电能量费、符合条件的完整15分钟月份示例最大需量费；AC吞吐衰减代理单列，不是供电账单或真实寿命。',
    '已知时区按来源日历计价；未知UCI时区只按source-local示例月份计价，实际合同及行政时区未核验。',
    '光伏仅取同站原始计量；禁止反送，剩余光伏明确弃光。无售电、进口容量上限、合同罚金、税费或投资回报。',
    '实际SOC跨日连续且不重置；全部电池策略使用相同每日末SOC目标，限制跨日移能。末区间物理修复单独记录，失败不隐去。',
    '部署策略仅见冻结日前预测与已完成区间；当前实际量仅在执行保护和最后区间终端修复时揭示。',
    'O1只使用逐日实际未来作诊断；不是整月联合最优下界，不是可部署策略，也不计为AI效果。',
    'R2先最小化为恢复共同终端可达性所需释放的AC侧余量，再按这个最小预算优化费用；不放宽功率、SOC、效率或禁止反送约束。',
    '压力情景是合成扰动；原始预测评分与压力回放评分分别报告，不能当作现场适应验证。',
    '任务执行成功、物理比较有效、科学候选通过分别报告；学习模型未胜开发基线就回退，风险候选不会依据留出结果自动成为推荐。'
]


def _float_record(row):
    return {key: float(value) if isinstance(value, (float, int, np.floating, np.integer)) else value for key, value in row.items()}


def recommend_strategy(strategies):
    """Predeclared validity fallback only; no selection by retrospective savings."""
    by_id={strategy['id']:strategy for strategy in strategies}
    for key in ('B2','B1','B0'):
        if by_id.get(key,{}).get('comparison_valid'):
            return key, ('开发规则选定方案通过本场景有效性检查。' if key=='B2' else
                         f'B2未通过完整有效性检查，按固定安全顺序回退到{NAMES[key]}；未按本次节费挑选赢家。')
    return None, '尚无物理与完整计费均有效的方案，仅可查看诊断；需补齐数据或修正约束。'


def run_experiment(config, run_id, progress=None, cancelled=None):
    from .data import load_dataset

    before = time.perf_counter()
    engine_paths = [Path(__file__).parent/name for name in ('core.py','planner.py','forecast.py','billing.py','config.py','data.py')]
    code_digest = lambda: hashlib.sha256(b''.join(p.name.encode()+p.read_bytes() for p in engine_paths)).hexdigest()
    start_code_hash = code_digest()

    def stage(name, percent, message):
        if cancelled and cancelled():
            raise Cancelled('用户取消运行')
        if progress:
            progress(name, percent, message)

    stage('validating', 3, '核对数据身份、时间间隔、光伏边界与示例计费合同')
    frame, metadata = load_dataset(config.dataset_id)
    metadata = dict(metadata)
    scope = metadata.get('scope', {})
    if isinstance(scope, dict) and scope.get('dispatch') is False:
        raise ValueError('该来源缺少可核实的整站负荷边界，不能用于调度：' + str(scope.get('reason', '数据用途受限')))
    frame = frame.copy()
    if 'pv_kw' not in frame:
        frame['pv_kw'] = 0.
    frame.index = local_index(frame.index, metadata)
    dt = (frame.index[1]-frame.index[0]).total_seconds()/3600
    if config.tariff.prices and len(config.tariff.prices) == 96 and dt == 1:
        raise ValueError('小时来源不能冒充15分钟价格下的实测计费；请使用24项电价')
    stage('forecasting', 10, '按冻结开发规则对照负荷与光伏预测，留出结果不参与选模')
    requested = frame.loc[config.evaluation.start:config.evaluation.end]
    if requested[['load_kw','pv_kw']].isna().any().any() or ('observed' in requested and not requested.observed.all()):
        raise ValueError('调度回放区间存在缺失或插补真值，只能先作质量诊断；不能伪造真实执行费用')
    forecast, report = train_forecasts(frame, config.evaluation.start, config.evaluation.end, metadata, config.protocol_id)
    if config.stress == 'load_up_20':
        forecast['load_kw'] *= 1.2
    elif config.stress == 'pv_drop_30':
        forecast['pv_kw'] *= .7
    elif config.stress == 'forecast_bias_up_20':
        forecast[['forecast_kw', 'hgb_kw', 'daily_naive_kw', 'weekly_naive_kw']] *= 1.2
    index = forecast.index
    prices = price_vector(index, config.tariff, config.stress)
    b = config.battery; target = b.capacity_kwh*b.initial_soc
    traces = {key: [] for key in NAMES}
    energy = {key: target for key in NAMES}
    peak = {key: 0. for key in NAMES}
    statuses = {key: {'optimal':0, 'feasible':0, 'failed':0, 'margin_plan_failed':0, 'fallback':0} for key in NAMES}
    planned_cost = {key: 0. for key in NAMES}
    terminal_errors = {key: [] for key in NAMES}
    audits, daily, active_month = [], [], None
    days = list(forecast.groupby(index.normalize()))
    rolling = ('B2', 'N1', 'L1', 'R1', 'R2')
    demand_rate = config.tariff.demand_per_kw if dt == .25 else 0.
    previous_errors = {key: (0., 0.) for key in rolling}
    for day_number, (date, day) in enumerate(days):
        stage('replaying', 20+int(64*day_number/len(days)), f'回放 {date.date()} · 第 {day_number+1}/{len(days)} 天')
        if str(date.strftime('%Y-%m')) != active_month:
            active_month = str(date.strftime('%Y-%m'))
            peak = {key: 0. for key in NAMES}
        load, pv = day.load_kw.to_numpy(), day.pv_kw.to_numpy()
        p = price_vector(day.index, config.tariff, config.stress)
        bases = {'B2': day.forecast_kw.to_numpy(), 'N1': day.weekly_naive_kw.to_numpy(),
                 'L1': day.hgb_kw.to_numpy(), 'R1':day.forecast_kw.to_numpy(), 'R2':day.forecast_kw.to_numpy()}
        pv_bases = {'B2':day.pv_forecast_kw.to_numpy(), 'N1':day.pv_weekly_naive_kw.to_numpy(),
                    'L1':day.pv_hgb_kw.to_numpy(), 'R1':day.pv_forecast_kw.to_numpy(), 'R2':day.pv_forecast_kw.to_numpy()}
        # A new day-ahead forecast already incorporates the completed day.
        previous_errors = {key: (0., 0.) for key in rolling}
        oracle = solve_plan(load, pv, p, b, dt, energy['O1'], target, peak['O1'], demand_rate)
        statuses['O1']['optimal' if oracle['optimal'] else 'feasible' if oracle['feasible'] else 'failed'] += 1
        if oracle['feasible']:
            planned_cost['O1'] += oracle['forecast_plan_cost']
        day_begin = len(traces['B0'])
        for j, timestamp in enumerate(day.index):
            if cancelled and cancelled():
                raise Cancelled('用户取消运行')
            actions = {'B0': (0.,0.), 'O1': (float(oracle['charge_kw'][j]),float(oracle['discharge_kw'][j])) if oracle['feasible'] else (0.,0.)}
            relaxation = {key: 0. for key in NAMES}
            cache = {}
            for key in rolling:
                decay = np.exp(-np.arange(len(day)-j)*dt/6)
                prediction = np.maximum(0, bases[key][j:]+.5*previous_errors[key][0]*decay)
                pv_prediction = np.maximum(0, pv_bases[key][j:]+.5*previous_errors[key][1]*decay)
                net = np.maximum(0, prediction-pv_prediction)
                risk_scale = config.risk_margin_scale if key in ('R1','R2') else 0.
                margin = np.minimum(report['risk_calibration']['positive_overprediction_q75_kw'], .35*net)*risk_scale
                limits = np.maximum(0, net-margin)
                kwargs = dict(dt=dt, initial_kwh=energy[key], target_kwh=target, peak_so_far=peak[key], demand_rate=demand_rate)
                cache_key = (prediction.tobytes(), pv_prediction.tobytes(), round(energy[key],9), round(peak[key],9),
                             key if risk_scale else 'base', margin.tobytes())
                if cache_key not in cache:
                    cache[cache_key] = solve_risk_plan(prediction,pv_prediction,p[j:],b,limits,mode=key,**kwargs) if risk_scale else solve_plan(prediction,pv_prediction,p[j:],b,**kwargs)
                plan = cache[cache_key]
                statuses[key]['optimal' if plan['optimal'] else 'feasible' if plan['feasible'] else 'failed'] += 1
                statuses[key]['margin_plan_failed'] += int(plan.get('margin_plan_failed',False))
                statuses[key]['fallback'] += int(plan.get('fallback_used',False))
                if j == 0 and plan['feasible']:
                    planned_cost[key] += plan['forecast_plan_cost']
                actions[key] = (float(plan['charge_kw'][0]),float(plan['discharge_kw'][0])) if plan['feasible'] else (0.,0.)
                relaxation[key] = float(plan.get('margin_relaxation_kw',np.zeros(1))[0]) if plan['feasible'] else 0.
                audits.append({'strategy':key, 'timestamp':str(timestamp), 'horizon_hours':(len(day)-j)*dt,
                               'horizon_intervals':len(day)-j, 'initial_kwh':energy[key], 'target_kwh':target,
                               'status':plan['status'], 'mip_gap':plan['mip_gap'], 'elapsed_seconds':plan['elapsed_seconds'],
                               'forecast_origin':str(date), 'latest_observation':str(timestamp-pd.Timedelta(hours=dt)),
                               'first_forecast_kw':float(prediction[0]), 'first_pv_forecast_kw':float(pv_prediction[0]),
                               'first_discharge_limit_kw':float(limits[0]), 'first_safety_margin_kw':float(margin[0]),
                               'margin_relaxation_kw':relaxation[key], 'minimum_margin_relaxation_kwh':plan.get('minimum_margin_relaxation_kwh',0.),
                               'margin_plan_status':plan.get('margin_plan_status'), 'margin_plan_failed':bool(plan.get('margin_plan_failed',False)),
                               'fallback_used':bool(plan.get('fallback_used',False)), 'fallback_kind':plan.get('fallback_kind'),
                               'independent_max_residual':plan.get('independent_max_residual'),
                               'first_charge_kw':actions[key][0], 'first_discharge_kw':actions[key][1], 'peak_so_far_kw':peak[key]})
            charge = discharge = 0.
            if timestamp.hour in config.tariff.offpeak_hours and timestamp.hour < 7:
                charge = min(b.power_kw,max(0.,(b.capacity_kwh*b.max_soc-energy['B1'])/(b.charge_efficiency*dt)))
            elif timestamp.hour in config.tariff.peak_hours or timestamp.hour >= 21:
                discharge = min(b.power_kw,max(0.,(energy['B1']-target)*b.discharge_efficiency/dt))
            if timestamp.hour >= 22 and energy['B1'] < target:
                charge, discharge = min(b.power_kw,(target-energy['B1'])/(b.charge_efficiency*dt)), 0.
            actions['B1'] = charge, discharge
            for key, (requested_charge, requested_discharge) in actions.items():
                c, d = requested_charge, requested_discharge
                repair = 0.
                unrepaired = None
                if j == len(day)-1 and key != 'B0':
                    unrepaired = execute_step(load[j],pv[j],requested_charge,requested_discharge,energy[key],b,dt)
                    c, d = terminal_action(load[j],pv[j],energy[key],target,b,dt)
                    repair = (abs(c-requested_charge)+abs(d-requested_discharge))*dt
                row = execute_step(load[j],pv[j],c,d,energy[key],b,dt)
                row.update(timestamp=str(timestamp),interval_hours=dt,soc_pct=row['soc_kwh']/b.capacity_kwh*100,
                           planned_charge_kw=requested_charge,planned_discharge_kw=requested_discharge,
                           terminal_repair_kwh=repair, margin_relaxation_kw=relaxation[key],
                           cost_scope='energy_plus_throughput_proxy; monthly demand billed separately once')
                row['energy_cost'] = row['grid_kw']*p[j]*dt
                row['degradation_cost'] = (row['charge_kw']+row['discharge_kw'])*dt*b.degradation_per_kwh
                row['total_cost'] = row['energy_cost']+row['degradation_cost']
                row['execution_deviation_kwh'] = (abs(requested_charge-row['charge_kw'])+abs(requested_discharge-row['discharge_kw']))*dt
                row['terminal_repair_local_cost_delta'] = (row['total_cost']-(unrepaired['grid_kw']*p[j]*dt+(unrepaired['charge_kw']+unrepaired['discharge_kw'])*dt*b.degradation_per_kwh)) if unrepaired is not None else 0.
                row['cumulative_cost'] = (traces[key][-1]['cumulative_cost'] if traces[key] else 0)+row['total_cost']
                row['clip_retained_energy_kwh'] = row['clip_discharge_kwh']/b.discharge_efficiency-row['clip_charge_kwh']*b.charge_efficiency
                row['clip_local_cost_delta'] = row['clip_discharge_kwh']*(p[j]-b.degradation_per_kwh)-row['clip_charge_kwh']*(p[j]+b.degradation_per_kwh)
                traces[key].append(row)
                energy[key] = row['soc_kwh']; peak[key] = max(peak[key],row['grid_kw'])
            for key in rolling:
                previous_errors[key] = float(load[j]-bases[key][j]),float(pv[j]-pv_bases[key][j])
        item = {'date':str(date.date()),'intervals':len(day),'hours':len(day)*dt}
        for key in NAMES:
            error = abs(energy[key]-target); terminal_errors[key].append(error)
            item[key+'_cost'] = sum(row['total_cost'] for row in traces[key][day_begin:])
            item[key+'_terminal_error_kwh'] = error
        item['B2_savings'] = item['B0_cost']-item['B2_cost']
        item['cost_scope'] = 'energy_plus_throughput_proxy_only; monthly demand billed once at month close'
        daily.append(item)
    stage('evaluating', 89, '独立汇总八策略能量、月峰值、费用、终端误差和风险代价')
    observed = forecast.observed.to_numpy(dtype=bool) if 'observed' in forecast else np.ones(len(index),bool)
    time_basis = str(index.tz) if index.tz else 'source-local-unknown'
    source_eligible=bool(metadata.get('original_observation_verified',True) and (not isinstance(scope,dict) or scope.get('demand_15min',True)))
    bills = {key: monthly_bills(index,rows,dt,config.tariff.demand_per_kw,observed,time_basis,source_eligible) for key,rows in traces.items()}
    totals = {key: sum(bill['total_cost'] for bill in values) if all(bill['total_cost'] is not None for bill in values) else None for key,values in bills.items()}
    strategies = []
    for key, rows in traces.items():
        terminal = max(terminal_errors[key]); simul = sum(r['charge_kw']>1e-6 and r['discharge_kw']>1e-6 for r in rows)
        balance = max(max(r['balance_error_kwh'],r['ac_balance_error_kwh']) for r in rows)
        violation = max(r['soc_violation_kwh'] for r in rows)
        physical = terminal < 1e-5 and simul == 0 and balance < 1e-5 and violation < 1e-5 and statuses[key]['failed'] == 0
        complete = totals[key] is not None
        learning_available = report['hgb_available'] and (report['pv'].get('hgb_available',True))
        valid = bool(physical and complete and (key != 'L1' or learning_available))
        total = totals[key]; savings = totals['B0']-total if total is not None and totals['B0'] is not None else None
        planned = planned_cost[key] if key in (*rolling,'O1') else None
        s = {'id':key,'name':NAMES[key],'energy_cost':sum(r['energy_cost'] for r in rows),
             'demand_cost':sum(x['demand_cost'] for x in bills[key]) if complete else None,
             'degradation_cost':sum(r['degradation_cost'] for r in rows),'total_cost':total,
             'known_cost_subtotal':sum(r['total_cost'] for r in rows), 'cost_complete':complete,
             'savings_vs_b0':savings,'savings_pct':savings/totals['B0']*100 if savings is not None and totals['B0'] else None,
             'peak_grid_kw':max(r['grid_kw'] for r in rows), 'charge_kwh':sum(r['charge_kw']*dt for r in rows),
             'discharge_kwh':sum(r['discharge_kw']*dt for r in rows), 'throughput_kwh':sum((r['charge_kw']+r['discharge_kw'])*dt for r in rows),
             'curtailment_kwh':sum(r['curtailment_kw']*dt for r in rows),
             'terminal_error_kwh':terminal,'terminal_errors_by_day_kwh':terminal_errors[key],
             'max_soc_violation_kwh':violation,'simultaneous_count':int(simul),'grid_violation_kwh':0.,
             'max_balance_error_kwh':balance,'forecast_plan_cost':planned,
             'plan_replay_gap':total-planned if total is not None and planned is not None else None,
             'forecast_plan_cost_scope':'Sum of daily-origin predicted energy, proxy and incremental demand objectives; not a feasible whole-month bill or clipping loss',
             'solver':statuses[key],'margin_plan_failures':statuses[key]['margin_plan_failed'],
             'fallback_count':statuses[key]['fallback'],'physical_valid':bool(physical),'comparison_valid':valid,
             'monthly_bills':bills[key]}
        for field in ('clip_kwh','clip_no_export_kwh','clip_soc_kwh','clip_power_kwh','clip_charge_kwh','clip_discharge_kwh','clip_retained_energy_kwh','clip_local_cost_delta','terminal_repair_kwh','execution_deviation_kwh','terminal_repair_local_cost_delta'):
            s[field] = sum(r[field] for r in rows)
        s['margin_relaxation_kwh'] = sum(r['margin_relaxation_kw']*dt for r in rows)
        strategies.append(s)
    byid = {s['id']:s for s in strategies}
    recommendation,recommendation_reason=recommend_strategy(strategies)
    series = []
    fields = ('forecast_kw','hgb_kw','daily_naive_kw','weekly_naive_kw','lower_kw','upper_kw','pv_kw','pv_forecast_kw','pv_lower_kw','pv_upper_kw')
    for i,(timestamp,row) in enumerate(forecast.iterrows()):
        series.append({'timestamp':str(timestamp),'actual_kw':float(row.load_kw),'price':float(prices[i]),'interval_hours':dt,
                       **{field:float(row[field]) for field in fields},
                       'strategies':{key:_float_record(traces[key][i]) for key in NAMES}})

    def ablation(candidate, baseline):
        c,base = byid[candidate],byid[baseline]
        inc = base['total_cost']-c['total_cost'] if c['total_cost'] is not None and base['total_cost'] is not None else None
        return {'baseline':baseline,'candidate':candidate,'incremental_savings':inc,
                'incremental_savings_pct':inc/base['total_cost']*100 if inc is not None and base['total_cost'] else None,
                'comparison_valid':bool(c['comparison_valid'] and base['comparison_valid']),
                'conclusion':'Same optimizer and physics compare forecast selection; total battery benefit is not AI benefit.',
                'actions_changed_hours':sum((abs(a['charge_kw']-n['charge_kw'])+abs(a['discharge_kw']-n['discharge_kw'])>1e-5)*dt for a,n in zip(traces[candidate],traces[baseline]))}

    risks = []
    for candidate in ('R1','R2'):
        base,risk = byid['B2'],byid[candidate]
        reduction = base['clip_kwh']-risk['clip_kwh']
        reduction_pct = reduction/base['clip_kwh']*100 if base['clip_kwh']>1e-9 else None
        retained = risk['savings_vs_b0']/base['savings_vs_b0']*100 if base['savings_vs_b0'] is not None and base['savings_vs_b0']>0 and risk['savings_vs_b0'] is not None else None
        ratio = risk['throughput_kwh']/base['throughput_kwh'] if base['throughput_kwh']>1e-9 else None
        valid = base['comparison_valid'] and risk['comparison_valid']
        # R2 explicitly permits minimal, audited margin release; original R1 does not.
        policy_ok = risk['margin_plan_failures']==0 if candidate=='R1' else risk['solver']['failed']==0
        passed = bool(valid and policy_ok and reduction_pct is not None and reduction_pct>=10 and retained is not None and retained>=90 and ratio is not None and ratio>=.8)
        risks.append({'baseline':'B2','candidate':candidate,'margin_scale':config.risk_margin_scale,
                      'clip_reduction_kwh':reduction,'clip_reduction_pct':reduction_pct,
                      'cost_increase':risk['total_cost']-base['total_cost'] if risk['total_cost'] is not None and base['total_cost'] is not None else None,
                      'retained_savings_pct':retained,'throughput_ratio':ratio,'comparison_valid':bool(valid),
                      'margin_plan_failures':risk['margin_plan_failures'],'fallback_count':risk['fallback_count'],
                      'margin_relaxation_kwh':risk['margin_relaxation_kwh'],'terminal_repair_kwh':risk['terminal_repair_kwh'],
                      'execution_deviation_kwh':risk['execution_deviation_kwh'],
                      'terminal_repair_local_cost_delta':risk['terminal_repair_local_cost_delta'],
                      'predefined_gate_passed':passed,'thresholds':{'min_clip_reduction_pct':10,'min_retained_savings_pct':90,'min_throughput_ratio':.8,'max_solver_failures':0},
                      'conclusion':'达到预定风险与代价阈值；仍不自动成为部署推荐。' if passed else '未达到全部阈值；保留裁剪、代价和终端失败，不推荐自动切换。'})
    valid = all(s['comparison_valid'] for s in strategies)
    physical_valid = all(s['physical_valid'] for s in strategies)
    warnings = []
    if report['selected_model'] != 'HistGradientBoosting':
        warnings.append(report['selection_reason'])
    if not physical_valid:
        warnings.append('至少一项策略的物理／终端／求解检查失败；实际SOC未被重置，不能作整体公平收益结论。')
    if any(s['total_cost'] is None for s in strategies):
        warnings.append('请求了需量费但数据不是完整原生15分钟实测月；需量费、完整总费和节费均不计算。')
    if report['improvement_vs_weekly_pct'] is not None and report['improvement_vs_weekly_pct'] < 0:
        warnings.append('学习预测在本次报告区间劣于周朴素；模型选择只依据先前开发验证，不用此结果临时换赢家。')
    warnings.append('全部费用属于公开／声明授权数据与示例合同，不是已实现客户收益或真实账单。')
    if not report['new_independent_generalization_evidence']:
        warnings.append('此区间是历史回归或探索；不构成新独立泛化证明。')
    report['replay_forecast_metrics'] = metrics(forecast.load_kw,forecast.forecast_kw,'Selected load forecast under replay stress')
    report['interval_coverage_scope'] = 'Unperturbed development-selected evaluation only; not stress coverage'
    protocol_path = Path(__file__).resolve().parents[3]/'docs'/'protocol-v3-data.md'
    result = {'schema_version':'3.0.0','run_id':run_id,'generated_at':datetime.now(timezone.utc).isoformat(),
              'summary':{'period_start':str(index[0]),'period_end':str(index[-1]),'hours':len(index)*dt,'intervals':len(index),
                         'interval_minutes':int(dt*60),'interval_hours':dt,'days':len(days),
                         'source_label':'真实来源负荷／光伏 + 示例电池与计费合同','warnings':warnings,
                         'elapsed_seconds':time.perf_counter()-before,'selected_model':report['selected_model'],
                         'selected_pv_model':report['pv']['selected_model'],'recommended_strategy':recommendation,
                         'recommendation_reason':recommendation_reason,
                         'cumulative_cost_scope':'Interval curves contain energy + throughput proxy; monthly demand is in monthly_bills',
                         'comparison_valid':bool(valid),'physical_valid':bool(physical_valid),
                         'demand_status':sorted(set(bill['demand_status'] for bill in bills['B0']))},
              'config':config.model_dump(),'dataset':metadata,'forecast':report,'strategies':strategies,
              'series':series,'daily':daily,'monthly_bills':bills,'solver_audit':[a for a in audits if a['strategy']=='B2'],
              'strategy_solver_audit':audits,'assumptions':list(ASSUMPTIONS),'ablation':ablation('B2','N1'),
              'learning_ablation':ablation('L1','N1'),'risk_ablation':risks[0],'risk_ablations':risks,
              'reproducibility':{'python':platform.python_version(),'platform':platform.platform(),'cpu':platform.processor(),
                                 'package_versions':{name:version(name) for name in ('numpy','pandas','scipy','scikit-learn','fastapi','pydantic')},
                                 'code_sha256':start_code_hash,'code_changed_during_run':code_digest()!=start_code_hash,
                                 'thread_limit':'sklearn threadpool_limits(1); one application compute worker; HiGHS defaults',
                                 'seed':42,'model_parameters':MODEL_PARAMETERS,'evaluation_protocol_id':config.protocol_id or 'exploratory-unregistered',
                                 'evaluation_protocol_sha256':hashlib.sha256(protocol_path.read_bytes()).hexdigest() if protocol_path.exists() else None,
                                 'config_sha256':hashlib.sha256(json.dumps(config.model_dump(exclude={'idempotency_key'}),sort_keys=True).encode()).hexdigest()},
              'artifacts':{ext:f'/api/v3/runs/{run_id}/export/{ext}' for ext in ('json','csv','html')}}
    result['validation_conclusion'] = {'verdict':'情景计算完成；仅支持影子验证，非设备认证' if valid else '存在无效或不完整比较，请逐项检查',
                                      'rules':[{'id':'constraint_comparison','triggered':not physical_valid,'evidence':'逐策略SOC、AC/DC守恒、终端与独立MILP验解'},
                                               {'id':'billing_completeness','triggered':not all(s['cost_complete'] for s in strategies),'evidence':'需量仅按完整原生15分钟实测月份计收一次'},
                                               {'id':'action_clipping','triggered':byid['B2']['clip_kwh']>1e-6,'evidence':f"B2执行裁剪 {byid['B2']['clip_kwh']:.6f} kWh"}],
                                      'policy':'物理有效、候选科学门槛、任务完成分别判断；禁止把全额电池节费归于AI。',
                                      'next_steps':['核对示例合同与真实站点条件','检查候选的收益代价与失败案例','实际设备接入需要独立现场授权与验收'],
                                      'hardware_control':False,'safety_certification':False}
    stage('exporting', 96, '生成同源曲线、月账、风险与可复算证据')
    return result
