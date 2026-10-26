import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from pydantic import ValidationError
from backend.config import Battery,RunConfig
from backend.data import reference_data
from backend.forecast import train_forecasts,select_model
from backend.planner import solve_plan,solve_risk_plan,execute_step
from backend.engine import run_experiment,risk_discharge_limit


class V2ReliabilityTests(unittest.TestCase):
    def test_bad_planner_values_are_rejected(self):
        for load,prices in [([1],[np.nan]),([1],[np.inf]),([1],[-1]),([[1]],[[1]]),([],[]),([1,2],[1])]:
            with self.subTest(load=load,prices=prices),self.assertRaises(ValueError):solve_plan(load,prices,Battery())
        for kwargs in [{'initial_kwh':np.nan},{'target_kwh':99},{'time_limit':np.inf},{'discharge_limit':[np.nan]},{'discharge_limit':[2]}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):solve_plan([1],[1],Battery(),**kwargs)

    def test_invalid_executor_and_simultaneous_request_rejected_before_clipping(self):
        for args in [(np.nan,0,0,50),(5,-1,0,50),(0,1,1,50),(0,0,0,100)]:
            with self.subTest(args=args),self.assertRaises(ValueError):execute_step(*args,Battery())

    def test_clipping_causes_partition_and_energy_effect(self):
        r=execute_step(2,0,70,20,Battery())
        self.assertAlmostEqual(r['clip_power_kwh'],30)
        self.assertAlmostEqual(r['clip_soc_kwh'],30.5)
        self.assertAlmostEqual(r['clip_no_export_kwh'],7.5)
        self.assertAlmostEqual(r['clip_kwh'],68)
        self.assertAlmostEqual(sum(r[k] for k in ('clip_power_kwh','clip_soc_kwh','clip_no_export_kwh')),r['clip_kwh'])

    def test_margin_changes_constraint_not_base_energy_fee(self):
        b=Battery(degradation_per_kwh=100)
        p=solve_plan([10,20],[1,1],b,discharge_limit=[0,0])
        self.assertTrue(p['feasible']);self.assertAlmostEqual(p['forecast_plan_cost'],30)
        limit,margin=risk_discharge_limit(np.array([10,100]),{'positive_overprediction_q75_kw':20,'cap_fraction':.35},1)
        np.testing.assert_allclose(limit,[6.5,80]);np.testing.assert_allclose(margin,[3.5,20])

    def test_selection_threshold_and_simple_tie_policy(self):
        def score(x):return {'mae_kw':x,'name':str(x)}
        simple=[score(9.9),score(10),score(10)];folds=[{'models':simple}]*3
        self.assertEqual(select_model(simple,folds)[0],2)
        scores=[score(9),score(10),score(10)]
        self.assertEqual(select_model(scores,[{'models':scores}]*3)[0],0)
        self.assertEqual(select_model(scores,[{'models':scores}]*3,failed=True)[0],2)

    def test_risk_scale_invalid(self):
        for value in (-.1,1.01,float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaises(ValidationError):RunConfig(risk_margin_scale=value)

    def test_infeasible_margin_degrades_same_soc_and_keeps_failure(self):
        p=solve_risk_plan([10],[1],Battery(),[6.5],initial_kwh=60,target_kwh=50)
        self.assertTrue(p['feasible']);self.assertTrue(p['fallback_used']);self.assertTrue(p['margin_plan_failed'])
        self.assertEqual(p['margin_plan_status'],'infeasible')
        self.assertAlmostEqual(p['soc_kwh'][-1],50);self.assertAlmostEqual(p['discharge_kw'][0],9.5)

    def test_both_margin_and_original_infeasible_never_fake_action(self):
        p=solve_risk_plan([1],[1],Battery(),[.65],initial_kwh=90,target_kwh=10)
        self.assertFalse(p['feasible']);self.assertFalse(p['fallback_used']);self.assertTrue(p['margin_plan_failed'])
        self.assertNotIn('charge_kw',p);self.assertEqual(p['status'],'infeasible')

    def test_timezone_aware_forecast_and_bad_partial_date(self):
        idx=pd.date_range('2024-01-01',periods=24*90,freq='h',tz='Asia/Shanghai')
        f=pd.DataFrame({'load_kw':20+np.sin(np.arange(len(idx))*np.pi/12)},index=idx)
        out,r=train_forecasts(f,'2024-03-20','2024-03-20')
        self.assertEqual(len(out),24);self.assertEqual(str(out.index.tz),'Asia/Shanghai')
        self.assertEqual(r['evaluation_role'],'exploratory_subperiod')
        with self.assertRaises(ValueError):train_forecasts(f,'2024-03-20 00:01','2024-03-20')
        bad=f.copy();bad.iloc[40,0]=np.inf
        with self.assertRaises(ValueError):train_forecasts(bad,'2024-03-20','2024-03-20')

    def test_future_change_does_not_change_selection_margin_or_current_day(self):
        f,_=reference_data();altered=f.copy();altered.loc['2018-12-02':,'load_kw']=99999
        a,ra=train_forecasts(f,'2018-12-01','2018-12-01')
        z,rz=train_forecasts(altered,'2018-12-01','2018-12-01')
        self.assertEqual(ra['selected_model'],rz['selected_model']);self.assertEqual(ra['risk_calibration'],rz['risk_calibration'])
        np.testing.assert_allclose(a.forecast_kw,z.forecast_kw);np.testing.assert_allclose(a.hgb_kw,z.hgb_kw)
        self.assertEqual(ra['evaluation_role'],'historical_regression')
        self.assertTrue(all(x['train_end']<x['start'] for x in ra['rolling_validation']))

    def test_zero_margin_full_replay_equivalence_and_independent_cost(self):
        c=RunConfig(risk_margin_scale=0);c.evaluation.end='2018-12-02'
        r=run_experiment(c,'zero-margin-ablation');byid={s['id']:s for s in r['strategies']}
        self.assertEqual(len(byid),7)
        for key in ('total_cost','clip_kwh','charge_kwh','discharge_kwh','terminal_error_kwh'):
            self.assertAlmostEqual(byid['B2'][key],byid['R1'][key],places=6)
        for key,s in byid.items():
            total=0
            for row in r['series']:
                v=row['strategies'][key]
                total+=(row['actual_kw']+v['charge_kw']-v['discharge_kw'])*row['price']+(v['charge_kw']+v['discharge_kw'])*c.battery.degradation_per_kwh
                self.assertAlmostEqual(v['clip_kwh'],v['clip_power_kwh']+v['clip_soc_kwh']+v['clip_no_export_kwh'],places=6)
            self.assertAlmostEqual(total,s['total_cost'],places=6)
        self.assertEqual(len(r['solver_audit']),48);self.assertEqual(len(r['strategy_solver_audit']),48*4)
        self.assertEqual(r['summary']['recommended_strategy'],'B2')
        self.assertTrue(all(x['comparison_valid'] for x in r['strategies']))

    def test_uploaded_dataset_not_mislabeled_public_uci_history(self):
        f,m=reference_data();m=dict(m,dataset_id='csv-fixture',timezone='Asia/Shanghai',source_type='user_authorized_observed')
        c=RunConfig(dataset_id='csv-fixture');c.evaluation.end='2018-12-01'
        with patch('backend.engine.load_dataset',return_value=(f,m)):r=run_experiment(c,'csv-source-metadata')
        self.assertEqual(r['summary']['source_label'],'用户声明授权负荷 + 参数化电池/电价情景')
        self.assertEqual(r['forecast']['evaluation_role'],'exploratory_subperiod')
        self.assertIn('Asia/Shanghai',r['assumptions'][1]);self.assertIn('不对导入数据套用UCI午夜修正',r['assumptions'][1])
        self.assertFalse(any('韩国钢厂' in x or '2018年12月已公开' in x for x in r['assumptions']))

if __name__=='__main__':unittest.main()
