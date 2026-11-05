"""Synthetic-only protocol/verification tests. No real model or PHI evaluation."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from serda_pipeline import ga_local_llm as llm
from serda_pipeline.ga_schema_engine import extract

CONFIG=Path(__file__).resolve().parents[1]/'configs'/'serda_ga_llm.yaml'


def record(text):return dict(sample_id='SYNTHETIC_ONLY',text=text,source_rows=[dict(source_excel_row=7,text_start=0,text_end=len(text))])

def finding(path,value,quote,certainty='explicit'):return dict(field_path=path,value=value,quote=quote,certainty=certainty)


def reply(findings):return dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps({'findings':findings})))],usage={'completion_tokens':20})


class MockClient:
    def __init__(self,cfg):self.cfg=cfg;self.calls=[]
    def tokens(self,msg):return len(json.dumps(msg))//4
    def generate(self,domain,msg):
        self.calls.append((domain,msg));text=json.loads(msg[-1]['content'])['source_text']
        _,audit=extract(text);fields=json.loads(msg[-1]['content'])['allowed_fields'];findings=[]
        for a in audit:
            if a['field_path'] in fields and a['extraction_status']=='extracted':
                findings.append(finding(a['field_path'],a['predicted_value'],a['accepted_evidence'][0]['evidence_text']))
        return reply(findings)


class MockServer:
    def __init__(self,cfg,out):self.client=MockClient(cfg);self.metadata={'mock':True}
    def __enter__(self):return self.client
    def __exit__(self,*args):pass


class LLMTests(unittest.TestCase):
    def test_config_and_loopback_only(self):
        cfg=llm.load_config(CONFIG)
        args=llm.server_args(cfg,'synthetic-test-key')
        self.assertEqual(args[args.index('--host')+1],'127.0.0.1')
        self.assertEqual(args[args.index('--n-gpu-layers')+1],'0')
        self.assertIn('--log-disable',args);self.assertNotIn('--tools',args)
        for host in ['localhost','0.0.0.0','https://example.com','127.0.0.1.evil.invalid']:
            bad=dict(cfg,host=host)
            with self.assertRaises(llm.LLMError):llm.LocalClient(bad,'test')
            with self.assertRaises(llm.LLMError):llm.server_args(bad,'test')
        with self.assertRaises(llm.LLMError):llm.NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_schema_and_truncated_responses(self):
        f=finding('cognition.moca.value',15,'MoCA 15/30')
        self.assertEqual(llm.parse_reply(reply([f]),'cognition'),[f])
        for bad in [reply([dict(f,field_path='nutrition.bmi')]),reply([dict(f,value='fifteen')]),reply([dict(f,value=True)])]:
            with self.assertRaises(llm.LLMError):llm.parse_reply(bad,'cognition')
        bad=reply([f]);bad['choices'][0]['finish_reason']='length'
        with self.assertRaises(llm.LLMError):llm.parse_reply(bad,'cognition')
        bad=reply([f]);bad['choices'][0]['message']['tool_calls']=[{'function':{'name':'external'}}]
        with self.assertRaises(llm.LLMError):llm.parse_reply(bad,'cognition')

    def test_quote_and_value_verification(self):
        text='MoCA 15/30.';r=record(text)
        good=llm.verify(finding('cognition.moca.value',15,'MoCA 15/30'),r,0,len(text))
        self.assertEqual(good['verification'],'accepted');self.assertEqual(good['source_excel_rows'],[7])
        self.assertEqual(text[good['character_start']:good['character_end']],good['quote'])
        fake=llm.verify(finding('cognition.moca.value',29,'MoCA 29/30'),r,0,len(text))
        self.assertEqual(fake['verification'],'rejected')
        wrong=llm.verify(finding('cognition.moca.value',29,'MoCA 15/30'),r,0,len(text))
        self.assertEqual(wrong['verification'],'accepted')  # Human reference must catch wrong values.
        short=llm.verify(finding('cognition.moca.value',15,'15'),r,0,len(text))
        self.assertEqual(short['verification'],'accepted')
        repeated=record('MoCA 15/30. MoCA 15/30.')
        self.assertEqual(llm.verify(finding('cognition.moca.value',15,'MoCA 15/30'),repeated,0,len(repeated['text']))['verification'],'review')

    def test_context_and_uncertainty(self):
        for text in ['Previous MoCA 15/30.','MoCA 15/30 not performed.','No MoCA 15/30.']:
            r=record(text)
            self.assertEqual(llm.verify(finding('cognition.moca.value',15,'MoCA 15/30'),r,0,len(text))['verification'],'accepted')
        r=record('Independent with all ADLs except bathing.')
        value=llm.verify(finding('physical_function.adl.bathing','independent','Independent with all ADLs'),r,0,len(r['text']))
        self.assertEqual(value['verification'],'accepted')
        r=record('MoCA 15/30')
        self.assertEqual(llm.verify(finding('cognition.moca.value',15,r['text'],'uncertain'),r,0,len(r['text']))['verification'],'review')

    def test_new_phrasing_is_retained_for_human_review(self):
        text='The patient requires another person to help with showering.'
        candidate=llm.verify(finding('physical_function.adl.bathing','needs_assistance',text),record(text),0,len(text))
        self.assertEqual(candidate['verification'],'accepted');self.assertEqual(candidate['quote'],text)

    def test_conflicts_and_partial_domains_cannot_be_accepted(self):
        cfg=llm.load_config(CONFIG);cfg['domains']=['cognition'];r=record('MoCA 15/30. MoCA 20/30.')
        hits=[dict(finding('cognition.moca.value',v,f'MoCA {v}/30'),verification='accepted',character_start=0,character_end=10) for v in [15,20]]
        obj,audit=llm.consolidate(r,hits,cfg,{(r['sample_id'],'cognition'):True})
        self.assertEqual(obj,{})
        self.assertEqual(next(a for a in audit if a['field_path']=='cognition.moca.value')['status'],'conflicting')
        obj,audit=llm.consolidate(r,hits[:1],cfg,{(r['sample_id'],'cognition'):False})
        self.assertEqual(obj,{});self.assertTrue(all(a['status']=='domain_incomplete' for a in audit if a['field_path'].startswith('cognition.')))

    def test_context_budget_and_all_chunk_coverage(self):
        cfg=llm.load_config(CONFIG);cfg.update(domains=['cognition'],chunk_characters=256,chunk_overlap=40)
        r=record(('Synthetic neutral prose. '*60)+'MoCA 15/30.')
        client=MockClient(cfg);_,requests,coverage,_=llm.infer([r],cfg,client)
        self.assertTrue(coverage[r['sample_id'],'cognition'])
        covered=set()
        for q in requests:
            covered.update(range(q['chunk_start'],q['chunk_end']))
            self.assertLessEqual(q['prompt_tokens']+cfg['output_tokens']+64,cfg['context_tokens'])
        self.assertEqual(covered,set(range(len(r['text']))))
        cfg['max_requests']=1
        _,_,coverage,_=llm.infer([r],cfg,client)
        self.assertFalse(coverage[r['sample_id'],'cognition'])

    def test_gate_before_reading_package(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(llm,'load_package',side_effect=AssertionError('Must not read patient text')):
            with self.assertRaises(llm.LLMError):llm.run(CONFIG,Path(tmp)/'run',package=Path(tmp)/'not_read',server_factory=MockServer)
            if os.name!='nt':
                with self.assertRaises(llm.LLMError):llm.run(CONFIG,Path(tmp)/'run',package=Path(tmp)/'not_read',authorized=True,server_factory=MockServer)

    def test_mock_end_to_end_outputs_and_same_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'synthetic_run'
            with patch.object(llm,'load_package',side_effect=AssertionError('Synthetic mode never reads package')):
                self.assertTrue(llm.run(CONFIG,out,server_factory=MockServer))
            manifest=json.loads((out/'run_manifest.json').read_text())
            self.assertEqual(manifest['mode'],'synthetic')
            self.assertEqual(manifest['runtime'],'synthetic_development_or_mock')
            self.assertTrue(manifest['synthetic_smoke_passed'])
            import csv
            with (out/'llm_regex_comparison.csv').open() as f:rows=list(csv.DictReader(f))
            self.assertEqual({r['sample_id'] for r in rows},{'SYNTHETIC_001'})
            self.assertEqual({r['field_path'] for r in rows},set().union(*(set(llm.domain_fields(d)) for d in llm.DOMAIN_PREFIXES))|{'note_id','note_date'})
            self.assertIn('exact_quote_located_clinical_meaning_unverified',(out/'llm_evidence.jsonl').read_text())
            self.assertTrue((out/'request_runtime.csv').exists())
            self.assertTrue((out/'regex_ga_features.jsonl').exists())
            self.assertTrue((out/'regex_evidence.jsonl').exists())
            self.assertTrue((out/'reference_annotations.csv').exists())
            with self.assertRaises(llm.LLMError):llm.run(CONFIG,out,server_factory=MockServer)

    def test_windows_launcher_contract(self):
        script=(CONFIG.parents[1]/'scripts'/'run_ga_local_llm.ps1').read_text()
        self.assertIn('[switch]$AuthorizePatientInference',script)
        self.assertIn('if ($PackagePath -and -not $AuthorizePatientInference)',script)
        self.assertIn('if ($SyntheticPassRun)',script)
        self.assertNotIn('-or -not $SyntheticPassRun',script)
        self.assertIn("-ine 'Z:'",script)
        self.assertNotIn('Z:\\PHI',script);self.assertNotIn('--ga-validation-prepare',script)

    @unittest.skipIf(os.name=='nt','Executable protocol fixture uses a POSIX shebang; real Windows validation is separate.')
    def test_persistent_process_http_integration_synthetic_only(self):
        import socket
        import stat
        import sys
        repo=CONFIG.parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'mock_server'
            original=(repo/'tests'/'fixtures'/'llama_server_mock.py').read_text()
            # Keep production modules importable after copying the fixture to a temporary directory.
            original=original.replace('#!/usr/bin/env python3','#!'+sys.executable).replace("str(Path(__file__).resolve().parents[2])",repr(str(repo)))
            binary.write_text(original);binary.chmod(binary.stat().st_mode|stat.S_IXUSR)
            model=root/'synthetic_model_sentinel.txt';model.write_text('NOT MODEL WEIGHTS; synthetic protocol test sentinel')
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            cfg=llm.load_config(CONFIG);cfg.update(server_binary=str(binary),model_path=str(model),port=port,startup_timeout_seconds=10)
            config=root/'mock_config.yaml';config.write_text(yaml.safe_dump(cfg))
            class SyntheticManager(llm.ManagedServer):pass
            with patch.dict(os.environ,{'HTTP_PROXY':'http://127.0.0.1:1','HTTPS_PROXY':'http://127.0.0.1:1'}):
                self.assertTrue(llm.run(config,root/'output',server_factory=SyntheticManager))
            manifest=json.loads((root/'output'/'run_manifest.json').read_text())
            self.assertEqual(manifest['runtime'],'synthetic_development_or_mock')
            self.assertEqual(manifest['request_count'],sum(len(llm.field_batches(d)) for d in cfg['domains']))
            self.assertTrue(manifest['server']['model_sha256'])
            with socket.socket() as sock:self.assertNotEqual(sock.connect_ex(('127.0.0.1',port)),0)

    def test_failed_domain_and_invalid_json_are_recorded(self):
        cfg=llm.load_config(CONFIG)
        class Broken(MockClient):
            def generate(self,domain,msg):
                if domain=='cognition':return {'choices':[{'finish_reason':'stop','message':{'content':'not json'}}]}
                return super().generate(domain,msg)
        records=llm.synthetic_records();candidates,requests,coverage,_=llm.infer(records,cfg,Broken(cfg))
        self.assertFalse(coverage['SYNTHETIC_001','cognition'])
        self.assertTrue(coverage['SYNTHETIC_001','nutrition'])
        obj,audit=llm.consolidate(records[0],candidates['SYNTHETIC_001'],cfg,coverage)
        self.assertNotIn('cognition',obj);self.assertIn('nutrition',obj)
        self.assertTrue(any(r['status']=='failed' for r in requests))

    def test_synthetic_receipt_gate_rejects_mock_and_stale_runs(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            receipt={'mode':'synthetic','runtime':'synthetic_development_or_mock','synthetic_smoke_passed':True,'code_sha256':llm.code_hashes(),'config_sha256':'test-config'}
            (path/'run_manifest.json').write_text(json.dumps(receipt))
            with patch.object(llm,'os',SimpleNamespace(name='nt')):
                with self.assertRaises(llm.LLMError):llm.authorize_package('not opened',True,path,'test-config')
                receipt['runtime']='Windows_SERDA_local_model';receipt['code_sha256']={}
                (path/'run_manifest.json').write_text(json.dumps(receipt))
                with self.assertRaises(llm.LLMError):llm.authorize_package('not opened',True,path,'test-config')
                receipt['code_sha256']=llm.code_hashes()
                (path/'run_manifest.json').write_text(json.dumps(receipt))
                self.assertEqual(llm.authorize_package('not opened',True,path,'test-config')['mode'],'synthetic')

    def test_full_schema_partition_and_prompt_bounds(self):
        cfg=llm.load_config(CONFIG)
        self.assertEqual(set(cfg['domains']),set(llm.CLINICAL_DOMAINS))
        all_paths=[]
        for domain in cfg['domains']:
            batches=llm.field_batches(domain,cfg['fields_per_prompt'])
            paths=[p for batch in batches for p in batch]
            self.assertEqual(set(paths),set(llm.domain_fields(domain)))
            self.assertEqual(len(paths),len(set(paths)))
            self.assertTrue(all(len(batch)<=cfg['fields_per_prompt'] for batch in batches))
            for batch in batches:
                for path in batch:
                    if path.endswith('.value'):
                        parent=path.rsplit('.',1)[0]
                        self.assertTrue(all(p in batch for p in paths if p.startswith(parent+'.')))
                prompt=llm.messages(domain,'SYNTHETIC note.',batch)
                self.assertEqual(set(json.loads(prompt[-1]['content'])['allowed_fields']),set(batch))
            all_paths.extend(paths)
        self.assertEqual(len(all_paths),114)
        self.assertEqual(set(all_paths)|{'note_id','note_date'},set(llm.schema_leaves()[1]))

    def test_batch_schema_rejects_out_of_batch_field(self):
        fields=['cognition.moca.value','cognition.moca.max','cognition.moca.interpretation']
        with self.assertRaises(llm.LLMError):
            llm.parse_reply(reply([finding('cognition.mmse.value',20,'MMSE 20/30')]),'cognition',fields)

    def test_full_run_has_ten_domain_checks_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'full'
            self.assertTrue(llm.run(CONFIG,out,server_factory=MockServer))
            manifest=json.loads((out/'run_manifest.json').read_text())
            self.assertTrue(manifest['full_clinical_schema_requested'])
            self.assertEqual(manifest['clinical_field_count'],114)
            evidence=json.loads((out/'llm_evidence.jsonl').read_text())
            self.assertEqual(len(evidence['fields']),116)
            obj=json.loads((out/'llm_ga_features.jsonl').read_text())
            self.assertTrue(set(llm.CLINICAL_DOMAINS).issubset(obj))
            self.assertEqual(obj['note_id'],'SYNTHETIC_DOCUMENT_ONLY')
            self.assertTrue((out/'llm_proposals_for_review.jsonl').exists())

    def test_metadata_never_substitutes_note_csn_or_patient(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'candidate.json'
            p.write_text(json.dumps({'note_date':'2024-01-01','raw_rows':[{'note_id':None,'note_csn':'SYNTHETIC_CONTACT','note_date':'2024-01-01'}]}))
            r={'source_package_candidate':'candidate.json'}
            llm.attach_metadata([r],root,{'candidate.json':llm.digest(p)})
            self.assertNotIn('note_id',r['schema_metadata'])
            self.assertEqual(r['schema_metadata']['note_date']['value'],'2024-01-01')

    def test_novel_llm_value_is_exported_for_review_not_silently_dropped(self):
        text=llm.SYNTHETIC_TEXT.replace('Independent with all ADLs.','The patient requires another person to help with showering.')
        quote='The patient requires another person to help with showering.'
        class NovelClient(MockClient):
            def generate(self,domain,msg):
                result=super().generate(domain,msg)
                fields=json.loads(msg[-1]['content'])['allowed_fields']
                if 'physical_function.adl.bathing' in fields:
                    obj=json.loads(result['choices'][0]['message']['content'])
                    obj['findings'].append(finding('physical_function.adl.bathing','needs_assistance',quote))
                    result['choices'][0]['message']['content']=json.dumps(obj)
                return result
        class NovelServer(MockServer):
            def __init__(self,cfg,out):self.client=NovelClient(cfg);self.metadata={'mock':True}
        r=llm.synthetic_records()[0];r['text']=text
        with tempfile.TemporaryDirectory() as tmp,patch.object(llm,'synthetic_records',return_value=[r]):
            out=Path(tmp)/'novel'
            self.assertFalse(llm.run(CONFIG,out,server_factory=NovelServer))
            proposal=json.loads((out/'llm_proposals_for_review.jsonl').read_text())
            accepted=json.loads((out/'llm_ga_features.jsonl').read_text())
            self.assertEqual(proposal['physical_function']['adl']['bathing'],'needs_assistance')
            self.assertEqual(accepted['physical_function']['adl']['bathing'],'needs_assistance')
            evidence=json.loads((out/'llm_evidence.jsonl').read_text())
            self.assertEqual(next(f for f in evidence['fields'] if f['field_path']=='physical_function.adl.bathing')['status'],'accepted')

    def test_llm_inference_never_calls_regex(self):
        class IndependentClient(MockClient):
            def generate(self, domain, msg):
                fields=json.loads(msg[-1]['content'])['allowed_fields']
                return reply([finding('cognition.moca.value',29,'MoCA 15/30')] if 'cognition.moca.value' in fields else [])
        cfg=llm.load_config(CONFIG);cfg['domains']=['cognition']
        r=record('MoCA 15/30')
        with patch.object(llm,'extract',side_effect=AssertionError('Regex must not judge LLM')):
            candidates,_,coverage,_=llm.infer([r],cfg,IndependentClient(cfg))
            obj,_=llm.consolidate(r,candidates[r['sample_id']],cfg,coverage)
        self.assertEqual(obj['cognition']['moca']['value'],29)

    def test_direct_authorization_without_smoke(self):
        from types import SimpleNamespace
        with patch.object(llm,'os',SimpleNamespace(name='nt')):
            self.assertIsNone(llm.authorize_package('explicit package',True,None,'config'))
            with self.assertRaises(llm.LLMError):llm.authorize_package('explicit package',False,None,'config')
        with patch.object(llm,'os',SimpleNamespace(name='posix')):
            with self.assertRaises(llm.LLMError):llm.authorize_package('explicit package',True,None,'config')

    def test_direct_package_preserves_integrity_and_independent_outputs(self):
        from tests.test_ga_frozen_extract import fixture
        from types import SimpleNamespace
        authorize=llm.authorize_package
        def windows_gate(*args):
            # Simulate only the platform authorization gate; filesystem remains Linux.
            with patch.object(llm,'os',SimpleNamespace(name='nt')):return authorize(*args)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package,internal=fixture(root)
            before={str(p.relative_to(package)):llm.digest(p) for p in package.rglob('*') if p.is_file()}
            with patch.object(llm,'authorize_package',side_effect=windows_gate),patch('openpyxl.load_workbook',side_effect=AssertionError('No Excel')),patch('serda_pipeline.ga_validation.prepare',side_effect=AssertionError('No Prepare')):
                out=root/'direct'
                self.assertTrue(llm.run(CONFIG,out,package=package,authorized=True,server_factory=MockServer))
                manifest=json.loads((out/'run_manifest.json').read_text())
                self.assertEqual(manifest['synthetic_receipt_status'],'not_supplied_optional')
                self.assertTrue(manifest['patient_inference_explicitly_authorized'])
                self.assertEqual(manifest['record_order'][0]['sample_id'],'S001')
                for name in ['llm_evidence.jsonl','regex_evidence.jsonl','llm_regex_comparison.csv','reference_annotations.csv','review.html']:
                    self.assertTrue((out/name).is_file())
                self.assertEqual(before,{str(p.relative_to(package)):llm.digest(p) for p in package.rglob('*') if p.is_file()})
                with self.assertRaises(llm.LLMError):llm.run(CONFIG,out,package=package,authorized=True,server_factory=MockServer)
                with self.assertRaises(llm.LLMError):llm.run(CONFIG,package/'output',package=package,authorized=True,server_factory=MockServer)
                with self.assertRaises(llm.LLMError):llm.run(CONFIG,root/'missing'/'output',package=package,authorized=True,server_factory=MockServer)
                # Tampering still fails before any inference server starts.
                (package/'candidates'/(internal+'.json')).write_text('{}')
                from serda_pipeline.ga_frozen_extract import InputError
                with patch.object(llm,'ManagedServer',side_effect=AssertionError('No server on invalid package')):
                    with self.assertRaises(InputError):llm.run(CONFIG,root/'tampered',package=package,authorized=True,server_factory=llm.ManagedServer)

    def test_direct_package_missing_approval_is_blocked(self):
        from tests.test_ga_frozen_extract import fixture
        from serda_pipeline.ga_frozen_extract import InputError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package,_=fixture(root)
            manifest=package/'sample_manifest.csv'
            manifest.write_text(manifest.read_text().replace('yes,yes','no,yes'))
            with patch.object(llm,'authorize_package',return_value=None),patch.object(llm,'ManagedServer',side_effect=AssertionError('No server without approval')):
                with self.assertRaises(InputError):llm.run(CONFIG,root/'new',package=package,authorized=True,server_factory=llm.ManagedServer)

    def test_direct_package_membership_changes_rejected(self):
        from tests.test_ga_frozen_extract import fixture
        from serda_pipeline.ga_frozen_extract import InputError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package,_=fixture(root)
            manifest=package/'sample_manifest.csv'
            manifest.write_text(manifest.read_text().replace('S001','S009'))
            with patch.object(llm,'authorize_package',return_value=None),patch.object(llm,'ManagedServer',side_effect=AssertionError('No server on membership changes')):
                with self.assertRaises(InputError):llm.run(CONFIG,root/'new',package=package,authorized=True,server_factory=llm.ManagedServer)
