import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from backend import data

class ImportIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(data,'UPLOADS',Path(self.temp.name));self.patch.start()
        self.frame=pd.DataFrame({'timestamp':pd.date_range('2025-01-01',periods=2160,freq='h'),'load_kw':42.})
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def submit(self,frame=None,name='授权样本',tz='Asia/Shanghai'):
        return data.import_csv((frame if frame is not None else self.frame).to_csv(index=False),name,tz,'kW',True)
    def test_raw_bytes_and_reimport_are_immutable(self):
        r=self.submit();self.assertTrue(r['valid']); ident=r['dataset']['dataset_id']
        first=(data.UPLOADS/ident/'metadata.json').read_bytes()
        self.assertEqual(self.submit()['dataset']['dataset_id'],ident)
        self.assertEqual((data.UPLOADS/ident/'metadata.json').read_bytes(),first)
        f,m=data.load_dataset(ident);self.assertEqual(len(f),2160)
        self.assertEqual(m['provenance']['raw_sha256'],data.sha256(data.UPLOADS/ident/'raw.csv'))
    def test_changed_timezone_creates_distinct_audit(self):
        self.assertNotEqual(self.submit(tz='UTC')['dataset']['dataset_id'],self.submit()['dataset']['dataset_id'])
    def test_tampered_csv_rejected(self):
        ident=self.submit()['dataset']['dataset_id'];(data.UPLOADS/ident/'hourly.csv').write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'SHA256'):data.load_dataset(ident)
    def test_partial_hour_rejected_with_row(self):
        self.frame['timestamp']+=pd.Timedelta(minutes=30)
        r=self.submit();self.assertFalse(r['valid']);self.assertEqual(r['errors'][0]['row'],2)
    def test_offset_timestamps_rejected_explicitly(self):
        self.frame['timestamp']=self.frame['timestamp'].dt.tz_localize('UTC')
        r=self.submit();self.assertFalse(r['valid']);self.assertEqual(r['errors'][0]['field'],'timestamp')
    def test_duplicate_gap_and_nonfinite(self):
        for value in [-1,float('inf'),float('nan')]:
            f=self.frame.copy();f.loc[30,'load_kw']=value
            r=self.submit(f);self.assertFalse(r['valid']);self.assertTrue(any(x['row']==32 for x in r['errors']))
        f=self.frame.copy();f.loc[30,'timestamp']=f.loc[29,'timestamp'];self.assertFalse(self.submit(f)['valid'])

if __name__=='__main__':unittest.main()
