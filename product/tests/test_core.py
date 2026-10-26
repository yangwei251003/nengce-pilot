import unittest,tempfile,json,time
from pathlib import Path
import numpy as np
from pydantic import ValidationError
from backend.config import Battery,RunConfig
from backend.data import reference_data,import_csv
from backend.forecast import feature_matrix,train_forecasts
from backend.planner import solve_plan,execute_step
from backend.engine import run_experiment
from backend.evidence import save_evidence

class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.frame,cls.meta=reference_data()
    def test_real_source_integrity(self):
        self.assertEqual(len(self.frame),8760);self.assertEqual(self.meta['rows_raw'],35040)
        self.assertTrue(self.meta['quality']['energy_conserved'])
        self.assertEqual(str(self.frame.index[0]),'2018-01-01 00:00:00')
        self.assertEqual(str(self.frame.index[-1]),'2018-12-31 23:00:00')
    def test_target_day_features_ignore_target_day_values(self):
        altered=self.frame.copy();day='2018-12-12';altered.loc[day,'load_kw']=999999
        before=feature_matrix(self.frame).loc[day];after=feature_matrix(altered).loc[day]
        np.testing.assert_allclose(before,after)
    def test_every_feature_is_calendar_or_past_load(self):
        X=feature_matrix(self.frame)
        self.assertFalse(any(s in ''.join(X.columns) for s in ['Reactive','CO2','Load_Type','Power_Factor']))
        t=X.index[500];self.assertEqual(X.loc[t,'lag_24h'],self.frame.load_kw.iloc[476])
    def test_bad_csv_reports_original_row(self):
        r=import_csv('timestamp,load_kw\n2018-01-01 00:00,1\n2018-01-01 01:00,-3\n','bad','source-local-unknown','kW',True)
        self.assertFalse(r['valid']);self.assertTrue(any(e['row']==3 for e in r['errors']))
    def test_authorization_required(self):
        self.assertFalse(import_csv('x\n1','no','UTC','kW',False)['valid'])

class PlannerTests(unittest.TestCase):
    def test_hand_calculated_fixture(self):
        b=Battery(capacity_kwh=100,power_kw=20,min_soc=0,max_soc=1,initial_soc=.5,charge_efficiency=1,discharge_efficiency=1,degradation_per_kwh=.01)
        p=solve_plan([20,20,80,80],[.2,.2,1,1],b)
        self.assertTrue(p['optimal']);self.assertAlmostEqual(p['forecast_plan_cost'],136.8,places=6)
        self.assertAlmostEqual(p['soc_kwh'][-1],50,places=6)
    def test_random_feasible_and_invariants(self):
        rng=np.random.default_rng(42)
        for _ in range(12):
            b=Battery();load=rng.uniform(0,150,24);prices=rng.uniform(.2,1.5,24)
            p=solve_plan(load,prices,b);self.assertTrue(p['feasible']);e=50
            for i in range(24):
                r=execute_step(load[i],p['charge_kw'][i],p['discharge_kw'][i],e,b);e=r['soc_kwh']
                self.assertLess(r['balance_error_kwh'],1e-7);self.assertLess(r['soc_violation_kwh'],1e-7)
                self.assertFalse(r['charge_kw']>1e-6 and r['discharge_kw']>1e-6);self.assertGreaterEqual(r['grid_kw'],-1e-7)
            self.assertAlmostEqual(e,50,places=5)
    def test_no_export_actual_safety_clipping(self):
        r=execute_step(3,0,20,80,Battery())
        self.assertEqual(r['discharge_kw'],3);self.assertEqual(r['grid_kw'],0);self.assertEqual(r['clip_kwh'],17)
    def test_invalid_soc_rejected(self):
        with self.assertRaises(ValidationError):Battery(min_soc=.8,initial_soc=.5)
    def test_infeasible_terminal_not_fake_success(self):
        r=solve_plan([0],[1],Battery(),initial_kwh=90,target_kwh=10)
        self.assertFalse(r['feasible']);self.assertEqual(r['status'],'infeasible');self.assertNotIn('charge_kw',r)

class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c=RunConfig();c.evaluation.end='2018-12-03';cls.r=run_experiment(c,'test-three-days')
    def test_full_fairness(self):
        self.assertEqual(self.r['summary']['hours'],72)
        for s in self.r['strategies']:
            self.assertTrue(s['comparison_valid']);self.assertLess(s['terminal_error_kwh'],1e-5)
            self.assertAlmostEqual(s['total_cost'],s['energy_cost']+s['degradation_cost'],places=7)
    def test_future_oracle_explicit(self):
        s={s['id']:s for s in self.r['strategies']}
        self.assertLessEqual(s['O1']['total_cost'],s['B2']['total_cost']+1e-6)
        self.assertIn('不可部署',s['O1']['name']);self.assertIn('N1',s)
    def test_split_precedes_holdout(self):
        f=self.r['forecast'];self.assertEqual(f['train_end'],'2018-10-31 23:00:00')
        self.assertEqual(f['validation_period'][-1],'2018-11-30 23:00:00')
    def test_solver_every_hour_not_one_daily_plan(self):
        a=self.r['solver_audit'];self.assertEqual(len(a),72)
        self.assertEqual(a[0]['horizon_hours'],24);self.assertEqual(a[23]['horizon_hours'],1)
        self.assertTrue(all(r['latest_observation']<r['forecast_origin'] for r in a))
    def test_export_complete_and_finite(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t,'state.json').write_text('{"status":"exporting"}')
            save_evidence(self.r,t);p=Path(t)
            self.assertNotIn('state.json',json.loads((p/'manifest.json').read_text())['sha256'])
            self.assertTrue((p/'manifest.json').exists());self.assertIn('N1_grid_kw',(p/'timeseries.csv').read_text())
            loaded=json.loads((p/'result.json').read_text(encoding='utf-8'));self.assertEqual(loaded['run_id'],'test-three-days')
    def test_zero_denominators_export(self):
        import copy
        r=copy.deepcopy(self.r)
        for s in r['strategies']:s['savings_pct']=None
        for s in r['forecast']['models']:s['wape_pct']=None
        with tempfile.TemporaryDirectory() as t:
            save_evidence(r,t)
            self.assertIn('N/A',Path(t,'report.html').read_text(encoding='utf-8'))
    def test_zero_load_run_is_computed_but_bad_terminal_is_flagged(self):
        from unittest.mock import patch
        f,m=reference_data();f=f.copy();f['load_kw']=0.0
        c=RunConfig();c.evaluation.end='2018-12-01'
        with patch('backend.engine.load_dataset',return_value=(f,m)):
            r=run_experiment(c,'zero-load-fixture')
        self.assertIsNone(r['forecast']['models'][0]['wape_pct'])
        self.assertFalse(r['summary']['comparison_valid'])
        self.assertTrue(any(x['id']=='B1' and x['terminal_error_kwh']>0 for x in r['strategies']))
        with tempfile.TemporaryDirectory() as t:save_evidence(r,t)
    def test_cancel_raises(self):
        from backend.engine import Cancelled
        with self.assertRaises(Cancelled):run_experiment(RunConfig(),'cancelled',cancelled=lambda:True)

if __name__=='__main__':unittest.main()
