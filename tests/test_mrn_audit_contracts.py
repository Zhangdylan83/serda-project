"""Header-only MRN audit checks; no clinical records or identifiers are fabricated."""
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
from contextlib import redirect_stdout, redirect_stderr
import io
import unittest
from unittest.mock import patch

from openpyxl import Workbook
import yaml

from serda_pipeline.core import Report
from serda_pipeline.mrn_audit import DATASETS, _clean_mrn, _discover, audit_mrn
from serda_pipeline.schema import STEMS, SCHEMAS, REQUIRED
import run_pipeline


class MRNAuditContracts(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.source=root/'source';self.source.mkdir()
        self.out=root/'results';self.out.mkdir()
        self.config=yaml.safe_load(Path('config.yaml').read_text())
        self.report=Report()

    def headers_only(self,dataset,headers):
        stem='Notes' if dataset=='notes' else STEMS[dataset]
        book=Workbook();book.active.append(headers)
        book.save(self.source/(stem+'.xlsx'));book.close()

    def test_mrn_text_preserves_leading_zeros_and_rejects_numeric_cells(self):
        self.assertEqual(_clean_mrn(' 00E01 ')[0],'00E01')
        self.assertEqual(_clean_mrn('E0001')[0],'E0001')
        self.assertIsNone(_clean_mrn(123)[0])
        self.assertEqual(_clean_mrn(123)[1],'numeric_or_nontext_cell')

    def test_preferred_field_and_conflicting_header_rejection(self):
        mapped=_discover(['PAT_ID','MRN','PAT_MRN_ID','CONTACT_DATE'],'demographics',self.config)
        self.assertEqual(mapped['headers'][mapped['mrn']],'PAT_MRN_ID')
        self.assertEqual(mapped['alternatives'],[1])
        config={**self.config,'columns':{'demographics':{'mrn':'MRN'}}}
        self.assertEqual(_discover(['PAT_ID','MRN'],'demographics',config)['mrn'],1)
        config['columns']['demographics']['mrn']='PAT_ID'
        self.assertIsNone(_discover(['PAT_ID','MRN'],'demographics',config)['mrn'])

    def test_notes_only_reports_other_six_unavailable(self):
        self.headers_only('demographics',['PAT_ID','PAT_MRN_ID','CONTACT_DATE'])
        self.headers_only('notes',['PAT_ID','PAT_MRN_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','Anchor'])
        audit_mrn(self.source,self.config,self.report,self.out,notes_only=True)
        self.assertEqual(self.report.data['failed_modules'],[])
        with (self.out/'mrn_dataset_inventory.csv').open() as handle:rows=list(csv.DictReader(handle))
        self.assertEqual(len(rows),8)
        self.assertEqual(rows[0]['dataset'],'demographics')
        self.assertEqual(rows[-1]['dataset'],'notes')
        self.assertEqual(rows[1]['status'],'dataset_unavailable')
        self.assertTrue(all(None not in row for row in rows))
        self.assertTrue((self.out/'mrn_anchor_alignment_summary.csv').exists())
        self.assertTrue((self.out/'mrn_patient_mapping_detail_SERDA_ONLY.csv').exists())
        self.assertFalse(list(self.out.glob('.mrn-stage-*')))

    def test_all_eight_header_only_scans_and_exports(self):
        for dataset in DATASETS:
            if dataset=='notes':headers=['PAT_ID','PAT_MRN_ID','NOTE_CONTACT_DATE','Anchor']
            else:
                field='anchor' if dataset=='demographics' else 'date'
                headers=['PAT_ID','PAT_MRN_ID',SCHEMAS[dataset][field][0]]
            self.headers_only(dataset,headers)
        audit_mrn(self.source,self.config,self.report,self.out)
        self.assertEqual(self.report.data['failed_modules'],[])
        self.assertIn('mrn_intersections',self.report.data['completed_modules'])
        for filename in ['mrn_schema_validation.csv','mrn_patient_mapping_audit.csv','mrn_dataset_inventory.csv',
                         'mrn_patient_intersections.csv','mrn_coverage_comparison.csv',
                         'mrn_anchor_alignment_summary.csv','mrn_multiple_anchor_summary.csv',
                         'mrn_vs_pat_id_comparison.csv','mrn_pairwise_intersections.csv']:
            self.assertTrue((self.out/filename).exists(),filename)
        with (self.out/'mrn_coverage_comparison.csv').open() as handle:coverage=list(csv.DictReader(handle))
        self.assertEqual(coverage[-1]['scope'],'all_eight')
        for filename in ['mrn_schema_validation.csv','mrn_patient_mapping_audit.csv',
                         'mrn_dataset_inventory.csv','mrn_patient_intersections.csv',
                         'mrn_vs_pat_id_comparison.csv','mrn_pairwise_intersections.csv']:
            with (self.out/filename).open() as handle:
                self.assertTrue(all(None not in row for row in csv.DictReader(handle)),filename)

    def test_notes_only_cli_writes_dedicated_mrn_summary_without_clinical_rows(self):
        self.headers_only('demographics',['PAT_ID','PAT_MRN_ID','CONTACT_DATE'])
        self.headers_only('notes',['PAT_ID','PAT_MRN_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor'])
        args=['run_pipeline.py','--data-dir',str(self.source),'--output-dir',str(self.out/'new'),
              '--patient-key','mrn','--notes-audit-only']
        with patch('sys.argv',args),redirect_stdout(io.StringIO()):
            code=run_pipeline.main()
        self.assertEqual(code,0)
        summary=(self.out/'new'/'Data_Audit_Summary.md').read_text()
        self.assertIn('MRN-Based Patient Linkage Validation',summary)
        self.assertIn('No patient rows were observed',summary)
        self.assertFalse((self.out/'new'/'patient_features.csv').exists())

    def test_mrn_cli_refuses_to_overwrite_prior_audit_even_if_config_allows(self):
        prior=self.out/'prior';prior.mkdir()
        sentinel=prior/'patient_features.csv';sentinel.write_text('existing result')
        self.config['overwrite']=True
        config_path=self.out/'mrn_config.yaml';config_path.write_text(yaml.safe_dump(self.config))
        args=['run_pipeline.py','--data-dir',str(self.source),'--output-dir',str(prior),
              '--config',str(config_path),'--patient-key','mrn']
        with patch('sys.argv',args),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            run_pipeline.main()
        self.assertEqual(sentinel.read_text(),'existing result')

    def test_full_cli_scans_eight_after_structured_cohort_stops(self):
        for dataset in DATASETS:
            if dataset=='notes':
                headers=['PAT_ID','PAT_MRN_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor']
            else:
                fields=['PAT_ID','PAT_MRN_ID']
                fields += [SCHEMAS[dataset][field][0] for field in REQUIRED[dataset]
                           if field!='patient']
                headers=list(dict.fromkeys(fields))
            self.headers_only(dataset,headers)
        target=self.out/'full'
        args=['run_pipeline.py','--data-dir',str(self.source),'--output-dir',str(target),
              '--patient-key','mrn']
        with patch('sys.argv',args),redirect_stdout(io.StringIO()):
            code=run_pipeline.main()
        self.assertEqual(code,2)  # Empty Demographics cannot establish a clinical cohort.
        with (target/'mrn_dataset_inventory.csv').open() as handle:rows=list(csv.DictReader(handle))
        self.assertEqual(len(rows),8)
        self.assertEqual({row['dataset'] for row in rows},set(DATASETS))
        with (target/'execution_report.json').open() as handle:report=__import__('json').load(handle)
        self.assertIn('mrn_intersections',report['completed_modules'])
        self.assertIn('cohort_analysis',[row['module'] for row in report['failed_modules']])

    def test_missing_mrn_header_is_unavailable_not_zero(self):
        self.headers_only('demographics',['PAT_ID','CONTACT_DATE'])
        self.headers_only('notes',['PAT_ID','NOTE_CONTACT_DATE','Anchor'])
        audit_mrn(self.source,self.config,self.report,self.out,notes_only=True)
        self.assertEqual(self.report.data['failed_modules'],[])
        with (self.out/'mrn_dataset_inventory.csv').open() as handle: rows=list(csv.DictReader(handle))
        self.assertEqual(rows[0]['unique_mrns'],'')
        self.assertEqual(rows[-1]['unique_mrns'],'')
        with (self.out/'mrn_patient_intersections.csv').open() as handle: rows=list(csv.DictReader(handle))
        self.assertEqual(rows[0]['mrn_overlap_demographics'],'')


if __name__=='__main__':unittest.main()
