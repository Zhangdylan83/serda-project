"""Tiny synthetic identifier fixtures for software contracts, not clinical results."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook
from serda_pipeline import patient_coverage as c
from serda_pipeline.schema import STEMS


def sheet(path,headers,rows):
    book=Workbook();book.active.append(headers)
    for row in rows:book.active.append(row)
    book.save(path)


def table(path):
    with path.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))


def fixture(root):
    source=root/'source';source.mkdir();config=root/'config.yaml';config.write_text('{}')
    for d in c.DATASETS:
        name='Notes' if d=='notes' else STEMS[d]
        rows=[['TEST_PAT_A','000TEST_A'],['TEST_PAT_B','TEST_B']]
        if d=='demographics':rows=rows[:1]
        sheet(source/(name+'.xlsx'),['PAT_ID','PAT_MRN_ID'],rows)
    return source,config


class CoverageTests(unittest.TestCase):
    def test_union_not_demographics_and_aggregate_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,config=fixture(root);out=root/'audit'
            with patch('serda_pipeline.analysis.execute',side_effect=AssertionError('No clinical EDA')),patch('serda_pipeline.ga_extraction.run',side_effect=AssertionError('No GA')):
                self.assertTrue(c.run(source,out,config))
            rows={r['dataset']:r for r in table(out/'aggregate'/'patient_coverage_summary.csv')}
            self.assertEqual(rows['demographics']['coverage_pct'],'50.0')
            self.assertEqual(rows['demographics']['reference_mrns_absent_from_dataset'],'1')
            self.assertEqual(rows['medications']['unique_valid_mrns'],'2') # No date or medication columns needed
            totals={r['metric']:r['count'] for r in table(out/'aggregate'/'union_intersection_summary.csv')}
            self.assertEqual(totals['eight_table_union_mrns'],'2');self.assertEqual(totals['eight_table_intersection_mrns'],'1')
            pair={r['dataset']:r for r in table(out/'aggregate'/'pairwise_overlap_matrix.csv')}
            self.assertEqual(pair['notes']['demographics'],'1');self.assertEqual(pair['notes']['notes'],'2')
            gaps=table(out/'aggregate'/'directional_patient_gaps.csv')
            self.assertEqual(next(r['patients'] for r in gaps if r['present_in']=='notes' and r['absent_from']=='demographics'),'1')
            for p in (out/'aggregate').iterdir():
                text=p.read_text();self.assertNotIn('000TEST_A',text);self.assertNotIn('TEST_PAT_A',text);self.assertNotIn('TEST_B',text)
            self.assertIn('TEST_B',(out/'restricted_SERDA_ONLY'/'observed_union_mrns_absent_from_dataset.csv').read_text())

    def test_missing_table_is_unknown_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,config=fixture(root);(source/'Notes.xlsx').unlink();out=root/'audit'
            self.assertFalse(c.run(source,out,config))
            rows={r['dataset']:r for r in table(out/'aggregate'/'patient_coverage_summary.csv')}
            self.assertEqual(rows['notes']['status'],'failed');self.assertEqual(rows['notes']['coverage_pct'],'')
            self.assertEqual(rows['labs']['reference_type'],'partial_observed_union_available_tables')
            matrix=table(out/'aggregate'/'pairwise_overlap_matrix.csv');self.assertTrue(all(r['notes']=='' for r in matrix))
            total={r['metric']:r['count'] for r in table(out/'aggregate'/'union_intersection_summary.csv')}
            self.assertEqual(total['eight_table_intersection_mrns'],'');self.assertEqual(total['eight_table_union_mrns'],'')

    def test_identifiers_and_row_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,config=fixture(root)
            sheet(source/'Notes.xlsx',['PAT_ID','PAT_MRN_ID','MRN'],[
                ['TEST_1','000TEST',None],['TEST_2',123,None],['TEST_3',None,None],
                ['TEST_4','TEST_A','TEST_B'],[None,None,None],['TEST_5',' TEST_C ',None]])
            out=root/'audit';self.assertTrue(c.run(source,out,config))
            row=next(r for r in table(out/'aggregate'/'patient_coverage_summary.csv') if r['dataset']=='notes')
            self.assertEqual(row['total_rows'],'6');self.assertEqual(row['unique_valid_mrns'],'2')
            self.assertEqual(row['missing_mrn_rows'],'2');self.assertEqual(row['invalid_nontext_mrn_rows'],'1')
            self.assertEqual(row['conflicting_mrn_columns_rows'],'1');self.assertEqual(row['unlinked_identifier_rows'],'4')
            self.assertEqual(row['trimmed_mrn_rows'],'1')

    def test_roster_independent_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,config=fixture(root);roster=root/'roster.csv'
            roster.write_text('mrn,eligible,confirmation_status,source,reviewer\nTEST_B,yes,confirmed,software fixture,tester\nTEST_OTHER,yes,confirmed,software fixture,tester\n')
            original={p.name:c.fingerprint(p) for p in source.iterdir()};out=root/'audit'
            self.assertTrue(c.run(source,out,config,roster))
            row=next(r for r in table(out/'aggregate'/'validated_roster_coverage.csv') if r['dataset']=='demographics')
            self.assertEqual(row['matched_mrns'],'0');self.assertEqual(row['roster_mrns_absent_from_dataset'],'2')
            self.assertEqual(original,{p.name:c.fingerprint(p) for p in source.iterdir()})
            with self.assertRaises(c.CoverageError):c.run(source,out,config)
            roster.write_text('mrn,eligible,confirmation_status,source,reviewer\nTEST_B,yes,pending,fixture,tester\n')
            with self.assertRaises(c.CoverageError):c.run(source,root/'other',config,roster)

    def test_missing_column_not_empty_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,config=fixture(root)
            sheet(source/'Notes.xlsx',['PAT_ID','NOTE_TEXT'],[['TEST_PAT','synthetic text never exported']])
            out=root/'audit';self.assertFalse(c.run(source,out,config))
            row=next(r for r in table(out/'aggregate'/'patient_coverage_summary.csv') if r['dataset']=='notes')
            self.assertEqual(row['status'],'linkage_unavailable');self.assertEqual(row['coverage_pct'],'')
            for p in out.rglob('*'):
                if p.is_file():self.assertNotIn('synthetic text never exported',p.read_text())
