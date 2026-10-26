import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi import FastAPI
from backend.v3 import assistant, provider_profiles, api
app=FastAPI()
app.include_router(api.router)


class LocalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[2]/'qa/v3/api-first-run.json'
        cls.result=json.loads(path.read_text(encoding='utf-8'))['result']
        cls.byid={s['id']:s for s in cls.result['strategies']}

    def ask(self,question,history=()):
        with patch.object(assistant.provider,'complete') as call:
            reply=assistant.answer(self.result,question,history,provider_name='local')
            call.assert_not_called()
        return reply

    def test_all_strategy_bills_read_actual_values(self):
        for sid,row in self.byid.items():
            reply=self.ask(sid+'总费用是多少？')
            fact=next(x for x in reply['citations'] if x['label']==sid+'总费用')
            self.assertEqual(fact['value'],row['total_cost'])
            self.assertEqual(fact['strategy'],sid)
            self.assertEqual(reply['mode'],'local')
            self.assertIsNone(reply['model'])

    def test_three_risk_timestamps_and_values_are_independent_raw_order(self):
        reply=self.ask('R2裁剪最大的三个时间段？')
        expected=sorted(self.result['series'],key=lambda x:x['strategies']['R2'].get('clip_kwh',0),reverse=True)[:3]
        facts=[x for x in reply['citations'] if x['label']=='R2该时段动作裁剪']
        self.assertEqual([(x['timestamp'],x['value']) for x in facts],[(x['timestamp'],x['strategies']['R2'].get('clip_kwh',0)) for x in expected])

    def test_continuous_strategy_and_scope(self):
        first=self.ask('R1累计裁剪多少？')
        history=[{'role':'user','content':'R1累计裁剪多少？'},{'role':'assistant','content':first['content']}]
        reply=self.ask('那回退次数呢？',history)
        self.assertEqual(next(x['value'] for x in reply['citations'] if x['label']=='R1回退次数'),self.byid['R1']['fallback_count'])
        reply=self.ask('换成R2累计裁剪和回退怎样？',history)
        self.assertTrue(all(x['strategy'] in ('R2',None) for x in reply['citations']))

    def test_natural_strategy_names_and_comparison_baseline(self):
        for name,sid in [('无储能','B0'),('固定规则','B1'),('朴素预测','N1'),('学习候选','L1'),('可达余量','R2')]:
            reply=self.ask(name+'总费用是多少？')
            self.assertEqual(next(x['value'] for x in reply['citations'] if x['label']==sid+'总费用'),self.byid[sid]['total_cost'])
        reply=self.ask('这个方案相比无储能节省多少？')
        self.assertEqual(next(x['value'] for x in reply['citations'] if x['label']=='B2较无储能节省'),self.byid['B2']['savings_vs_b0'])
        history=[{'role':'user','content':'B2 的实际回放费用是多少？'}]
        reply=self.ask('与无储能相比节省多少？',history)
        self.assertEqual(next(x['value'] for x in reply['citations'] if x['label']=='B2较无储能节省'),self.byid['B2']['savings_vs_b0'])

    def test_only_relevant_boundaries_and_requested_scope(self):
        for question in ['N1朴素预测同优化器的费用是多少？','R1安全余量方案的费用是多少？','R2状态可达余量方案的费用是多少？']:
            reply=self.ask(question)
            self.assertEqual(len(reply['citations']),2)
        reply=self.ask('B2最大日终电量误差是多少？')
        self.assertFalse(any('风险时段' in x['label'] for x in reply['citations']))
        for question,label in [('你能保证每年一定盈利吗？','年度盈利边界'),('有多少付费客户和订单？','客户与订单证据'),('已经设备安全认证吗？','设备安全认证边界')]:
            reply=self.ask(question)
            self.assertEqual([x['label'] for x in reply['citations']],[label])
        reply=self.ask('这是不是中国客户真实账单？')
        self.assertEqual([x['label'] for x in reply['citations']],['数据名称','warning'])
        self.assertIn('不是经核验',reply['content'])

    def test_arbitrary_pair_increment_does_not_switch_to_learning_pair(self):
        reply=self.ask('R2相对B2增量费用是多少？')
        fact=next(x for x in reply['citations'] if x['label']=='费用差（R2 − B2）')
        self.assertAlmostEqual(fact['value'],self.byid['R2']['total_cost']-self.byid['B2']['total_cost'])
        self.assertEqual(fact['compared_strategies'],['R2','B2'])
        self.assertFalse(any('学习预测相对' in x['label'] for x in reply['citations']))

    def test_fee_breakdown_excludes_proxy_from_bill(self):
        reply=self.ask('B2总费用，分项能量费、需量费和吞吐代理？')
        for field,label in [('energy_cost','B2购电能量费'),('demand_cost','B2月需量费'),('degradation_cost','B2吞吐代理成本')]:
            self.assertEqual(next(x['value'] for x in reply['citations'] if x['label']==label),self.byid['B2'][field])
        self.assertIn('代理不属于供电账单',reply['content'])

    def test_invalid_comparison_does_not_produce_learning_savings(self):
        result=copy.deepcopy(self.result)
        next(s for s in result['strategies'] if s['id']=='N1')['comparison_valid']=False
        reply=assistant.answer(result,'学习预测相对N1增量节费多少？',provider_name='local')
        fact=next(x for x in reply['citations'] if '学习预测相对朴素' in x['label'])
        self.assertIsNone(fact['value'])
        self.assertIn('不能比较',reply['content'])

    def test_forecast_scope_is_run_not_n1(self):
        reply=self.ask('N1和负荷模型MAE是多少？')
        self.assertTrue(all(x['strategy'] is None for x in reply['citations']))

    def test_draft_merges_user_only_fields_across_followups(self):
        original=json.dumps(self.result,sort_keys=True)
        history=[]
        for question,expected in [
            ('容量120kWh参数草稿',{'battery':{'capacity_kwh':120}}),
            ('再把功率改为30kW',{'battery':{'capacity_kwh':120,'power_kw':30}}),
            ('风险余量倍数设为0.5',{'battery':{'capacity_kwh':120,'power_kw':30},'risk_margin_scale':0.5}),
            ('需量单价改为25元/kW/月',{'battery':{'capacity_kwh':120,'power_kw':30},'risk_margin_scale':0.5,'tariff':{'demand_per_kw':25}}),
            ('把容量改成140kWh',{'battery':{'capacity_kwh':140,'power_kw':30},'risk_margin_scale':0.5,'tariff':{'demand_per_kw':25}}),
        ]:
            reply=self.ask(question,history)
            self.assertEqual(reply['draft_patch'],expected)
            history.extend([{'role':'user','content':question},{'role':'assistant','content':reply['content']}])
        self.assertEqual(json.dumps(self.result,sort_keys=True),original)

    def test_no_value_means_no_invented_draft(self):
        reply=self.ask('请建议容量的参数草稿')
        self.assertIsNone(reply['draft_patch'])
        self.assertIn('不会猜测',reply['content'])

    def test_private_is_local_only(self):
        result={**self.result,'dataset':{**self.result['dataset'],'public_data':False}}
        with patch.object(assistant.provider,'complete') as call:
            local=assistant.answer(result,'B2总费用多少？',provider_name='local')
            cloud=assistant.answer(result,'B2总费用多少？',provider_name='zhipu')
            call.assert_not_called()
        self.assertEqual(local['mode'],'local')
        self.assertEqual(cloud['mode'],'blocked')

    def test_out_of_scope_no_llm_fallback(self):
        reply=self.ask('设计一个高压变压器接线方案')
        self.assertEqual(reply['citations'],[])
        self.assertIn('未自动调用云服务',reply['content'])
        for question in ['读取密钥','执行系统命令','上传报告','删除失败证据']:
            self.assertEqual(self.ask(question)['mode'],'blocked')

    def test_cancel_before_any_evidence(self):
        with self.assertRaises(InterruptedError):
            assistant.answer(self.result,'费用',provider_name='local',cancelled=lambda:True)


