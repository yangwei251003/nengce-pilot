"""Independent final ledger checks; no application billing/dispatch imports."""
import calendar
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'qa/v3/reproduction-clean/offline-evidence'
DEST = ROOT / 'qa/v3/final-replay-suite'
if not DEST.exists():
    shutil.copytree(SOURCE, DEST)
report = {'status': 'PASS', 'scope': 'Independent arithmetic of executed traces, not a declaration of feasible planning', 'cases': []}
for folder in sorted(p for p in DEST.iterdir() if p.is_dir()):
    file = folder / 'result.json'
    result = json.loads(file.read_text(encoding='utf-8'))
    battery = result['config']['battery']
    rate = result['config']['tariff']['demand_per_kw']
    checks = []
    for strategy in result['strategies']:
        sid = strategy['id']
        energy = proxy = clip = 0.0
        peaks = defaultdict(float)
        soc = battery['capacity_kwh'] * battery['initial_soc']
        errors = {'soc_transition': 0., 'ac_balance': 0., 'power': 0., 'soc_bounds': 0., 'no_export': 0., 'simultaneous': 0.}
        for row in result['series']:
            a = row['strategies'][sid]
            dt = row['interval_hours']
            energy += a['grid_kw'] * row['price'] * dt
            proxy += (a['charge_kw'] + a['discharge_kw']) * dt * battery['degradation_per_kwh']
            clip += a['clip_kwh']
            peaks[row['timestamp'][:7]] = max(peaks[row['timestamp'][:7]], a['grid_kw'])
            next_soc = soc + (a['charge_kw'] * battery['charge_efficiency'] - a['discharge_kw'] / battery['discharge_efficiency']) * dt
            errors['soc_transition'] = max(errors['soc_transition'], abs(next_soc-a['soc_kwh']))
            errors['ac_balance'] = max(errors['ac_balance'], abs(a['grid_kw']+row['pv_kw']-a['curtailment_kw']+a['discharge_kw']-row['actual_kw']-a['charge_kw'])*dt)
            errors['power'] = max(errors['power'], a['charge_kw']-battery['power_kw'], a['discharge_kw']-battery['power_kw'])
            errors['soc_bounds'] = max(errors['soc_bounds'], a['soc_kwh']-battery['capacity_kwh']*battery['max_soc'], battery['capacity_kwh']*battery['min_soc']-a['soc_kwh'])
            errors['no_export'] = max(errors['no_export'], -a['grid_kw'])
            errors['simultaneous'] += int(a['charge_kw']>1e-7 and a['discharge_kw']>1e-7)
            soc = a['soc_kwh']
        demand = sum(peaks.values()) * rate
        errors.update(energy=abs(energy-strategy['energy_cost']), throughput=abs(proxy-strategy['degradation_cost']), demand=abs(demand-strategy['demand_cost']), total=abs(energy+proxy+demand-strategy['total_cost']), clipping=abs(clip-strategy['clip_kwh']))
        monthly = []
        for bill in strategy['monthly_bills']:
            y,m = map(int,bill['month'].split('-'))
            count = sum(r['timestamp'].startswith(bill['month']) for r in result['series'])
            eligible = rate == 0 or (result['series'][0]['interval_hours']==.25 and count==calendar.monthrange(y,m)[1]*96 and bill['complete_observed_month'])
            monthly.append({'month':bill['month'],'intervals':count,'eligible_for_this_example_contract':eligible,'peak_error':abs(peaks[bill['month']]-bill['peak_grid_kw'])})
        passed = max(errors.values())<1e-6 and all(b['eligible_for_this_example_contract'] and b['peak_error']<1e-6 for b in monthly)
        checks.append({'strategy':sid, 'arithmetic_status':'PASS' if passed else 'FAIL','errors':errors,'independent_total':energy+proxy+demand,'monthly':monthly,'planner_physical_valid':strategy['physical_valid'],'comparison_valid':strategy['comparison_valid'],'terminal_error_kwh':strategy['terminal_error_kwh']})
    ok = all(c['arithmetic_status']=='PASS' for c in checks)
    report['cases'].append({'case':folder.name,'status':'PASS' if ok else 'FAIL','sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'engine_seconds':result['summary']['elapsed_seconds'],'comparison_valid':result['summary']['comparison_valid'],'physical_valid':result['summary']['physical_valid'],'checks':checks})
    if not ok: report['status']='FAIL'
report['engine_seconds_total'] = sum(c['engine_seconds'] for c in report['cases'])
(ROOT/'qa/v3/final-independent-rebill.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'cases':len(report['cases']),'strategies':sum(len(c['checks']) for c in report['cases']),'engine_seconds_total':report['engine_seconds_total']}))
raise SystemExit(0 if report['status']=='PASS' else 1)
