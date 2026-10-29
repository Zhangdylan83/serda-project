"""Frozen package software fixtures only, never real clinical notes."""
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from serda_pipeline import ga_frozen_extract as f
from serda_pipeline.ga_schema_review import highlight
from serda_pipeline.ga_schema_engine import extract

CONFIG=Path(__file__).resolve().parents[1]/'configs'/'serda_ga_erika.yaml'


def fixture(root,text='MoCA 15/30. Needs assistance with bathing. Two falls during the past year.'):
    package=root/'Frozen Package';(package/'candidates').mkdir(parents=True)
    internal=hashlib.sha256(b'software fixture note identity').hexdigest()
    original=dict(sample_id='S001',internal_note_id=internal,patient_key='TEST_ONLY',anchor_date='2024-01-01',
                  identity_approved='no',reconstruction_approved='no',target_ga_approved='no',reviewer='',review_comment='')
    approved=dict(original,identity_approved='yes',reconstruction_approved='yes',reviewer='software test')
    with (package/'sample_manifest.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(approved));w.writeheader();w.writerow(approved)
    mapping=[dict(source_file='Notes.xlsx',source_sheet='Sheet',source_excel_row=2,original_line_number='1',text_start=0,text_end=len(text),original_text=text)]
    f.save(package/'candidates'/(internal+'.json'),dict(internal_note_id=internal,text=text,source_rows=mapping,hard_blocks=[]))
    f.save(package/'run_manifest.json',dict(sample_membership=[['S001',internal]],frozen_sample_rows=[original],sample_files={internal:f.digest(package/'candidates'/(internal+'.json'))}))
    (package/'baseline').mkdir();(package/'baseline'/'review.html').write_text('original baseline must stay untouched')
    # A malformed unselected candidate proves the loader must not enumerate candidates.
    (package/'candidates'/'not_selected.json').write_text('DO NOT READ')
    return package,internal


class FrozenTests(unittest.TestCase):
    def test_old_package_no_prepare_or_excel_and_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package,_=fixture(root);output=root/'new results'
            before={p.relative_to(package):f.digest(p) for p in package.rglob('*') if p.is_file()}
            with patch('openpyxl.load_workbook',side_effect=AssertionError('No Excel allowed')),patch('serda_pipeline.ga_validation.prepare',side_effect=AssertionError('No Prepare allowed')):
                count,counts=f.run(package,output,CONFIG)
            self.assertEqual(count,1);self.assertGreater(counts['extracted'],4)
            self.assertEqual(before,{p.relative_to(package):f.digest(p) for p in package.rglob('*') if p.is_file()})
            manifest=f.read(output/'run_manifest.json');self.assertFalse(manifest['record_order'][0]['target_confirmed'])
            self.assertEqual(manifest['input_mode'],'frozen_development_samples')
            data=[json.loads(s) for s in (output/'ga_features.jsonl').read_text().splitlines()]
            self.assertEqual(data[0]['physical_function']['adl']['bathing'],'needs_assistance')
            self.assertIn('unsupported', (output/'field_coverage.csv').read_text())
            with self.assertRaises(f.InputError):f.run(package,output,CONFIG)

    def test_tampering_missing_approval_and_output_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package,internal=fixture(root)
            with self.assertRaises(f.InputError):f.run(package,package/'new',CONFIG)
            with self.assertRaises(f.InputError):f.run(package,Path(__file__).resolve().parents[1]/'outputs'/'new',CONFIG)
            p=package/'candidates'/(internal+'.json');p.write_text('{}')
            with self.assertRaises(f.InputError):f.load_package(package)
        with tempfile.TemporaryDirectory() as tmp:
            package,_=fixture(Path(tmp))
            p=package/'sample_manifest.csv';p.write_text(p.read_text().replace('yes,yes','no,yes'))
            with self.assertRaises(f.InputError):f.load_package(package)

    def test_metadata_and_provenance_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            package,internal=fixture(Path(tmp))
            p=package/'candidates'/(internal+'.json');item=f.read(p);item['source_rows'][0]['text_end']=2;f.save(p,item)
            manifest=f.read(package/'run_manifest.json');manifest['sample_files'][internal]=f.digest(p);f.save(package/'run_manifest.json',manifest)
            with self.assertRaises(f.InputError):f.load_package(package)

    def test_html_escaped_and_color_semantics(self):
        text='<script>MoCA 15/30.</script> Previous MMSE 20/30. SPPB mentioned.'
        _,audit=extract(text);html=highlight(text,audit)
        self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)
        self.assertIn('class="accepted"',html);self.assertIn('class="unresolved"',html);self.assertIn('class="keyword"',html)

    def test_config_nulls_and_windows_launcher_contract(self):
        cfg=f.load_config(CONFIG)
        self.assertIsNone(cfg['ga_input']['cohort_anchor_file']);self.assertIsNone(cfg['ga_input']['target_note_manifest'])
        self.assertEqual(cfg['columns']['notes']['mrn'],'PAT_MRN_ID')
        self.assertEqual(cfg['columns']['notes']['anchor_flag'],'Anchor')
        script=(CONFIG.parents[1]/'scripts'/'run_ga_erika_extract.ps1').read_text()
        self.assertIn('[string]$PackagePath',script);self.assertIn('Join-Path',script);self.assertIn('Resolve-Path -LiteralPath',script)
        self.assertNotIn('--ga-validation-prepare',script)

    def test_curated_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();path=source/'confirmed.jsonl';text='ECOG: 2'
            record=dict(sample_id='TEST_ONLY',text=text,identity_approved=True,reconstruction_approved=True,target_confirmed=True,confirmation_source='software contract fixture',source_rows=[dict(text_start=0,text_end=len(text),original_text=text,source_excel_row=2)])
            path.write_text(json.dumps(record)+'\n')
            count,_=f.run(path,root/'new',CONFIG,curated=True);self.assertEqual(count,1)
            record['target_confirmed']=False;path.write_text(json.dumps(record)+'\n')
            with self.assertRaises(f.InputError):f.load_curated(path)

    def test_cli_and_lightweight_import_boundary(self):
        import subprocess
        import sys
        repo=CONFIG.parents[1]
        check=subprocess.run([sys.executable,'-c',"import sys; import serda_pipeline.ga_frozen_extract; assert 'openpyxl' not in sys.modules; assert 'pandas' not in sys.modules"],cwd=repo,capture_output=True,text=True)
        self.assertEqual(check.returncode,0,check.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package,_=fixture(root)
            process=subprocess.run([sys.executable,'-m','serda_pipeline.ga_frozen_extract','--package',str(package),'--output-dir',str(root/'new'),'--config',str(CONFIG)],cwd=repo,capture_output=True,text=True)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertIn('1 notes',process.stdout)
            self.assertNotIn('TEST_ONLY',process.stdout)
            self.assertNotIn('MoCA',process.stdout)
