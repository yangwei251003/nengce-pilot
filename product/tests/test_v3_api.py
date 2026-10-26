import copy
import json
import tempfile
import subprocess
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import Future

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.v3 import api
from backend.v3.config import RunConfig
from backend.v3.store import Store
from backend.v3.evidence import save_evidence


class HoldWorker:
    def submit(self, *args):
        return Future()


class DurableAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(api,'store',Store(root/'index.sqlite')),
                        patch.object(api,'RUNS',root/'runs'), patch.object(api,'compute_worker',HoldWorker()),
                        patch.object(api,'chat_worker',HoldWorker()), patch.object(api,'futures',{}),
                        patch.object(api,'cancel_flags',set())]
        for p in self.patches:p.start()
        app = FastAPI(); app.include_router(api.router)
        self.client=TestClient(app)
        self.config=RunConfig().model_dump()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def post(self, **updates):
        return self.client.post('/api/v3/runs',json={**self.config,**updates})

    def succeeded(self):
        # Real persisted result schema from an independently executed 15-minute case.
        source=Path(__file__).resolve().parents[2]/'qa/v3/api-first-run.json'
        result=json.loads(source.read_text(encoding='utf-8'))['result']
        run=self.post().json(); result['run_id']=run['id']
        save_evidence(result,api.RUNS/run['id'])
        api.store.patch('run',run['id'],status='succeeded')
        return run['id'],result

    def test_idempotency_same_body(self):
        first=self.post(idempotency_key='repeat').json()
        second=self.post(idempotency_key='repeat').json()
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(api.store.all('run')),1)

    def test_idempotency_conflict(self):
        self.post(idempotency_key='repeat')
        r=self.post(idempotency_key='repeat',stress='load_up_20')
        self.assertEqual(r.status_code,409)

    def test_capacity_and_duplicate_when_full(self):
        first=self.post(idempotency_key='first')
        for _ in range(19):self.assertEqual(self.post().status_code,202)
        self.assertEqual(self.post().status_code,429)
        self.assertEqual(self.post(idempotency_key='first').json()['id'],first.json()['id'])

    def test_cancel_queue_immediate_terminal_and_releases_capacity(self):
        first=self.post().json()['id']
        future=api.futures[first]
        r=self.client.post(f'/api/v3/runs/{first}/cancel')
        self.assertEqual(r.json()['status'],'cancelled')
        self.assertTrue(future.cancelled())
        self.assertNotIn(first,api.futures)
        self.assertNotIn(first,api.cancel_flags)
        self.assertEqual(api.active_count('run'),0)

    def test_restart_marks_interrupted_and_preserves_idempotency(self):
        first=self.post(idempotency_key='restart').json()['id']
        api.store=Store(api.store.path); api.recover()
        self.assertEqual(api.require('run',first)['stage'],'interrupted')
        self.assertEqual(self.post(idempotency_key='restart').json()['id'],first)

    def test_import_does_not_interrupt_tasks_but_service_start_does(self):
        # A separate test/CLI import must never pretend that the real API restarted.
        output=Path(self.temp.name)/'import-isolation'
        database=Store(output/'index.sqlite')
        database.put('run',{'id':'run-abcdef012345','run_id':'run-abcdef012345','status':'queued','created_at':api.now()})
        environment={**os.environ,'NENGCE_V3_OUTPUT':str(output),'NENGCE_RUNS_DIR':str(output/'legacy')}
        subprocess.run([sys.executable,'-c','import backend.app'],env=environment,check=True,capture_output=True)
        self.assertEqual(database.get('run','run-abcdef012345')['status'],'queued')
        code='from backend.app import app; from fastapi.testclient import TestClient\nwith TestClient(app) as client:\n assert client.get("/api/v3/health").status_code == 200'
        subprocess.run([sys.executable,'-c',code],env=environment,check=True,capture_output=True)
        self.assertEqual(database.get('run','run-abcdef012345')['stage'],'interrupted')

    def test_pagination_thousand_unique_stable(self):
        for i in range(1000):
            api.store.put('run',{'id':f'run-{i:012d}','run_id':f'run-{i:012d}','created_at':'2026-01-01','status':'succeeded'})
        all_ids=[];cursor=None
        while True:
            query='/api/v3/runs?limit=100'+(f'&cursor={cursor}' if cursor else '')
            response=self.client.get(query).json(); all_ids.extend(x['id'] for x in response['runs'])
            cursor=response['next_cursor']
            if cursor is None:break
        self.assertEqual(len(all_ids),1000);self.assertEqual(len(set(all_ids)),1000)

    def test_invalid_cursor_and_limit(self):
        self.assertEqual(self.client.get('/api/v3/runs?cursor=missing').status_code,400)
        self.assertEqual(self.client.get('/api/v3/runs?limit=0').status_code,422)

    def test_batch_idempotency_and_independent_configs(self):
        body={'configs':[self.config,{**self.config,'stress':'load_up_20'}],'idempotency_key':'batch'}
        a=self.client.post('/api/v3/batches',json=body).json()
        b=self.client.post('/api/v3/batches',json=body).json()
        self.assertEqual(a['batch_id'],b['batch_id']);self.assertEqual(len(api.store.all('run')),2)
        self.assertNotEqual(a['runs'][0]['config']['stress'],a['runs'][1]['config']['stress'])

    def test_batch_capacity_rejected_atomically(self):
        for _ in range(19):self.post()
        r=self.client.post('/api/v3/batches',json={'configs':[self.config,self.config]})
        self.assertEqual(r.status_code,429);self.assertEqual(len(api.store.all('run')),19)
        self.assertFalse(api.store.all('batch'))

    def test_only_success_can_export(self):
        ident=self.post().json()['id']
        self.assertEqual(self.client.get(f'/api/v3/runs/{ident}/export/json').status_code,409)

    def test_exports_match_same_result_and_cannot_overwrite(self):
        ident,result=self.succeeded()
        exported=self.client.get(f'/api/v3/runs/{ident}/export/json')
        self.assertEqual(exported.json(),result)
        self.assertIn('B2_grid_kw',self.client.get(f'/api/v3/runs/{ident}/export/csv').text)
        self.assertIn(ident,self.client.get(f'/api/v3/runs/{ident}/export/html').text)
        with self.assertRaises(FileExistsError):save_evidence(result,api.RUNS/ident)

    def test_tampered_result_and_report_blocked(self):
        ident,_=self.succeeded(); folder=api.RUNS/ident
        (folder/'report.html').write_text('tamper',encoding='utf-8')
        self.assertEqual(self.client.get(f'/api/v3/runs/{ident}/export/html').status_code,409)
        (folder/'result.json').write_text('{}',encoding='utf-8')
        self.assertEqual(self.client.get(f'/api/v3/runs/{ident}').status_code,409)

    def test_chat_session_bound_and_duplicate_inflight(self):
        ident,_=self.succeeded()
        body={'run_id':ident,'question':'总费用是多少'}
        first=self.client.post('/api/v3/assistant/chat',json=body).json()
        body['session_id']=first['session_id']
        self.assertEqual(self.client.post('/api/v3/assistant/chat',json=body).status_code,409)
        other,_=self.succeeded();body['run_id']=other
        self.assertEqual(self.client.post('/api/v3/assistant/chat',json=body).status_code,409)

    def test_chat_cancel_discards_late_result(self):
        ident,result=self.succeeded()
        r=self.client.post('/api/v3/assistant/chat',json={'run_id':ident,'question':'费用'}).json()
        self.client.post(f'/api/v3/assistant/requests/{r["id"]}/cancel')
        with patch('backend.v3.assistant.answer') as model:
            api.execute_chat(r['id'],result,'费用',api.require('session',r['session_id']))
            model.assert_not_called()
        self.assertEqual(api.require('chat',r['id'])['status'],'cancelled')
        self.assertEqual(api.require('session',r['session_id'])['messages'],[])

    def test_unknown_paths_and_invalid_configuration(self):
        self.assertEqual(self.client.get('/api/v3/runs/missing').status_code,404)
        self.assertEqual(self.post(tariff={'prices':[.2]}).status_code,422)
        self.assertEqual(self.post(battery={'capacity_kwh':-1}).status_code,422)


if __name__=='__main__':unittest.main()
