"""Disk-backed grouping comparison; identifiers stay in SERDA-only detail files.

This audits partitions of source ROWS, not the clinical identity of documents.
No extra fields are added to the configured reconstruction key.
"""
import csv
from collections import Counter


def write_csv(path, fields, rows):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle); writer.writerow(fields); writer.writerows(rows)


def audit_grouping(db, output, available, source_file, source_sheet, header_row):
    """Requires the GA fragment stage, including direct pat_id/mrn columns.

    Global CSN conflicts are materialized BEFORE any custom/composite grouping;
    every subgroup touching an affected CSN must subsequently be blocked.
    """
    db.execute('CREATE INDEX IF NOT EXISTS ga_csn ON fragments(note_csn)')
    db.execute('''CREATE TEMP TABLE csn_groups AS SELECT note_csn, COUNT(*) AS rows,
        COUNT(DISTINCT mrn) AS mrns, COUNT(DISTINCT pat_id) AS pat_ids,
        COUNT(DISTINCT note_id) AS note_ids,
        SUM(mrn IS NULL) AS missing_mrn_rows,
        SUM(pat_id IS NULL) AS missing_pat_id_rows,
        SUM(mrn_status='conflicting_mrn_columns') AS conflicting_mrn_rows
        FROM fragments WHERE note_csn IS NOT NULL GROUP BY note_csn''')
    db.execute('CREATE UNIQUE INDEX csn_groups_key ON csn_groups(note_csn)')
    db.execute('CREATE TEMP TABLE blocked_csns (note_csn TEXT, reason TEXT)')
    for column, condition, reason in [
        ('mrns','>1','global_csn_multiple_mrns'),
        ('pat_ids','>1','global_csn_multiple_pat_ids'),
        ('note_ids','>1','global_csn_multiple_note_ids'),
        ('conflicting_mrn_rows','>0','global_csn_conflicting_mrn_columns')]:
        db.execute(f'INSERT INTO blocked_csns SELECT note_csn, ? FROM csn_groups WHERE {column}{condition}',(reason,))
    db.execute('CREATE INDEX blocked_csn_key ON blocked_csns(note_csn)')
    # Even an explicitly configured date/type composite must not hide metadata
    # differences within the underlying CSN. Dates block; descriptive fields review.
    db.execute('CREATE TEMP TABLE review_csns (note_csn TEXT, reason TEXT)')
    for field,reason in [('day','global_csn_multiple_note_dates'),('note_timestamp','global_csn_multiple_note_timestamps')]:
        db.execute(f'''INSERT INTO blocked_csns SELECT note_csn, ? FROM fragments
            WHERE note_csn IS NOT NULL GROUP BY note_csn HAVING COUNT(DISTINCT {field})>1''',(reason,))
    for field in ['note_type','author','encounter','department']:
        db.execute(f'''INSERT INTO review_csns SELECT note_csn, ? FROM fragments
            WHERE note_csn IS NOT NULL GROUP BY note_csn HAVING COUNT(DISTINCT {field})>1''',('global_csn_conflicting_'+field,))
    db.execute('CREATE INDEX review_csn_key ON review_csns(note_csn)')
    total = db.execute('SELECT COUNT(*) FROM fragments').fetchone()[0]
    counts = Counter()
    counts['source_rows'] = total
    counts['note_csn_groups'] = db.execute('SELECT COUNT(*) FROM csn_groups').fetchone()[0]
    counts['rows_missing_note_csn'] = db.execute('SELECT COUNT(*) FROM fragments WHERE note_csn IS NULL').fetchone()[0]
    counts['rows_with_csn_missing_mrn'] = db.execute('SELECT COUNT(*) FROM fragments WHERE note_csn IS NOT NULL AND mrn IS NULL').fetchone()[0]
    counts['mrn_note_csn_groups_complete_ids'] = db.execute('SELECT COUNT(*) FROM (SELECT mrn,note_csn FROM fragments WHERE mrn IS NOT NULL AND note_csn IS NOT NULL GROUP BY mrn,note_csn)').fetchone()[0]
    counts['csn_groups_on_complete_id_rows'] = db.execute('SELECT COUNT(*) FROM csn_groups WHERE mrns>0').fetchone()[0]
    counts['csn_groups_with_multiple_mrns'] = db.execute('SELECT COUNT(*) FROM csn_groups WHERE mrns>1').fetchone()[0]
    counts['csn_groups_with_multiple_pat_ids'] = db.execute('SELECT COUNT(*) FROM csn_groups WHERE pat_ids>1').fetchone()[0]
    counts['csn_groups_with_multiple_note_ids'] = db.execute('SELECT COUNT(*) FROM csn_groups WHERE note_ids>1').fetchone()[0]
    counts['note_id_groups_with_multiple_csns'] = db.execute('SELECT COUNT(*) FROM (SELECT note_id FROM fragments WHERE note_id IS NOT NULL GROUP BY note_id HAVING COUNT(DISTINCT note_csn)>1)').fetchone()[0]
    counts['csn_groups_changed_or_uncomparable'] = db.execute('SELECT COUNT(*) FROM csn_groups WHERE mrns!=1 OR missing_mrn_rows>0').fetchone()[0]
    counts['csn_groups_with_identical_complete_membership'] = db.execute('SELECT COUNT(*) FROM csn_groups WHERE mrns=1 AND missing_mrn_rows=0').fetchone()[0]
    counts['globally_blocked_csns'] = db.execute('SELECT COUNT(DISTINCT note_csn) FROM blocked_csns').fetchone()[0]
    counts['csn_groups_needing_metadata_review'] = db.execute('SELECT COUNT(DISTINCT note_csn) FROM review_csns').fetchone()[0]
    counts['rows_with_invalid_or_conflicting_mrn'] = db.execute("SELECT COUNT(*) FROM fragments WHERE mrn_status IN ('numeric_or_nontext_cell','conflicting_mrn_columns')").fetchone()[0]
    counts['pat_ids_mapping_to_multiple_mrns'] = db.execute('SELECT COUNT(*) FROM (SELECT pat_id FROM fragments WHERE pat_id IS NOT NULL GROUP BY pat_id HAVING COUNT(DISTINCT mrn)>1)').fetchone()[0]
    counts['mrns_mapping_to_multiple_pat_ids'] = db.execute('SELECT COUNT(*) FROM (SELECT mrn FROM fragments WHERE mrn IS NOT NULL GROUP BY mrn HAVING COUNT(DISTINCT pat_id)>1)').fetchone()[0]
    # Equality on complete rows is a separate statement from full export equality.
    counts['same_partition_on_complete_id_rows'] = int(counts['csn_groups_on_complete_id_rows']>0 and counts['csn_groups_with_multiple_mrns']==0)
    counts['same_partition_on_all_source_rows'] = int(total>0 and counts['rows_missing_note_csn']==0 and counts['csn_groups_changed_or_uncomparable']==0)
    rows=[]
    for name, count in counts.items():
        needed=[]
        if 'csn' in name or 'partition' in name: needed.append('note_csn')
        if 'mrn' in name or 'partition' in name or 'complete_id' in name or 'complete_membership' in name or 'uncomparable' in name: needed.append('mrn')
        if 'pat_id' in name: needed.append('pat_id')
        if 'note_id' in name: needed.append('note_id')
        missing=[field for field in needed if not available.get(field)]
        state='unavailable_columns:'+','.join(missing) if missing else 'no_rows' if total==0 else 'available'
        no_comparable = name=='same_partition_on_complete_id_rows' and counts['csn_groups_on_complete_id_rows']==0
        if not missing and no_comparable: state='no_complete_identifier_rows'
        rows.append([name,None if missing or no_comparable or (total==0 and 'partition' in name) else count,state])
    write_csv(output/'ga_note_grouping_summary.csv',['metric','count','status'],rows)
    detail=[]
    for csn,size,mrns,pats,notes,missing_mrn,missing_pat,conflicts in db.execute('SELECT * FROM csn_groups ORDER BY note_csn'):
        reasons=[r[0] for r in db.execute('SELECT reason FROM blocked_csns WHERE note_csn=?',(csn,))]
        state=('unavailable_mrn_column' if not available.get('mrn') else
               'split_and_missing_mrn_rows' if mrns>1 and missing_mrn else
               'split_by_mrn' if mrns>1 else 'incomplete_mrn_membership' if missing_mrn else 'same_membership')
        detail.append([csn,size,mrns if available.get('mrn') else None,pats if available.get('pat_id') else None,
                       notes if available.get('note_id') else None,missing_mrn if available.get('mrn') else None,
                       missing_pat if available.get('pat_id') else None,state,';'.join(reasons)])
    write_csv(output/'ga_note_grouping_detail_SERDA_ONLY.csv',
        ['NOTE_CSN','source_rows','distinct_mrns','distinct_pat_ids','distinct_note_ids','missing_mrn_rows','missing_pat_id_rows','partition_comparison','hard_blocks'],detail)
    # Includes ALL source rows so missing CSNs/MRNs cannot silently disappear.
    write_csv(output/'ga_note_grouping_members_SERDA_ONLY.csv',
        ['source_file','source_sheet','source_excel_row','NOTE_CSN','PAT_ID','MRN','NOTE_ID','mrn_status','complete_composite_key',
         'note_timestamp','note_type','department','author','encounter'],
        ([source_file,source_sheet,header_row+2+ordinal,csn,pat,mrn,note_id,status,bool(csn is not None and mrn is not None),timestamp,kind,department,author,encounter]
         for ordinal,csn,pat,mrn,note_id,status,timestamp,kind,department,author,encounter in db.execute(
             'SELECT ordinal,note_csn,pat_id,mrn,note_id,mrn_status,note_timestamp,note_type,department,author,encounter FROM fragments ORDER BY ordinal')))
    write_csv(output/'ga_note_identifier_relations_SERDA_ONLY.csv',
        ['PAT_ID','MRN','NOTE_ID','NOTE_CSN','source_rows'],
        db.execute('SELECT pat_id,mrn,note_id,note_csn,COUNT(*) FROM fragments GROUP BY pat_id,mrn,note_id,note_csn'))
    return {name:{'count':value,'status':status} for name,value,status in rows}


