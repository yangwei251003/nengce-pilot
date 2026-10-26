"""Independent V3 physical, accounting, information-boundary regression checks."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pydantic import ValidationError

from backend.v3.billing import local_index, monthly_bills, price_vector
from backend.v3.config import Battery, RunConfig, Tariff
from backend.v3.core import Cancelled, recommend_strategy, run_experiment
from backend.v3.forecast import aggregate_development, evaluate_external, feature_matrix
from backend.v3.planner import execute_step, solve_plan, solve_risk_plan, terminal_action


class IntervalPhysicsTests(unittest.TestCase):
    def setUp(self):
        self.b = Battery(capacity_kwh=100,power_kw=40,charge_efficiency=1,discharge_efficiency=1,degradation_per_kwh=0)

    def test_quarter_hour_energy_and_both_balances(self):
        row = execute_step(30,10,20,0,50,self.b,.25)
        self.assertEqual(row['soc_kwh'],55)
        self.assertEqual(row['grid_kw'],40)
        self.assertEqual(row['balance_error_kwh'],0)
        self.assertEqual(row['ac_balance_error_kwh'],0)

    def test_pv_surplus_curtailment_and_storage_absorption(self):
        idle = execute_step(10,50,0,0,50,self.b,.25)
        store = execute_step(10,50,20,0,50,self.b,.25)
        self.assertEqual(idle['curtailment_kw'],40)
        self.assertEqual(store['curtailment_kw'],20)
        self.assertEqual(store['grid_kw'],0)

    def test_no_export_clipping_is_kwh_not_kw(self):
        row = execute_step(10,6,0,20,50,self.b,.25)
        self.assertEqual(row['discharge_kw'],4)
        self.assertEqual(row['clip_no_export_kwh'],4)
        self.assertEqual(row['clip_discharge_kwh'],4)
        self.assertEqual(row['soc_kwh'],49)

    def test_simultaneous_charge_discharge_rejected(self):
        with self.assertRaises(ValueError):
            execute_step(10,0,1,1,50,self.b,.25)

    def test_nonunity_efficiency_conserves_energy(self):
        b = Battery(charge_efficiency=.8,discharge_efficiency=.9)
        charged = execute_step(20,0,40,0,50,b,.25)
        discharged = execute_step(40,0,0,36,charged['soc_kwh'],b,.25)
        self.assertAlmostEqual(charged['soc_kwh'],58)
        self.assertAlmostEqual(discharged['soc_kwh'],48)

    def test_last_interval_repair_cannot_invent_export(self):
        c,d = terminal_action(1,0,60,50,self.b,.25)
        row = execute_step(1,0,c,d,60,self.b,.25)
        self.assertEqual(d,1)
        self.assertGreater(row['soc_kwh'],50)

    def test_two_interval_hand_optimized_pv_fixture(self):
        plan = solve_plan([10,10],[50,0],[.3,1],self.b,.25)
        self.assertTrue(plan['feasible'])
        # 2.5 kWh of free PV stored and consumed, same end SOC, zero grid cost.
        self.assertAlmostEqual(plan['forecast_plan_cost'],0,places=6)
        self.assertAlmostEqual(plan['soc_kwh'][-1],50,places=6)
        self.assertLess(plan['independent_max_residual'],1e-6)
        self.assertTrue(np.all(plan['charge_kw']*plan['discharge_kw']<1e-6))

    def test_demand_is_increment_over_realized_peak(self):
        plan = solve_plan([20,20],[0,0],[0,0],self.b,.25,peak_so_far=30,demand_rate=10)
        self.assertTrue(plan['feasible'])
        self.assertAlmostEqual(plan['forecast_demand_increment'],0,places=6)
        self.assertAlmostEqual(plan['forecast_plan_cost'],0,places=6)

    def test_r2_releases_only_minimum_terminal_required_margin(self):
        plan = solve_risk_plan([10],[0],[1],self.b,[5],mode='R2',dt=1,initial_kwh=60,target_kwh=50)
        self.assertTrue(plan['feasible'])
        self.assertTrue(plan['margin_plan_failed'])
        self.assertEqual(plan['fallback_kind'],'minimum_terminal_margin_release')
        self.assertAlmostEqual(plan['minimum_margin_relaxation_kwh'],5,places=6)
        self.assertAlmostEqual(plan['margin_relaxation_kw'][0],5,places=5)
        self.assertAlmostEqual(plan['soc_kwh'][0],50,places=6)

    def test_r2_never_relaxes_physical_infeasibility(self):
        plan = solve_risk_plan([1],[0],[1],self.b,[.5],mode='R2',dt=.25,initial_kwh=60,target_kwh=50)
        self.assertFalse(plan['feasible'])

    def test_r1_explicit_fallback_keeps_margin_failure(self):
        plan = solve_risk_plan([10],[0],[1],self.b,[5],mode='R1',initial_kwh=60,target_kwh=50)
        self.assertTrue(plan['feasible'])
        self.assertTrue(plan['margin_plan_failed'])
        self.assertTrue(plan['fallback_used'])


class MonthlyBillTests(unittest.TestCase):
    def rows(self,index,dt=.25):
        return [{'grid_kw':20.,'energy_cost':20*dt*.5,'degradation_cost':0.} for _ in index]

    def test_complete_month_charged_once(self):
        index = pd.date_range('2020-02-01','2020-03-01',freq='15min',inclusive='left')
        bill = monthly_bills(index,self.rows(index),.25,30)[0]
        self.assertTrue(bill['complete_observed_month'])
        self.assertEqual(bill['demand_cost'],600)
        self.assertEqual(bill['energy_cost'],29*24*10)
        self.assertEqual(bill['total_cost'],7560)

    def test_partial_month_and_imputed_month_not_billed(self):
        index = pd.date_range('2020-02-01','2020-03-01',freq='15min',inclusive='left')
        partial = monthly_bills(index[:-1],self.rows(index[:-1]),.25,30)[0]
        observed = np.ones(len(index),bool); observed[200]=False
        imputed = monthly_bills(index,self.rows(index),.25,30,observed)[0]
        self.assertIsNone(partial['total_cost'])
        self.assertIsNone(imputed['demand_cost'])

    def test_hourly_month_never_certifies_fifteen_minute_demand(self):
        index = pd.date_range('2020-02-01','2020-03-01',freq='h',inclusive='left')
        bill = monthly_bills(index,self.rows(index,1),1,30)[0]
        self.assertEqual(bill['demand_status'],'ineligible_hourly_resolution')
        self.assertIsNone(bill['total_cost'])

    def test_disabled_demand_contract_partial_energy_is_valid(self):
        index = pd.date_range('2020-02-01',periods=24,freq='h')
        bill = monthly_bills(index,self.rows(index,1),1,0)[0]
        self.assertEqual(bill['demand_cost'],0)
        self.assertEqual(bill['total_cost'],240)

    def test_dst_calendar_counts_actual_intervals(self):
        index = pd.date_range('2020-03-01','2020-04-01',freq='15min',inclusive='left',tz='Europe/Berlin')
        bill = monthly_bills(index,self.rows(index),.25,30)[0]
        self.assertEqual(len(index),31*96-4)
        self.assertTrue(bill['complete_observed_month'])
        self.assertEqual(bill['demand_cost'],600)

    def test_utc_storage_converts_to_source_tariff_calendar(self):
        idx = pd.date_range('2020-01-01',periods=2,freq='h')
        local = local_index(idx,{'time_axis':'UTC','timezone':'Asia/Shanghai'})
        self.assertEqual(local[0].hour,8)

    def test_quarter_hour_price_mapping(self):
        tariff=Tariff(prices=[i/100 for i in range(96)])
        index=pd.date_range('2020-01-01 01:00',periods=4,freq='15min')
        np.testing.assert_allclose(price_vector(index,tariff),[.04,.05,.06,.07])

    def test_invalid_tariff_and_nonmonotone_tariff(self):
        with self.assertRaises(ValidationError):
            Tariff(prices=[.5]*23)
        with self.assertRaises(ValidationError):
            Tariff(prices=[float('nan')]*24)
        # A non-monotonic schedule is a valid declared contract, not a model error.
        self.assertEqual(Tariff(offpeak=1,flat=.1,peak=.5).flat,.1)
        with self.assertRaises(ValidationError):
            Tariff(currency='USD')

    def test_source_boundary_can_veto_an_apparently_complete_month(self):
        index=pd.date_range('2018-12-01','2019-01-01',freq='15min',inclusive='left')
        bill=monthly_bills(index,self.rows(index),.25,30,source_eligible=False)[0]
        self.assertTrue(bill['complete_observed_month'])
        self.assertEqual(bill['demand_status'],'ineligible_source_boundary')
        self.assertIsNone(bill['total_cost'])

    def test_hourly_with_96_prices_is_rejected_before_training(self):
        frame=pd.DataFrame({'load_kw':[1.,1.],'pv_kw':[0.,0.]},index=pd.date_range('2020-01-01',periods=2,freq='h'))
        config=RunConfig(tariff={'prices':[.5]*96})
        with patch('backend.v3.data.load_dataset',return_value=(frame,{'scope':{'dispatch':True}})),patch('backend.v3.core.train_forecasts') as forecast:
            with self.assertRaisesRegex(ValueError,'小时来源不能冒充15分钟'):
                run_experiment(config,'invalid-prices')
            forecast.assert_not_called()

    def test_unknown_source_timezone_can_have_illustrative_month(self):
        index=pd.date_range('2018-12-01','2019-01-01',freq='15min',inclusive='left')
        bill=monthly_bills(index,self.rows(index),.25,30,time_basis='source-local-unknown')[0]
        self.assertEqual(bill['demand_status'],'illustrative_complete_15min_month')
        self.assertFalse(bill['actual_contract_verified'])


class CausalForecastTests(unittest.TestCase):
    def test_validity_recommendation_never_picks_test_cost_winner(self):
        rows=[{'id':'B2','comparison_valid':False,'total_cost':1},
              {'id':'B1','comparison_valid':True,'total_cost':1000},
              {'id':'B0','comparison_valid':True,'total_cost':2}]
        self.assertEqual(recommend_strategy(rows)[0],'B1')
        rows[1]['comparison_valid']=False
        self.assertEqual(recommend_strategy(rows)[0],'B0')
        rows[2]['comparison_valid']=False
        self.assertIsNone(recommend_strategy(rows)[0])
        self.assertEqual(RunConfig().dataset_id,'uci-steel-15min')
    def test_aggregated_development_choice_does_not_use_external_scores(self):
        models=[{'name':name,'mae_kw':mae,'n':100} for name,mae in [('HistGradientBoosting',9),('Daily naive',10),('Weekly naive',12)]]
        report={'validation':models,'rolling_validation':[{'models':models} for _ in range(3)],'hgb_available':True,
                'development_calibration_by_model':[{'absolute_q90_fraction':.2,'positive_q75_fraction':.1} for _ in range(3)]}
        policy=aggregate_development([report,report])
        self.assertEqual(policy['selected_index'],0)
        self.assertAlmostEqual(policy['selection_policy']['observed_mae_improvement_pct'],10)
        self.assertEqual(policy['external_train_end'],'2016-12-31')

    def test_external_training_is_strictly_2016(self):
        index=pd.date_range('2016-01-01','2018-01-01',freq='h',inclusive='left')
        frame=pd.DataFrame({'load_kw':10.,'pv_kw':0.,'observed':True},index=index)
        frame.loc['2017','load_kw']=99.
        fitted=[]
        class Model:
            def fit(self,X,y):
                fitted.append((X.index.max(),y.max()))
                return self
            def predict(self,X):
                return np.full(len(X),10.)
        policy={'selected_index':2,'selected_model':'Weekly naive','absolute_q90_fraction':.2}
        with patch('backend.v3.forecast.HistGradientBoostingRegressor',return_value=Model()):
            out,report=evaluate_external(frame,policy,{'dataset_id':'synthetic-external'})
        self.assertEqual(fitted[0][0].year,2016)
        self.assertEqual(fitted[0][1],10.)
        self.assertEqual(len(out),92*24)
        self.assertEqual(report['selected_model'],'Weekly naive')
    def test_target_day_values_never_enter_its_daily_origin_features(self):
        index=pd.date_range('2020-01-01',periods=100*96,freq='15min')
        frame=pd.DataFrame({'load_kw':20+np.sin(np.arange(len(index))/96),'pv_kw':3.},index=index)
        changed=frame.copy(); changed.loc['2020-03-01','load_kw']=9999
        np.testing.assert_allclose(feature_matrix(frame,'load_kw',.25).loc['2020-03-01'],feature_matrix(changed,'load_kw',.25).loc['2020-03-01'])

    def test_dst_fall_back_day_lag_never_reaches_origin(self):
        index=pd.date_range('2020-09-01','2020-11-01',freq='h',inclusive='left',tz='Europe/Berlin')
        frame=pd.DataFrame({'load_kw':np.arange(len(index),dtype=float),'pv_kw':0.},index=index)
        changed=frame.copy(); changed.loc['2020-10-25','load_kw']=999999
        before=feature_matrix(frame,'load_kw',1).loc['2020-10-25']
        after=feature_matrix(changed,'load_kw',1).loc['2020-10-25']
        self.assertEqual(len(before),25)
        np.testing.assert_allclose(before,after)

    def test_cancellation_before_data_access(self):
        with self.assertRaises(Cancelled):
            run_experiment(RunConfig(),'cancelled',cancelled=lambda:True)

    def test_core_synthetic_run_preserves_soc_across_days(self):
        # Patch forecasting, not physics: a bad forecast causes no-export clips.
        index=pd.date_range('2020-04-01',periods=48,freq='h')
        frame=pd.DataFrame({'load_kw':2.,'pv_kw':0.,'observed':True},index=index)
        out=frame.copy()
        for field in ('forecast_kw','hgb_kw','daily_naive_kw','weekly_naive_kw','lower_kw','upper_kw'):
            out[field]=20.
        for field in ('pv_forecast_kw','pv_hgb_kw','pv_weekly_naive_kw','pv_lower_kw','pv_upper_kw'):
            out[field]=0.
        report={'selected_model':'HistGradientBoosting','hgb_available':True,'improvement_vs_weekly_pct':0,
                'new_independent_generalization_evidence':False,'selection_reason':'synthetic test',
                'risk_calibration':{'positive_overprediction_q75_kw':4.},
                'pv':{'selected_model':'No PV','hgb_available':True}}
        config=RunConfig(evaluation={'start':'2020-04-01','end':'2020-04-02'})
        with patch('backend.v3.data.load_dataset',return_value=(frame,{'dataset_id':'synthetic','scope':{'dispatch':True}})), patch('backend.v3.core.train_forecasts',return_value=(out,report)):
            result=run_experiment(config,'synthetic')
        self.assertEqual(result['summary']['intervals'],48)
        self.assertEqual(len(result['strategies']),8)
        self.assertEqual(result['schema_version'],'3.0.0')
        for key in ('B1','B2','R1','R2'):
            previous=result['series'][23]['strategies'][key]['soc_kwh']
            current=result['series'][24]['strategies'][key]
            expected=previous+config.battery.charge_efficiency*current['charge_kw']-current['discharge_kw']/config.battery.discharge_efficiency
            self.assertAlmostEqual(current['soc_kwh'],expected,places=6)


if __name__ == '__main__':
    unittest.main()
