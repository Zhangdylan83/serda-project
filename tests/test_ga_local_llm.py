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
        _,audit=extract(text);fields=llm.domain_fields(domain);findings=[]
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
        self.assertEqual(wrong['verification'],'rejected')
        short=llm.verify(finding('cognition.moca.value',15,'15'),r,0,len(text))
        self.assertEqual(short['verification'],'review')
        repeated=record('MoCA 15/30. MoCA 15/30.')
        self.assertEqual(llm.verify(finding('cognition.moca.value',15,'MoCA 15/30'),repeated,0,len(repeated['text']))['verification'],'review')

    def test_context_and_uncertainty(self):
        for text in ['Previous MoCA 15/30.','MoCA 15/30 not performed.','No MoCA 15/30.']:
            r=record(text)
            self.assertNotEqual(llm.verify(finding('cognition.moca.value',15,'MoCA 15/30'),r,0,len(text))['verification'],'accepted')
        r=record('Independent with all ADLs except bathing.')
        value=llm.verify(finding('physical_function.adl.bathing','independent','Independent with all ADLs'),r,0,len(r['text']))
        self.assertEqual(value['verification'],'review')
        r=record('MoCA 15/30')
        self.assertEqual(llm.verify(finding('cognition.moca.value',15,r['text'],'uncertain'),r,0,len(r['text']))['verification'],'review')

    def test_new_phrasing_is_retained_for_human_review(self):
        text='The patient requires another person to help with showering.'
        candidate=llm.verify(finding('physical_function.adl.bathing','needs_assistance',text),record(text),0,len(text))
        self.assertEqual(candidate['verification'],'review');self.assertEqual(candidate['quote'],text)

    def test_conflicts_and_partial_domains_cannot_be_accepted(self):
        cfg=llm.load_config(CONFIG);cfg['domains']=['cognition'];r=record('MoCA 15/30. MoCA 20/30.')
        hits=[dict(finding('cognition.moca.value',v,f'MoCA {v}/30'),verification='accepted',character_start=0,character_end=10) for v in [15,20]]
        obj,audit=llm.consolidate(r,hits,cfg,{(r['sample_id'],'cognition'):True})
        self.assertEqual(obj,{})
        self.assertEqual(next(a for a in audit if a['field_path']=='cognition.moca.value')['status'],'conflicting')
        obj,audit=llm.consolidate(r,hits[:1],cfg,{(r['sample_id'],'cognition'):False})
        self.assertEqual(obj,{});self.assertTrue(all(a['status']=='domain_incomplete' for a in audit))

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
            self.assertEqual({r['field_path'] for r in rows},set().union(*(set(llm.domain_fields(d)) for d in llm.DOMAIN_PREFIXES)))
            self.assertIn('exact_quote_and_field_value_rule_verified',(out/'llm_evidence.jsonl').read_text())
            self.assertTrue((out/'request_runtime.csv').exists())
            with self.assertRaises(llm.LLMError):llm.run(CONFIG,out,server_factory=MockServer)

    def test_windows_launcher_contract(self):
        script=(CONFIG.parents[1]/'scripts'/'run_ga_local_llm.ps1').read_text()
        self.assertIn('[switch]$AuthorizePatientInference',script)
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
            self.assertEqual(manifest['request_count'],4)
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
