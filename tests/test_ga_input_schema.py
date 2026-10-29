"""Software-only contract fixtures; not clinical evaluation."""
import csv
import tempfile
import unittest
from pathlib import Path
from serda_pipeline import ga_validation as v
from serda_pipeline.ga_input import master, targets
from serda_pipeline.ga_schema_adapter import registry
from serda_pipeline.core import PipelineError
from tests import test_ga_validation


def csv_file(path, rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


class InputTests(unittest.TestCase):
    def master_row(self):
        return dict(patient_key='000TEST',patient_key_type='mrn',anchor_date='2024-01-01',eligible='yes',confirmation_status='confirmed',source='test contract',reviewer='tester')

    def test_master_string_key_duplicate_and_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'master.csv';row=self.master_row();csv_file(path,[row])
            cfg={'ga_input':{'anchor_source':'approved_master','cohort_anchor_file':str(path)}}
            self.assertEqual(master(cfg,'mrn')[0]['000TEST'],{'2024-01-01'})
            with self.assertRaises(PipelineError):master(cfg,'pat_id')
            csv_file(path,[row,row])
            with self.assertRaises(PipelineError):master(cfg,'mrn')
            row['anchor_date']='01/02/2024';csv_file(path,[row])
            with self.assertRaises(PipelineError):master(cfg,'mrn')

    def test_manifest_multiple_targets_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'target.csv'
            row=dict(patient_key='000TEST',patient_key_type='mrn',anchor_date='2024-01-01',target_note_key='N1',selection_source='test contract',confirmation_status='confirmed',reviewer='tester')
            csv_file(path,[row,dict(row,target_note_key='N2')])
            with self.assertRaises(PipelineError):targets({'ga_input':{'target_note_manifest':str(path)}},'mrn')

    def test_historical_text_is_not_reconstruction_failure(self):
        group=test_ga_validation.ValidationTests().group();group['reference_days']=['2024-02-01']
        note=v.candidate(group)
        self.assertEqual(note['reconstruction_status'],'pending_human_confirmation')
        self.assertEqual(note['anchor_linkage_status'],'off_anchor')
        self.assertEqual(note['target_note_status'],'not_target')
        self.assertIn('MoCA',note['text'])
        self.assertTrue(note['hard_blocks'])  # excluded from target extraction, not destroyed

    def test_schema_registry_no_inferred_interpretation(self):
        fields={f['field_path']:f for f in registry()}
        self.assertEqual(fields['cognition.moca.value']['domain'],'moca')
        self.assertEqual(fields['cognition.moca.interpretation']['support_status'],'not_supported')
        self.assertEqual(fields['psychological.gds15.value']['support_status'],'not_supported')
        self.assertIn('physical_function.adl.bathing',fields)
        self.assertIn('social_support.has_caregiver',fields)

    def test_approved_master_prepare_run_without_demographics(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);book=Workbook()
            for row in [['PAT_MRN_ID','NOTE_CSN_ID','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor'],
                        ['000TEST','N1',1,'2024-01-01','MoCA 15/30','No']]:book.active.append(row)
            book.save(root/'Notes.xlsx')
            csv_file(root/'master.csv',[self.master_row()])
            csv_file(root/'target.csv',[dict(patient_key='000TEST',patient_key_type='mrn',anchor_date='2024-01-01',target_note_key='N1',selection_source='test contract',confirmation_status='confirmed',reviewer='tester'),
                                      dict(patient_key='ABSENT_TEST',patient_key_type='mrn',anchor_date='2024-01-01',target_note_key='N2',selection_source='test contract',confirmation_status='confirmed',reviewer='tester')])
            cfg={'excel_date_min':20000,'excel_date_max':80000,'dayfirst':False,'notes':{'note_key_fields':['note_csn'],'note_key_verified':False},
                 'ga_validation':{'sample_size':8,'field_registry':'erika_draft'},
                 'ga_input':{'anchor_source':'approved_master','cohort_anchor_file':str(root/'master.csv'),'target_note_manifest':str(root/'target.csv')}}
            out=root/'review';v.prepare(root,out,cfg,'mrn')
            manifest=v.table(out/'sample_manifest.csv');self.assertEqual(len(manifest),1)
            note=v.read(out/'candidates'/(manifest[0]['internal_note_id']+'.json'))
            self.assertEqual(note['target_note_status'],'confirmed_by_manifest')
            self.assertEqual(note['anchor_linkage_status'],'matched')
            audit=v.table(out/'prepare_audit'/'ga_target_manifest_audit_SERDA_ONLY.csv')
            self.assertEqual({r['link_status'] for r in audit},{'matched','missing_document'})
            for k in ['identity_approved','reconstruction_approved','target_ga_approved']:manifest[0][k]='yes'
            manifest[0]['reviewer']='tester';v.write_table(out/'sample_manifest.csv',manifest,v.MANIFEST)
            v.run(out)
            predictions={r['field_path']:r for r in v.table(out/'baseline'/'predictions.csv')}
            self.assertEqual(predictions['cognition.moca.value']['predicted_value'],'15')
            self.assertEqual(predictions['cognition.moca.max']['predicted_value'],'30')
            self.assertEqual(predictions['physical_function.adl.bathing']['extraction_status'],'not_supported')
            self.assertEqual(len(predictions),len(registry()))
            v.evaluate(out)
            self.assertTrue((out/'baseline'/'ga_extraction_results.json').exists())
            self.assertNotIn('demographics',v.read(out/'run_manifest.json')['input_sha256'])
