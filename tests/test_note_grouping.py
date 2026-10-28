"""Small software fixtures only; no SERDA data or clinical performance claims."""
import csv
import io
import json
import sqlite3
import unittest
from contextlib import redirect_stdout, closing
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook
from serda_pipeline import ga_extraction as ga, ga_validation as validation
from serda_pipeline import notes, mrn_audit
from serda_pipeline.core import Report, PipelineError


class GroupingAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'source';self.root.mkdir()
        self.out=Path(self.temp.name)/'out';self.out.mkdir()
        self.headers=['PAT_ID','PAT_MRN_ID','NOTE_ID','NOTE_CSN','LINE','NOTE_CONTACT_DATE','NOTE_TEXT','Anchor','NOTE_TYPE','DEPARTMENT_NAME']
        self.config={'excel_date_min':20000,'excel_date_max':80000,'dayfirst':False,
                     'notes':{'note_key_fields':['note_csn'],'note_key_verified':False}}

    def row(self, pat='PAT_TEST_A',mrn='MRN_TEST_A',note='NOTE_TEST',csn='CSN_TEST',line=1,text='Geriatric components MoCA 15/30',department='SERVICE_TEST'):
        return [pat,mrn,note,csn,line,'2024-01-02',text,'Yes','Progress Note',department]

    def workbooks(self,rows,drop=None):
        demo=Workbook();demo.active.append(['PAT_ID','PAT_MRN_ID','CONTACT_DATE'])
        for p,m in sorted({(r[0],r[1]) for r in rows if r[0] and r[1]}): demo.active.append([p,m,'2024-01-02'])
        demo.save(self.root/'Frailty Demographics.xlsx');demo.close()
        book=Workbook()
        indexes=[i for i,h in enumerate(self.headers) if h not in (drop or [])]
        book.active.append([self.headers[i] for i in indexes])
        for r in rows: book.active.append([r[i] for i in indexes])
        book.save(self.root/'Notes.xlsx');book.close()

    def execute(self,key='mrn',callback=True):
        groups=[];console=io.StringIO()
        with redirect_stdout(console):
            ga.run(self.root,self.out,self.config,key,review_callback=groups.append if callback else None)
        self.assertNotIn('MRN_TEST_A',console.getvalue())
        self.assertNotIn('PAT_TEST_A',console.getvalue())
        return groups

    def table(self,name):
        with (self.out/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

    def stats(self):return {r['metric']:r for r in self.table('ga_note_grouping_summary.csv')}

    def test_explicit_csn_preserves_contacts_and_equal_partitions(self):
        self.workbooks([self.row(csn='CONTACT_A'),self.row(csn='CONTACT_B')])
        groups=self.execute()
        self.assertEqual(len(groups),2)  # NOTE_ID present does not take precedence.
        self.assertEqual(self.stats()['note_id_groups_with_multiple_csns']['count'],'1')
        self.assertEqual(self.stats()['same_partition_on_all_source_rows']['count'],'1')
        schema=json.loads((self.out/'ga_linkage_schema.json').read_text())
        self.assertEqual(schema['note_reconstruction']['source_columns'],['NOTE_CSN'])
        self.assertEqual(schema['patient_linkage']['source_column'],'PAT_MRN_ID')
        self.assertEqual(schema['cross_patient_consistency']['pat_id_column'],'PAT_ID')

    def test_serda_aliases_work_without_column_overrides(self):
        self.headers[3]='NOTE_CSN_ID'
        self.headers[9]='SERVICE_NAME'
        self.workbooks([self.row()])
        self.assertEqual(len(self.execute()),1)
        schema=json.loads((self.out/'ga_linkage_schema.json').read_text())
        self.assertEqual(schema['note_reconstruction']['source_columns'],['NOTE_CSN_ID'])
        self.assertEqual(schema['note_reconstruction']['status'],'explicit_candidate_key')
        self.assertEqual(schema['department_column'],'SERVICE_NAME')
        self.assertEqual(mrn_audit._discover(self.headers,'notes',self.config)['note_fields']['note_csn'],3)
        with closing(sqlite3.connect(':memory:')) as db:
            stats,_,_,_=notes.ingest(db,self.root,self.config,Report(),self.out)
            self.assertEqual(stats['column_mapping']['note_csn'],'NOTE_CSN_ID')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM fragments WHERE key IS NOT NULL').fetchone()[0],1)

    def test_alias_collisions_require_explicit_mapping(self):
        headers=['NOTE_CSN','NOTE_CSN_ID']
        _,mapping,ambiguous,_=notes.schema_mapping(headers,{})
        self.assertNotIn('note_csn',mapping)
        self.assertIn('note_csn',ambiguous)
        self.assertIsNone(mrn_audit._discover(headers,'notes',{})['note_fields']['note_csn'])
        config={'columns':{'notes':{'note_csn':'NOTE_CSN_ID'}}}
        self.assertEqual(notes.schema_mapping(headers,config)[1]['note_csn'],1)
        self.assertEqual(mrn_audit._discover(headers,'notes',config)['note_fields']['note_csn'],1)
        self.headers.append('SERVICE_NAME')
        self.workbooks([self.row()+['SERVICE_TEST']])
        with self.assertRaises(PipelineError): self.execute()
        self.config['columns']={'notes':{'department':'SERVICE_NAME'}}
        self.assertEqual(len(self.execute()),1)

    def test_no_implicit_note_id_fallback_or_empty_key_group(self):
        self.config['notes']['note_key_fields']=[]
        self.workbooks([self.row()])
        self.assertEqual(self.execute(),[])
        self.assertEqual(len(self.table('ga_ungroupable_fragments_SERDA_ONLY.csv')),1)
        self.assertEqual(self.stats()['note_csn_groups']['count'],'1')
        with closing(sqlite3.connect(':memory:')) as db:
            notes.ingest(db,self.root,self.config,Report(),self.out)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM fragments WHERE key IS NOT NULL').fetchone()[0],0)
        with closing(sqlite3.connect(':memory:')) as db:
            mrn_audit._stage(db)
            stats=mrn_audit._read_dataset(db,self.root,'notes',self.config,Report())
            self.assertFalse(stats['candidate_note_key_available'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit_rows WHERE note_key IS NOT NULL').fetchone()[0],0)

    def test_global_conflict_blocks_composite_subgroups_and_validation(self):
        self.config['notes']['note_key_fields']=['patient','note_csn']
        self.workbooks([self.row(),self.row(pat='PAT_TEST_B',mrn='MRN_TEST_B')])
        groups=self.execute()
        self.assertEqual(len(groups),2)
        for g in groups:
            self.assertIn('global_csn_multiple_mrns',g['reasons'])
            self.assertIn('global_csn_multiple_pat_ids',g['reasons'])
            self.assertTrue(validation.candidate(g)['hard_blocks'])
        self.assertEqual(self.stats()['note_csn_groups']['count'],'1')
        self.assertEqual(self.stats()['mrn_note_csn_groups_complete_ids']['count'],'2')
        self.assertEqual(self.stats()['same_partition_on_all_source_rows']['count'],'0')
        self.assertTrue(all(r['hard_blocks'] for r in self.table('ga_note_grouping_detail_SERDA_ONLY.csv')))
        self.config['notes']['note_key_verified']=True
        self.execute(callback=False)
        self.assertEqual(self.table('ga_extracted_scores.csv'),[])
        self.assertTrue(all(r['selection_status']=='excluded_reconstruction' for r in self.table('ga_note_selection_audit.csv')))

    def test_configured_csn_absent_does_not_fall_back_to_present_note_id(self):
        self.workbooks([self.row()],drop=['NOTE_CSN'])
        self.assertEqual(self.execute(),[])
        schema=json.loads((self.out/'ga_linkage_schema.json').read_text())
        self.assertEqual(schema['note_reconstruction']['status'],'configured_key_unavailable')
        self.assertEqual(schema['note_reconstruction']['unavailable_key_fields'],['note_csn'])
        self.assertEqual(self.stats()['note_csn_groups']['count'],'')

    def test_explicit_record_key_spanning_contacts_requires_investigation(self):
        self.config['notes']['note_key_fields']=['note_id']
        self.workbooks([self.row(csn='CONTACT_A'),self.row(csn='CONTACT_B',line=2,text='second contact')])
        group=self.execute()[0]
        self.assertIn('conflicting_note_csn',group['reasons'])
        self.assertTrue(validation.candidate(group)['hard_blocks'])

    def test_metadata_composite_cannot_hide_csn_date_disagreement(self):
        self.config['notes']['note_key_fields']=['note_csn','date']
        row=self.row();row[5]='2024-01-03'
        self.workbooks([self.row(),row])
        groups=self.execute()
        self.assertEqual(len(groups),2)
        self.assertTrue(all('global_csn_multiple_note_dates' in g['reasons'] for g in groups))

    def test_missing_identifiers_preserved_in_member_audit(self):
        self.workbooks([self.row(),self.row(mrn=None,line=2,text='second fragment'),self.row(csn=None)])
        self.execute()
        stats=self.stats()
        self.assertEqual(stats['rows_with_csn_missing_mrn']['count'],'1')
        self.assertEqual(stats['rows_missing_note_csn']['count'],'1')
        self.assertEqual(stats['same_partition_on_complete_id_rows']['count'],'1')
        self.assertEqual(stats['same_partition_on_all_source_rows']['count'],'0')
        self.assertEqual(len(self.table('ga_note_grouping_members_SERDA_ONLY.csv')),3)

    def test_absent_mrn_is_unavailable_not_zero_or_equality(self):
        self.workbooks([self.row()],drop=['PAT_MRN_ID'])
        self.execute('pat_id')
        self.assertEqual(self.stats()['mrn_note_csn_groups_complete_ids']['count'],'')
        self.assertIn('unavailable',self.stats()['same_partition_on_all_source_rows']['status'])

    def test_department_missing_and_disagreement_are_distinct_review_evidence(self):
        self.workbooks([self.row(department=None),self.row(line=2,text='second fragment',department='SERVICE_TEST')])
        group=self.execute()[0]
        self.assertNotIn('conflicting_department',group['manual_review'])
        self.assertIn('missing_department_rows',group['warnings'])
        self.assertEqual(group['metadata']['department']['missing_rows'],1)
        self.assertFalse(validation.candidate(group)['hard_blocks'])
        self.workbooks([self.row(department='SERVICE_A'),self.row(line=2,text='second fragment',department='SERVICE_B')])
        group=self.execute()[0]
        self.assertIn('conflicting_department',group['manual_review'])
        self.assertNotIn('conflicting_department',group['reasons'])
        candidate=validation.candidate(group)
        self.assertFalse(candidate['hard_blocks'])
        self.assertIn('conflicting_department',candidate['reconstruction_warnings'])
        self.assertEqual(candidate['metadata_evidence']['department']['nonempty_values'],['SERVICE_A','SERVICE_B'])

    def test_sorted_reconstruction_retains_duplicate_source_rows_and_offsets(self):
        self.workbooks([self.row(line=3,text='third'),self.row(line=1,text='Geriatric components'),
                        self.row(line=2,text='MoCA 15/30'),self.row(line=2,text='MoCA 15/30')])
        group=self.execute()[0]
        candidate=validation.candidate(group)
        self.assertFalse(candidate['hard_blocks'])
        self.assertEqual(candidate['text'],'Geriatric components\nMoCA 15/30\nthird')
        self.assertIn('source_order_sorted_by_line',candidate['reconstruction_warnings'])
        self.assertNotIn('source_order_sorted_by_line',group['manual_review'])
        self.assertEqual(len(candidate['source_rows']),4)
        for r in candidate['source_rows']:
            self.assertEqual(candidate['text'][r['text_start']:r['text_end']],r['original_text'])
        self.assertEqual([r['source_excel_row'] for r in candidate['source_rows']],[3,4,5,2])

    def test_conflicting_line_text_stays_hard_blocked(self):
        self.workbooks([self.row(text='version one'),self.row(text='version two')])
        candidate=validation.candidate(self.execute()[0])
        self.assertIn('conflicting_line_text',candidate['hard_blocks'])
        self.assertEqual(candidate['text'],'')

    def test_csn_with_multiple_note_ids_blocks_even_note_id_subgroups(self):
        self.config['notes']['note_key_fields']=['note_id']
        self.workbooks([self.row(note='NOTE_A'),self.row(note='NOTE_B')])
        groups=self.execute()
        self.assertEqual(len(groups),2)
        self.assertTrue(all('global_csn_multiple_note_ids' in g['reasons'] for g in groups))
        self.assertEqual(self.stats()['csn_groups_with_multiple_note_ids']['count'],'1')

    def test_reverse_moca_pattern_remains_unsupported_baseline(self):
        rows,_=ga.extract_text('15/30 on MoCA')
        self.assertEqual(rows[0][3],'unsupported_format')
        self.assertIsNone(rows[0][1])

if __name__=='__main__':unittest.main()
