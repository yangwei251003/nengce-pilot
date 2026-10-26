import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from backend.v3 import data


def example(interval=60,timezone=None,days=90,pv=True):
    idx=pd.date_range('2024-01-01',periods=days*24*60//interval,freq=f'{interval}min',tz=timezone)
    f=pd.DataFrame({'timestamp':idx.astype(str),'load_kwh':np.full(len(idx),25*interval/60)})
    if pv:f['pv_kwh']=np.full(len(idx),5*interval/60)
    return f.to_csv(index=False)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=data.DATA)
        self.patch=patch.object(data,'UPLOADS',Path(self.tmp.name));self.patch.start()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def imp(self,text=None,**kwargs):
        args=dict(csv_text=text or example(),name='授权样本',timezone='source-local-unknown',unit='kWh',authorized=True)
        args.update(kwargs);return data.import_csv(**args)
    def test_energy_conversion_15min_and_private_default(self):
        r=self.imp(example(15),interval_minutes=15)
        self.assertTrue(r['valid'],r)
        f,m=data.load_dataset(r['dataset']['dataset_id'])
        self.assertTrue((f.load_kw==25).all());self.assertTrue((f.pv_kw==5).all())
        self.assertFalse(m['public_data']);self.assertEqual(m['privacy'],'private')
        self.assertTrue(m['demand_eligible']);self.assertIn('2024-01',m['quality']['demand_complete_months'])
        self.assertEqual(float(f.load_kw.sum()*.25),25*24*90)
    def test_same_bytes_different_unit_metadata_different_identity(self):
        a=self.imp();b=self.imp(timezone='UTC');c=self.imp(name='另一个名称')
        self.assertEqual(len({x['dataset']['dataset_id'] for x in (a,b,c)}),3)
    def test_repeated_import_is_immutable_and_raw_hash_checked(self):
        r=self.imp();ident=r['dataset']['dataset_id'];p=data.UPLOADS/ident/'raw.csv'
        before=p.stat().st_mtime_ns;r2=self.imp()
        self.assertTrue(r2['reused']);self.assertEqual(before,p.stat().st_mtime_ns)
        p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'SHA256'):data.load_dataset(ident)
    def test_derived_file_tamper_rejected(self):
        r=self.imp();p=data.UPLOADS/r['dataset']['dataset_id']/'series.csv'
        p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'SHA256'):data.load_dataset(r['dataset']['dataset_id'])
    def test_negative_nonfinite_original_rows_bounded(self):
        frame=pd.read_csv(__import__('io').StringIO(example()))
        frame.loc[:149,'load_kwh']=-2;frame.loc[150,'load_kwh']=np.inf
        r=self.imp(frame.to_csv(index=False))
        self.assertFalse(r['valid']);self.assertEqual(r['error_count'],151)
        self.assertEqual(len(r['errors']),100);self.assertTrue(r['errors_truncated'])
        self.assertEqual(r['errors'][0]['row'],2)
    def test_real_utf8_byte_limit(self):
        r=self.imp('数'*(data.MAX_BYTES//3+1))
        self.assertFalse(r['valid']);self.assertEqual(r['errors'][0]['field'],'size')
    def test_row_count_limit_before_processing(self):
        r=self.imp('timestamp,load_kwh\n'+('2024-01-01 00:00,1\n'*(data.MAX_ROWS+1)))
        self.assertFalse(r['valid']);self.assertEqual(r['errors'][0]['field'],'length')
    def test_duplicate_out_of_order_and_wrong_grid_rejected(self):
        frame=pd.read_csv(__import__('io').StringIO(example()))
        frame.loc[1,'timestamp']=frame.loc[0,'timestamp']
        r=self.imp(frame.to_csv(index=False));self.assertFalse(r['valid'])
        self.assertTrue(any(e['row']==3 for e in r['errors']))
        frame.loc[1,'timestamp']='2024-01-01 01:30:00'
        self.assertFalse(self.imp(frame.to_csv(index=False))['valid'])
    def test_half_hour_offset_timezone_hour_grid_allowed(self):
        r=self.imp(timezone='Asia/Kolkata');self.assertTrue(r['valid'],r)
        f,m=data.load_dataset(r['dataset']['dataset_id'])
        self.assertEqual(f.index[0],pd.Timestamp('2023-12-31 18:30:00'))
        self.assertEqual(m['start'],'2024-01-01 00:00:00+05:30')
    def test_explicit_dst_offsets_and_invalid_zone(self):
        r=self.imp(example(timezone='Europe/Berlin'),timezone='Europe/Berlin')
        self.assertTrue(r['valid'],r)
        self.assertFalse(self.imp(timezone='not/a/zone')['valid'])
        self.assertFalse(self.imp(authorized=False)['valid'])
    def test_header_collision_pv_mismatch_and_traversal(self):
        self.assertFalse(self.imp('timestamp,load_kwh,load_kwh\n2024-01-01,1,1')['valid'])
        self.assertFalse(self.imp(pv_column='load_kwh')['valid'])
        with self.assertRaises(ValueError):data.load_dataset('../raw')


class QualityTests(unittest.TestCase):
    def test_dst_23_hour_day_complete_month(self):
        idx=pd.date_range('2024-03-01','2024-04-01',freq='15min',inclusive='left',tz='Europe/Berlin').tz_convert('UTC').tz_localize(None)
        f=pd.DataFrame({'load_kw':10.,'pv_kw':0.,'observed':True},index=idx)
        m={'interval_minutes':15,'time_axis':'UTC','billing_timezone':'Europe/Berlin','scope':{'dispatch':True}}
        q=data.quality_report(f,m)
        self.assertEqual(q['monthly_coverage'][0]['expected'],31*96-4)
        self.assertEqual(q['demand_complete_months'],['2024-03'])
        f.iloc[30,f.columns.get_loc('observed')]=False
        self.assertEqual(data.quality_report(f,m)['demand_complete_months'],[])
    def test_hourly_or_partial_boundary_never_certifies_demand(self):
        idx=pd.date_range('2024-01-01','2024-02-01',freq='h',inclusive='left')
        f=pd.DataFrame({'load_kw':10.,'pv_kw':0.,'observed':True},index=idx)
        m={'interval_minutes':60,'time_axis':'source-local','scope':{'dispatch':True}}
        self.assertEqual(data.quality_report(f,m)['complete_months'],['2024-01'])
        self.assertEqual(data.quality_report(f,m)['demand_complete_months'],[])


class PublicSourceTests(unittest.TestCase):
    def test_frozen_selection_has_site_disjoint_12_and_12(self):
        selection=json.loads((data.ROOT/'qa/v3/data-bdg2-selection.json').read_text(encoding='utf-8'))
        groups={r:{s['site_id'] for s in selection['selected'] if s['role']==r} for r in ('development','external')}
        self.assertEqual(len(selection['selected']),24);self.assertEqual(len(groups['development']),3)
        self.assertEqual(len(groups['external']),3);self.assertFalse(groups['development']&groups['external'])
        self.assertFalse(selection['model_evaluation_performed'])
        freeze=json.loads((data.DATA/'protocol-freeze.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(data.sha256(data.ROOT/freeze['protocol_path']),freeze['protocol_sha256'])
    def test_uci_native_energy_conserved_and_rsf_source_sign(self):
        q,m=data.load_dataset('uci-steel-15min');h,_=data.load_dataset('uci-steel-hourly')
        self.assertAlmostEqual(q.load_kw.sum()*.25,h.load_kw.sum(),places=6)
        self.assertEqual(len(m['quality']['demand_complete_months']),12)
        rsf,meta=data.load_dataset('rsf-hourly')
        self.assertFalse(meta['demand_eligible']);self.assertTrue(meta['partial_meter_boundary'])
        signed=rsf.source_signed_pv_kw
        self.assertTrue(np.allclose(rsf.pv_kw,(-signed).clip(lower=0),equal_nan=True))
        self.assertGreater(rsf.pv_kw.max(),1000)
        self.assertFalse(meta['original_observation_verified'])
    def test_opsd_channel_only_cumulative_not_direct_load(self):
        f,m=data.load_dataset('opsd-industrial1')
        self.assertFalse(m['scope']['dispatch']);self.assertFalse(m['scope']['energy_billing'])
        self.assertFalse(m['demand_eligible']);self.assertTrue(m['channel_only'])
        expected=f.source_grid_import_register_kwh.diff().shift(-1)*4
        valid=f.load_kw.notna()&expected.notna()
        self.assertTrue(np.allclose(f.loc[valid,'load_kw'],expected[valid]))

if __name__=='__main__':unittest.main()