def group_global_blocks(db, group_key):
    return [r[0] for r in db.execute('''SELECT DISTINCT b.reason FROM blocked_csns b
        JOIN fragments f ON b.note_csn=f.note_csn WHERE f.group_key=? ORDER BY b.reason''',(group_key,))]


def group_global_review(db, group_key):
    return [r[0] for r in db.execute('''SELECT DISTINCT b.reason FROM review_csns b
        JOIN fragments f ON b.note_csn=f.note_csn WHERE f.group_key=? ORDER BY b.reason''',(group_key,))]


def metadata_evidence(rows, department_available):
    """Known identity/date inconsistencies are hard; descriptive metadata is reviewable.

    Missing optional values are not a second category. Fields' provenance remains
    unverified, especially the department column; never silently split on them.
    """
    hard=[]; warnings=[]; review=[]; evidence={}
    hard_columns=[(1,'patient'),(2,'date'),(10,'note_id'),(11,'note_csn'),(12,'note_timestamp'),
                  (13,'pat_id'),(14,'mrn')]
    review_columns=[(3,'note_type'),(4,'anchor_flag'),(8,'encounter'),(9,'author')]
    if department_available: review_columns.append((16,'department'))
    for index,name in hard_columns+review_columns:
        values={r[index] for r in rows if r[index] is not None}
        missing=sum(r[index] is None for r in rows)
        evidence[name]={'nonempty_values':sorted(values),'missing_rows':missing}
        if len(values)>1:
            reason='conflicting_'+name
            (hard if (index,name) in hard_columns else review).append(reason)
        if missing: warnings.append('missing_'+name+'_rows')
    if not department_available: warnings.append('department_column_unavailable')
    if any(row[15]=='conflicting_mrn_columns' for row in rows): hard.append('conflicting_mrn_columns')
    return hard,warnings,review,evidence
