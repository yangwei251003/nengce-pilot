import unittest,time,uuid
from fastapi.testclient import TestClient
from backend.app import app

class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.client=TestClient(app)
    def test_health_and_dataset(self):
        self.assertEqual(self.client.get('/api/health').status_code,200)
        r=self.client.get('/api/datasets').json()['datasets'][0];self.assertTrue(r['quality']['passed'])
    def test_invalid_config(self):
        r=self.client.post('/api/runs',json={'battery':{'capacity_kwh':-1}});self.assertEqual(r.status_code,422)
    def test_missing_run(self):self.assertEqual(self.client.get('/api/runs/not-real').status_code,404)
    def test_import_error(self):
        r=self.client.post('/api/datasets/import',json={'csv_text':'bad,csv\n1,2','authorized':True})
        self.assertFalse(r.json()['valid'])
    def test_real_run_idempotence_conflict_and_exports(self):
        c=self.client.get('/api/defaults').json();c['evaluation']['end']='2018-12-01';c['idempotency_key']='test-'+uuid.uuid4().hex
        a=self.client.post('/api/runs',json=c);self.assertEqual(a.status_code,202);rid=a.json()['run_id']
        self.assertEqual(self.client.post('/api/runs',json=c).json()['run_id'],rid)
        c['battery']['power_kw']=30;self.assertEqual(self.client.post('/api/runs',json=c).status_code,409)
        for _ in range(100):
            r=self.client.get('/api/runs/'+rid).json()
            if r['status'] in ('succeeded','failed','cancelled'):break
            time.sleep(.05)
        self.assertEqual(r['status'],'succeeded',r.get('message'));self.assertEqual(r['result']['summary']['hours'],24)
        for ext in ['json','csv','html']:
            x=self.client.get(f'/api/runs/{rid}/export/{ext}');self.assertEqual(x.status_code,200);self.assertGreater(len(x.content),100)
    def test_cancel_reaches_terminal_state(self):
        c=self.client.get('/api/defaults').json();rid=self.client.post('/api/runs',json=c).json()['run_id']
        self.client.post(f'/api/runs/{rid}/cancel')
        for _ in range(100):
            r=self.client.get('/api/runs/'+rid).json()
            if r['status'] in ('succeeded','failed','cancelled'):break
            time.sleep(.05)
        self.assertEqual(r['status'],'cancelled')

if __name__=='__main__':unittest.main()
