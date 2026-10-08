"""Notes contracts tested with header-only workbooks and no clinical records.

No synthetic patients, notes, or clinical results are used as validation.
"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import Workbook
import pandas as pd
import yaml

from serda_pipeline import notes
from serda_pipeline.core import PipelineError, Report
import run_pipeline


class NotesContracts(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'source'
        self.root.mkdir()
        self.out=Path(self.temp.name)/'output'
        self.out.mkdir()
        (self.out/'figures').mkdir()
        self.config=yaml.safe_load(Path('config.yaml').read_text())
        self.report=Report()

    def header_workbook(self, headers):
        book=Workbook()
        book.active.append(headers)
        book.save(self.root/'Notes.xlsx')
        book.close()

    def test_original_missing_conventions_and_text_preservation(self):
        for value in [None,'','  ','NULL','null','(null)','None']:
            self.assertIsNone(notes.missing_value(value))
        self.assertEqual(notes.missing_value('NA'),'NA')
        self.assertEqual(notes.missing_value('  text\n'),'  text\n')
        self.assertEqual(notes.anchor_status(' YES '),'Yes')
        self.assertEqual(notes.anchor_status('true'),'Other')

    def test_identifiers_and_integer_line_validation(self):
        self.assertIsNone(notes.identifier('123.0'))
        self.assertIsNone(notes.identifier('1e3'))
        self.assertEqual(notes.identifier(' 00123 '),'00123')
        self.assertEqual(notes.line_number('1.0'),1)
        self.assertIsNone(notes.line_number('1.5'))
        self.assertIsNone(notes.line_number('9'*100))

    def test_ordinal_gaps_conflicts_duplicates_and_source_order(self):
        # Abstract ordinals/cardinalities only; no note text or patient fixtures.
        quality=notes.line_quality({1:2,2:1,3:1},[1,1,3,2],4,1)
        self.assertEqual(quality['duplicate_line_rows'],1)
        self.assertEqual(quality['conflicting_lines'],1)
        self.assertTrue(quality['out_of_order'])
        self.assertEqual(quality['missing_line_positions'],0)
        quality=notes.line_quality({2:1,4:1},[2,4],2,1)
        self.assertEqual(quality['missing_line_positions'],2)
        self.assertTrue(quality['unexpected_first_line'])
        self.assertEqual(notes.line_quality({0:1,1:1},[0,1],2,0)['missing_line_positions'],0)
        self.assertTrue(notes.line_quality({},[],0,1)['no_valid_lines'])

    def test_schema_discovery_and_override_without_note_csn_assumption(self):
        headers=['NOTE_TYPE','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor']
        _,mapping,ambiguous,absent=notes.schema_mapping(headers,self.config)
        self.assertNotIn('patient',mapping)
        self.assertNotIn('encounter',mapping)
        self.assertIn('note_csn',mapping)
        self.assertIn('patient',absent)
        self.assertEqual(ambiguous,[])
        config={**self.config,'columns':{'notes':{'encounter':'NOTE_CSN'}}}
        _,mapping,_,_=notes.schema_mapping(headers,config)
        self.assertIn('encounter',mapping)
        self.assertFalse(config['notes']['encounter_linkage_verified'])
        with self.assertRaises(PipelineError): notes.schema_mapping(['LINE','line'],self.config)
        with self.assertRaises(PipelineError): notes.schema_mapping(['LINE',None],self.config)

    def test_verified_identity_requires_explicit_keys(self):
        config={**self.config,'notes':{'note_key_verified':True}}
        with self.assertRaises(PipelineError): notes.validate_settings(config)
        config['notes']['note_key_fields']=['text']
        with self.assertRaises(PipelineError): notes.validate_settings(config)

    def test_header_only_ingestion_and_reconstruction_outputs(self):
        self.header_workbook(['PAT_ID','NOTE_TYPE','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor'])
        demo=pd.DataFrame({'patient':pd.Series(dtype=str),'anchor':pd.Series(dtype='datetime64[ns]')})
        with patch.object(notes,'plot'):
            notes.audit_notes(self.root,self.config,self.report,self.out,demo)
        self.assertEqual(self.report.data['failed_modules'],[])
        stats=self.report.data['datasets']['notes']
        self.assertEqual(stats['row_count'],0)
        self.assertEqual(stats['duplicate_rows'],0)
        self.assertIsNone(stats['unique_reconstructed_notes'])
        self.assertFalse(stats['note_identity_verified_by_local_configuration'])
        self.assertIn('notes_reconstruction',[i['module'] for i in self.report.data['skipped_modules']])
        for filename in notes.DELIVERABLES: self.assertTrue((self.out/filename).exists(),filename)
        self.assertEqual(list(self.out.glob('.notes-stage-*')),[])
        self.assertFalse((self.out/'notes_reconstructed_text_SERDA_only.jsonl').exists())
        alignment=pd.read_csv(self.out/'notes_anchor_alignment_summary.csv').set_index('metric')
        self.assertEqual(str(alignment.loc['distinct_anchor_yes_notes','count']),'nan')

    def test_absent_linkage_is_explicit_without_guessing(self):
        self.header_workbook(['NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor'])
        with patch.object(notes,'plot'):
            notes.audit_notes(self.root,self.config,self.report,self.out)
        stats=self.report.data['datasets']['notes']
        self.assertFalse(stats['patient_linkage_available'])
        self.assertIsNone(stats['unique_patients'])
        self.assertIn('notes_anchor_alignment',[i['module'] for i in self.report.data['skipped_modules']])

    def test_missing_anchor_field_preserves_patient_coverage_but_withholds_alignment(self):
        self.header_workbook(['PAT_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT'])
        demo=pd.DataFrame({'patient':pd.Series(dtype=str),'anchor':pd.Series(dtype='datetime64[ns]')})
        with patch.object(notes,'plot'): notes.audit_notes(self.root,self.config,self.report,self.out,demo)
        self.assertIn('notes_patient_intersections',self.report.data['completed_modules'])
        self.assertIn('notes_anchor_alignment',[i['module'] for i in self.report.data['skipped_modules']])
        intersections=pd.read_csv(self.out/'notes_patient_intersections.csv').set_index('metric')
        self.assertTrue(pd.isna(intersections.loc['demographics_patients_with_anchor_yes_rows','count']))

    def test_verified_header_only_note_identity_path(self):
        self.header_workbook(['PAT_ID','NOTE_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor'])
        self.config['notes']['note_key_fields']=['note_id']
        self.config['notes']['note_key_verified']=True
        with patch.object(notes,'plot'): notes.audit_notes(self.root,self.config,self.report,self.out)
        self.assertEqual(self.report.data['failed_modules'],[])
        self.assertIn('notes_reconstruction',self.report.data['completed_modules'])
        self.assertEqual(self.report.data['datasets']['notes']['unique_reconstructed_notes'],0)

    def test_notes_failure_leaves_existing_structured_artifacts_intact(self):
        sentinel=self.out/'patient_features.csv'
        sentinel.write_text('PAT_ID,anchor\n')
        inventory=self.out/'dataset_inventory.csv'
        inventory.write_text('dataset,row_count\ndemographics,0\n')
        before=inventory.read_bytes()
        notes.audit_notes(self.root,self.config,self.report,self.out)
        self.assertEqual(inventory.read_bytes(),before)
        self.assertEqual(sentinel.read_text(),'PAT_ID,anchor\n')
        self.assertEqual(self.report.data['failed_modules'][0]['module'],'notes_audit')
        for filename in notes.DELIVERABLES: self.assertTrue((self.out/filename).exists())

    def test_integration_preserves_structured_inventory_and_intersections(self):
        self.header_workbook(['PAT_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor'])
        pd.DataFrame([{'dataset':'demographics','row_count':0,'unique_patients':0}]).to_csv(self.out/'dataset_inventory.csv',index=False)
        pd.DataFrame([{'dataset':'demographics','source_patients':0}]).to_csv(self.out/'patient_set_intersections.csv',index=False)
        demo=pd.DataFrame({'patient':pd.Series(dtype=str),'anchor':pd.Series(dtype='datetime64[ns]')})
        with patch.object(notes,'plot'): notes.audit_notes(self.root,self.config,self.report,self.out,demo)
        inventory=pd.read_csv(self.out/'dataset_inventory.csv')
        self.assertEqual(inventory.dataset.tolist(),['demographics','notes'])
        self.assertEqual(inventory.row_count.tolist(),[0,0])
        intersections=pd.read_csv(self.out/'patient_set_intersections.csv')
        self.assertEqual(intersections.dataset.tolist(),['demographics','notes'])

    def load_empty_demographics(self, root, config, report):
        report.data['datasets']['demographics']={'row_count':0,'unique_patients':0,
            'duplicate_rows':0,'missing_patient_ids':0,'missingness':{}}
        return pd.DataFrame({'patient':pd.Series(dtype=str),'anchor':pd.Series(dtype='datetime64[ns]')})

    def test_notes_only_does_not_call_cohort_or_clinical_analysis(self):
        (self.out/'figures').rmdir()
        self.header_workbook(['PAT_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor'])
        config={**self.config,'lookback_days':-1}
        config_path=Path(self.temp.name)/'config.yaml'
        config_path.write_text(yaml.safe_dump(config))
        argv=['run_pipeline.py','--data-dir',str(self.root),'--output-dir',str(self.out),
              '--config',str(config_path),'--notes-audit-only']
        with patch('sys.argv',argv), patch('serda_pipeline.core.load_demographics',side_effect=self.load_empty_demographics), \
                patch('serda_pipeline.analysis.execute') as execute, patch.object(notes,'plot'), redirect_stdout(io.StringIO()):
            result=run_pipeline.main()
        execute.assert_not_called()
        self.assertEqual(result,0)
        self.assertFalse((self.out/'patient_features.csv').exists())
        self.assertTrue((self.out/'Data_Audit_Summary.md').exists())

    def test_notes_runs_after_strict_cohort_rejection(self):
        (self.out/'figures').rmdir()
        self.header_workbook(['PAT_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor'])
        argv=['run_pipeline.py','--data-dir',str(self.root),'--output-dir',str(self.out)]
        with patch('sys.argv',argv), patch('serda_pipeline.core.load_demographics',side_effect=self.load_empty_demographics), \
                patch('serda_pipeline.core.load_dataset',side_effect=PipelineError('Unavailable test workbook')), \
                patch('serda_pipeline.analysis.execute',side_effect=PipelineError('Multiple demographic anchors')), \
                patch.object(notes,'plot'), redirect_stdout(io.StringIO()):
            result=run_pipeline.main()
        self.assertEqual(result,2)
        report=json.loads((self.out/'execution_report.json').read_text())
        self.assertIn('notes_inventory',report['completed_modules'])
        self.assertIn('cohort_analysis',[x['module'] for x in report['failed_modules']])


if __name__=='__main__': unittest.main()
