import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from serda_pipeline import ga_validation as v
from serda_pipeline.ga_review_report import highlighted
from serda_pipeline.core import PipelineError

class ValidationTests(unittest.TestCase):
    def group(self):
        return dict(key='test-note',rows=[(0,'test-patient','2024-01-01','Geriatric assessment','Yes',1,'1','Geriatric Assessment <script>','enc','author','note','csn','2024-01-01'),(1,'test-patient','2024-01-01','Geriatric assessment','Yes',3,'3','MoCA 15/30','enc','author','note','csn','2024-01-01')],reasons=['identity_unverified_candidate_group_only','line_gap_or_start'],patient='test-patient',day='2024-01-01',kind='Geriatric assessment',flag='Yes',reference_days=['2024-01-01'],invalid_reference=False,source_file='Notes.xlsx',source_sheet='Sheet',header_row=2,separator='\n',line_start=1)

    def test_mapping_gap_is_review_question(self):
        n=v.candidate(self.group())
        self.assertEqual(n['hard_blocks'],[])
        for r in n['source_rows']:
            self.assertEqual(n['text'][r['text_start']:r['text_end']],r['original_text'])
        self.assertEqual(n['source_rows'][0]['source_excel_row'],4)
        self.assertIn('line_gap_or_start',n['reconstruction_warnings'])

    def test_html_escape(self):
        self.assertNotIn('<script>',highlighted('<script>x</script>',[(0,8)]))

    def test_three_stages_and_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source';root.mkdir();out=Path(tmp)/'package'
            for f in ['Notes.xlsx','Frailty Demographics.xlsx']: (root/f).write_bytes(b'test fixture fingerprint only')
            def capture(*args,**kwargs): kwargs['review_callback'](self.group())
            with patch.object(v.ga,'run',side_effect=capture): v.prepare(root,out,{'ga_validation':{'sample_size':8}},'mrn')
            v.run(out,'unapproved')
            self.assertTrue(all(p['extraction_status']=='blocked' for p in v.table(out/'unapproved'/'predictions.csv')))
            m=v.table(out/'sample_manifest.csv')
            for k in ['identity_approved','reconstruction_approved','target_ga_approved']:m[0][k]='yes'
            m[0]['reviewer']='unit tester';v.write_table(out/'sample_manifest.csv',m,v.MANIFEST)
            v.run(out)
            predictions=v.table(out/'baseline'/'predictions.csv')
            self.assertEqual(len(predictions),len(v.registry()))
            moca=next(p for p in predictions if p['field_path']=='local.moca')
            self.assertEqual((moca['predicted_value'],moca['extraction_status']),('15','extracted'))
            self.assertEqual(moca['source_rows'],'[5]')
            refs=v.table(out/'reference_annotations.csv')
            for r in refs:
                if r['field_path']=='local.moca':r.update(reference_status='documented',reference_value='15',reference_denominator='30',reference_evidence='MoCA 15/30',reviewer='unit tester')
            v.write_table(out/'reference_annotations.csv',refs,v.REFERENCE);v.evaluate(out)
            self.assertTrue((out/'baseline'/'evaluation'/'evaluation_by_field.csv').exists())
            with self.assertRaises(PipelineError):v.run(out)
            m[0]['anchor_date']='changed';v.write_table(out/'sample_manifest.csv',m,v.MANIFEST)
            with self.assertRaises(PipelineError):v.load_package(out)

    def test_comparison_distinguishes_absence_support_and_errors(self):
        r=dict(reference_status='documented',reference_value='15',reference_denominator='30',needs_erika_review='no')
        p=dict(extraction_status='not_found',predicted_value='',predicted_denominator='')
        self.assertEqual(v.compare(p,r),'missed_documented_value')
        p['extraction_status']='not_supported';self.assertEqual(v.compare(p,r),'unsupported_documented')
        p.update(extraction_status='extracted',predicted_value='14',predicted_denominator='30')
        self.assertEqual(v.compare(p,r),'incorrect_value_or_denominator')

    def test_prepare_real_loader_header_and_fragment_fixture(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source';root.mkdir();out=Path(tmp)/'review'
            for name,rows in [('Frailty Demographics.xlsx',[['PAT_ID','CONTACT_DATE'],['TEST_ONLY','2024-01-01']]),('Notes.xlsx',[['PAT_ID','NOTE_ID','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor','NOTE_TYPE'],['TEST_ONLY','TEST_NOTE',1,'2024-01-01','Geriatric Assessment MoCA 15/30','Yes','Geriatric assessment']])]:
                book=Workbook()
                for row in rows:book.active.append(row)
                book.save(root/name)
            config=dict(excel_date_min=20000,excel_date_max=80000,dayfirst=False,notes={'note_key_verified':False,'note_key_fields':['note_id']})
            with patch.object(v.ga,'extract_text',side_effect=AssertionError('Prepare must not extract')):
                v.prepare(root,out,config,'pat_id')
            self.assertEqual(len(v.table(out/'sample_manifest.csv')),1)
            self.assertFalse(config['notes']['note_key_verified'])
            self.assertIsNotNone(v.read(out/'run_manifest.json')['schema_sha256'])
