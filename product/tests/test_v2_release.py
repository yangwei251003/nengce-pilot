"""Release-boundary checks: no model training or scenario computation."""
import contextlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend import cli
from backend.evidence import save_evidence


def rendering_fixture():
    slot={'grid_kw':1.,'charge_kw':0.,'discharge_kw':0.,'soc_kwh':50.,'planned_charge_kw':0.,'planned_discharge_kw':0.,'clip_kwh':0.,'energy_cost':1.,'degradation_cost':0.,'total_cost':1.,'cumulative_cost':1.}
    strategy={'id':'B0','name':'无储能','energy_cost':1.,'degradation_cost':0.,'total_cost':1.,'savings_pct':0.,'comparison_valid':True,'clip_kwh':0.,'terminal_error_kwh':0.,'charge_kwh':0.,'discharge_kwh':0.}
    return {'run_id':'rendering-fixture','generated_at':'2026-10-04T00:00:00Z',
        'summary':{'period_start':'2025-03-20 00:00:00','period_end':'2025-03-20 00:00:00','hours':1,'elapsed_seconds':0.,'comparison_valid':True,'warnings':[],'source_label':'用户声明授权负荷 <来源>'},
        'forecast':{'models':[],'selected_model':'Weekly naive','evaluation_role':'exploratory_subperiod'},
        'config':{'tariff':{'currency':'CNY'}},'strategies':[strategy],
        'series':[{'timestamp':'2025-03-20 00:00:00','actual_kw':1.,'forecast_kw':1.,'hgb_kw':1.,'daily_naive_kw':1.,'weekly_naive_kw':1.,'price':1.,'strategies':{'B0':slot}}],
        'dataset':{'provenance':{'source':'test fixture'}},'solver_audit':[],'assumptions':['导出格式测试夹具，不是运行成绩']}


class ReleaseBoundaryTests(unittest.TestCase):
    def test_cli_default_is_unique_and_never_frozen_default(self):
        paths=[]
        for _ in range(2):
            with patch.object(sys,'argv',['cli','run']),patch.object(cli,'run_experiment',return_value=rendering_fixture()),patch.object(cli,'save_evidence') as save,contextlib.redirect_stdout(io.StringIO()):
                cli.main();paths.append(save.call_args.args[1])
        self.assertNotEqual(paths[0],paths[1]);self.assertEqual(paths[0].parent.name,'cli-v2')
        self.assertNotEqual(paths[0],cli.ROOT/'outputs/v2/default')

    def test_cli_rejects_existing_evidence_before_computing(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'result.json';path.write_bytes(b'preserve')
            with patch.object(sys,'argv',['cli','run','--out',directory]),patch.object(cli,'run_experiment') as run,self.assertRaises(FileExistsError):cli.main()
            run.assert_not_called();self.assertEqual(path.read_bytes(),b'preserve')

    def test_unknown_cli_stress_rejected_before_computing(self):
        with patch.object(sys,'argv',['cli','run','--stress','mistyped-pressure']),patch.object(cli,'run_experiment') as run,contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:cli.main()
        self.assertEqual(error.exception.code,2);run.assert_not_called()

    def test_evidence_preserves_state_then_refuses_second_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'state.json').write_bytes(b'{"status":"exporting"}')
            save_evidence(rendering_fixture(),path)
            before={p.name:p.read_bytes() for p in path.iterdir()}
            self.assertNotIn('state.json',json.loads((path/'manifest.json').read_text(encoding='utf-8'))['sha256'])
            self.assertFalse((path/'.evidence-writing').exists())
            with self.assertRaises(FileExistsError):save_evidence(rendering_fixture(),path)
            self.assertEqual(before,{p.name:p.read_bytes() for p in path.iterdir()})

    def test_manifest_or_writer_reservation_blocks_overwrite(self):
        for existing in ('manifest.json','.evidence-writing'):
            with self.subTest(existing=existing),tempfile.TemporaryDirectory() as directory:
                path=Path(directory);(path/existing).write_bytes(b'preserve')
                with self.assertRaises(FileExistsError):save_evidence(rendering_fixture(),path)
                self.assertEqual((path/existing).read_bytes(),b'preserve');self.assertFalse((path/'result.json').exists())

    def test_uploaded_html_matches_source_role_and_escapes_label(self):
        with tempfile.TemporaryDirectory() as directory:
            save_evidence(rendering_fixture(),directory)
            report=(Path(directory)/'report.html').read_text(encoding='utf-8')
        self.assertIn('用户声明授权负荷 &lt;来源&gt;',report)
        self.assertIn('本次为探索性区间',report)
        self.assertNotIn('真实公开负荷',report);self.assertNotIn('2018年12月历史回归',report)

if __name__=='__main__':unittest.main()