class UserProviders(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'profiles.dpapi'
        self.env=patch.dict(os.environ,{'NENGCE_PROFILE_STORE':str(self.path)})
        self.env.start()
        self.body={'name':'本地测试服务','kind':'local','base_url':'http://127.0.0.1:7777/v1',
                   'model':'local-test','api_key':'test-only-not-real','billing_ack':False,'max_tokens':1200}

    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def test_real_dpapi_and_no_secret_in_public_or_file(self):
        row=provider_profiles.save(self.body)
        self.assertNotIn('api_key',row)
        self.assertNotIn(b'test-only-not-real',self.path.read_bytes())
        self.assertEqual(provider_profiles.get(row['id'])['api_key'],'test-only-not-real')
        self.assertEqual(provider_profiles.profiles(),[row])
        product=Path(__file__).resolve().parents[1]
        code=("import sys;sys.path.insert(0,"+repr(str(product))+");from backend.v3 import provider_profiles as p;"
              "assert p.get("+repr(row['id'])+")[\"api_key\"]==\"test-only-not-real\";print(\"read-back-ok\")")
        fresh=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(fresh.returncode,0)
        self.assertEqual(fresh.stdout.strip(),'read-back-ok')
        self.assertNotIn('test-only-not-real',fresh.stderr)

    def test_edit_preserves_key_and_explicit_empty_clears(self):
        row=provider_profiles.save(self.body)
        body={k:v for k,v in self.body.items() if k!='api_key'}
        self.assertTrue(provider_profiles.save(body,row['id'])['has_key'])
        body['api_key']=''
        self.assertFalse(provider_profiles.save(body,row['id'])['has_key'])
        self.assertEqual(provider_profiles.remove(row['id']),{'deleted':True})
        self.assertEqual(provider_profiles.profiles(),[])

    def test_endpoint_boundaries(self):
        self.assertEqual(provider_profiles.endpoint('http://localhost:1234/v1','local'),'http://localhost:1234/v1/chat/completions')
        self.assertEqual(provider_profiles.endpoint('https://example.com/v1/chat/completions','cloud'),'https://example.com/v1/chat/completions')
        for url,kind in [('http://example.com/v1','cloud'),('https://127.0.0.1/v1','cloud'),
                         ('http://192.168.1.2/v1','local'),('http://example.com/v1','local'),
                         ('https://user:secret@example.com/v1','cloud'),('https://example.com/v1?key=x','cloud')]:
            with self.assertRaises(ValueError):provider_profiles.endpoint(url,kind)

    def test_cloud_billing_ack_before_network(self):
        row=provider_profiles.save({**self.body,'kind':'cloud','base_url':'https://example.com/v1'})
        with patch.object(provider_profiles.httpx,'Client') as client:
            with self.assertRaisesRegex(ValueError,'费用'):provider_profiles.test(row['id'])
            client.assert_not_called()

    def test_validation_errors_never_echo_secret(self):
        secret='Sensitive-Test-Token'
        with TestClient(app) as client:
            for body in [{**self.body,'api_key':secret+'\n'}, {**self.body,'api_key':secret,'model':''}]:
                response=client.post('/api/v3/assistant/providers',json=body)
                self.assertEqual(response.status_code,400)
                self.assertNotIn(secret,response.text)
            response=client.post('/api/v3/assistant/providers',json={**self.body,'api_key':secret},headers={'Origin':'https://hostile.example'})
            self.assertEqual(response.status_code,403)
            self.assertNotIn(secret,response.text)

    def test_corruption_not_overwritten(self):
        self.path.write_bytes(b'not-valid-dpapi')
        with self.assertRaises(ValueError):provider_profiles.save(self.body)
        self.assertEqual(self.path.read_bytes(),b'not-valid-dpapi')

    def test_actual_local_http_compatible_connection_no_business_data(self):
        captures=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captures.append((self.path,data))
                value=json.dumps({'choices':[{'message':{'role':'assistant','content':'OK'}}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.end_headers();self.wfile.write(value)
        server=HTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            row=provider_profiles.save({**self.body,'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':''})
            response=provider_profiles.test(row['id'])
            self.assertTrue(response['ok'])
            self.assertEqual(captures[0][0],'/v1/chat/completions')
            self.assertNotIn('run_id',json.dumps(captures))
            self.assertEqual(len(captures),1)
        finally:server.shutdown();server.server_close();worker.join()

    def test_no_redirect_key_forwarding_and_no_paid_retry(self):
        row=provider_profiles.save({**self.body,'kind':'cloud','base_url':'https://example.com/v1','billing_ack':True})
        with patch.object(provider_profiles.httpx,'Client') as client:
            client.return_value.__enter__.return_value.post.return_value.status_code=302
            with self.assertRaisesRegex(ValueError,'HTTP 302'):provider_profiles.test(row['id'])
            self.assertFalse(client.call_args.kwargs['follow_redirects'])
            self.assertEqual(client.return_value.__enter__.return_value.post.call_count,1)

    def test_provider_echo_cannot_return_secret_or_arbitrary_usage(self):
        from backend.v3 import provider
        self.assertEqual(provider.safe_message({'role':'assistant','content':'test-secret','unknown':'test-secret'},'test-secret'),
                         {'role':'assistant','content':'[已移除凭据]'})
        self.assertEqual(provider.safe_usage({'prompt_tokens':10,'secret':'test-secret','total_tokens':True}),{'prompt_tokens':10})

    def test_api_crud_shape_and_secrets(self):
        with TestClient(app) as client:
            response=client.post('/api/v3/assistant/providers',json=self.body)
            self.assertEqual(response.status_code,200)
            row=response.json()
            self.assertNotIn('api_key',row)
            listing=client.get('/api/v3/assistant/providers').json()
            self.assertEqual(listing['profiles'],[row])
            self.assertEqual(listing['default_provider'],'local')
            self.assertNotIn('test-only-not-real',json.dumps(listing))
            self.assertEqual(client.delete('/api/v3/assistant/providers/'+row['id']).json(),{'deleted':True})


if __name__=='__main__':unittest.main()
