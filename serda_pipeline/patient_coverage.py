"""Standalone eight-export MRN coverage, not study cohort construction.

Reuse established streaming schema discovery and identifier conventions. No clinical
column requirements, date parsing, note reconstruction, feature extraction or PHI logs.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import yaml
from .mrn_audit import DATASETS, _workbook, _rows, _discover, _clean_mrn, _clean_id
from .notes import missing_value


class CoverageError(ValueError): pass


def write(path, records, columns):
    with Path(path).open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(records)


def fingerprint(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def scan(root,dataset,config,restricted):
    path=_workbook(root,dataset,config);counts=Counter();mrns=set();pairs=set();pats=set()
    invalid_path=restricted/(dataset+'_identifier_rows.csv')
    with invalid_path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['source_excel_row','PAT_ID','source_mrn_value','reason']);writer.writeheader()
        with _rows(path,dataset,config) as (sheet,header,headers,stream):
            mapping=_discover(headers,dataset,config);pending=0
            def get(row,i):return row[i] if i is not None and i<len(row) else None
            def process(row,excel_row):
                counts['total_rows']+=1
                pat=_clean_id(get(row,mapping['patient']))
                if pat is not None:pats.add(pat)
                raw=get(row,mapping['mrn']);mrn,status,trimmed=_clean_mrn(raw)
                if mapping['mrn'] is None:mrn=None;status='mrn_column_unavailable'
                if trimmed:counts['trimmed_mrn_rows']+=1
                alternatives=[_clean_mrn(get(row,i)) for i in mapping['alternatives']]
                if any(s=='numeric_or_nontext_cell' for _,s,_ in alternatives):counts['numeric_alternative_rows']+=1
                if mrn is None and any(a is not None for a,_,_ in alternatives):counts['alternative_present_primary_unavailable_rows']+=1
                if mrn is not None and any(a is not None and a!=mrn for a,_,_ in alternatives):mrn=None;status='conflicting_mrn_columns'
                if mrn is None:
                    counts['unlinked_identifier_rows']+=1;counts[status+'_rows']+=1
                    writer.writerow(dict(source_excel_row=excel_row,PAT_ID=pat,source_mrn_value=raw,reason=status))
                else:
                    counts['valid_mrn_rows']+=1;mrns.add(mrn)
                    if pat is not None:pairs.add((pat,mrn))
            for i,row in enumerate(stream,header+2):
                if len(row)>len(headers) and any(missing_value(v) is not None for v in row[len(headers):]):
                    raise CoverageError('Source header width does not cover populated cells.')
                if all(missing_value(v) is None for v in row):pending+=1;continue
                for blank in range(i-pending,i):process([],blank)
                pending=0;process(row,i)
            counts['trailing_blank_rows_ignored']=pending
    usable=mapping['mrn'] is not None and (counts['total_rows']==0 or bool(mrns))
    by_pat=defaultdict(set);by_mrn=defaultdict(set)
    for pat,mrn in pairs:by_pat[pat].add(mrn);by_mrn[mrn].add(pat)
    case=defaultdict(set)
    for mrn in mrns:case[mrn.casefold()].add(mrn)
    stats=dict(dataset=dataset,status='available' if usable else 'linkage_unavailable',total_rows=counts['total_rows'],
        unique_valid_mrns=len(mrns),unique_pat_ids=len(pats),valid_mrn_rows=counts['valid_mrn_rows'],
        missing_mrn_rows=counts['missing_rows'],invalid_nontext_mrn_rows=counts['numeric_or_nontext_cell_rows'],
        conflicting_mrn_columns_rows=counts['conflicting_mrn_columns_rows'],mrn_column_unavailable_rows=counts['mrn_column_unavailable_rows'],
        unlinked_identifier_rows=counts['unlinked_identifier_rows'],trimmed_mrn_rows=counts['trimmed_mrn_rows'],
        numeric_alternative_rows=counts['numeric_alternative_rows'],alternative_present_primary_unavailable_rows=counts['alternative_present_primary_unavailable_rows'],
        trailing_blank_rows_ignored=counts['trailing_blank_rows_ignored'],pat_ids_with_multiple_mrns=sum(len(v)>1 for v in by_pat.values()),
        mrns_with_multiple_pat_ids=sum(len(v)>1 for v in by_mrn.values()),case_variant_groups=sum(len(v)>1 for v in case.values()),
        mrn_mapping_status=mapping['status'],mrn_column=headers[mapping['mrn']] if mapping['mrn'] is not None else None,
        reason=None if usable else 'No usable direct MRN linkage; not an empty patient set.')
    return stats,mrns if usable else None,pairs,dict(file=path.name,sheet=sheet,header_row=header,bytes=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns)


def roster(path):
    if path is None:return None
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not {'mrn','eligible','confirmation_status','source','reviewer'}.issubset(reader.fieldnames or []):
            raise CoverageError('Roster must contain mrn, eligible, confirmation_status, source, reviewer.')
        seen=set();eligible=set()
        for row in reader:
            mrn,status,_=_clean_mrn(row['mrn'])
            if mrn is None or mrn in seen:raise CoverageError('Roster identifiers missing or duplicated.')
            if row['eligible'] not in {'yes','no'} or row['confirmation_status']!='confirmed' or not row['source'].strip() or not row['reviewer'].strip():
                raise CoverageError('Roster needs independently confirmed eligibility and provenance.')
            seen.add(mrn)
            if row['eligible']=='yes':eligible.add(mrn)
    if not eligible:raise CoverageError('Roster has no confirmed eligible MRNs.')
    return eligible


INVENTORY=['dataset','status','total_rows','unique_valid_mrns','unique_pat_ids','reference_type','reference_mrns',
           'reference_mrns_absent_from_dataset','coverage_pct','valid_mrn_rows','unlinked_identifier_rows','missing_mrn_rows',
           'invalid_nontext_mrn_rows','conflicting_mrn_columns_rows','mrn_column_unavailable_rows','trimmed_mrn_rows',
           'numeric_alternative_rows','alternative_present_primary_unavailable_rows','trailing_blank_rows_ignored',
           'pat_ids_with_multiple_mrns','mrns_with_multiple_pat_ids','case_variant_groups','mrn_mapping_status','mrn_column','reason']


def run(root,out,config_path,roster_path=None):
    root=Path(root).resolve();out=Path(out).resolve();repo=Path(__file__).resolve().parent.parent
    if not root.is_dir():raise CoverageError('Data directory must exist.')
    if out.exists():raise CoverageError('Use a new output directory; previous audits are never overwritten.')
    if any(out==p or out.is_relative_to(p) or p.is_relative_to(out) for p in [root,repo]):
        raise CoverageError('Output must be separate from source data and code repository.')
    config=yaml.safe_load(Path(config_path).read_text(encoding='utf-8'))
    if not isinstance(config,dict):raise CoverageError('Invalid configuration.')
    eligible=roster(roster_path)
    aggregate=out/'aggregate';restricted=out/'restricted_SERDA_ONLY'
    aggregate.mkdir(parents=True);restricted.mkdir()
    stats={};sets={};pairs={};sources={};failed=[]
    for dataset in DATASETS:
        try:
            stats[dataset],sets[dataset],pairs[dataset],sources[dataset]=scan(root,dataset,config,restricted)
        except Exception as exc:
            # Discard any partial dataset; no raw exception messages/values in shareable outputs.
            partial=restricted/(dataset+'_identifier_rows.csv')
            if partial.exists():partial.unlink()
            stats[dataset]=dict(dataset=dataset,status='failed',reason=type(exc).__name__+': workbook/schema scan failed; check local source and config.')
            sets[dataset]=None;pairs[dataset]=set();failed.append(dataset)
        print(dataset+': '+stats[dataset]['status'])
    available=[s for s in sets.values() if s is not None];complete=len(available)==len(DATASETS)
    union=set().union(*available) if available else set()
    intersection=set.intersection(*available) if complete else None
    reference_type='observed_eight_table_union' if complete else 'partial_observed_union_available_tables'
    rows=[]
    for dataset in DATASETS:
        current=sets[dataset];row={k:stats[dataset].get(k) for k in INVENTORY}
        row.update(reference_type=reference_type,reference_mrns=len(union) if available else None,
                   reference_mrns_absent_from_dataset=len(union-current) if current is not None else None,
                   coverage_pct=100*len(current)/len(union) if current is not None and union else None)
        rows.append(row)
    write(aggregate/'patient_coverage_summary.csv',rows,INVENTORY)
    totals=[dict(metric='datasets_expected',count=len(DATASETS)),dict(metric='datasets_with_usable_linkage',count=len(available)),
            dict(metric='observed_available_union_mrns',count=len(union) if available else None),
            dict(metric='eight_table_union_mrns',count=len(union) if complete else None),
            dict(metric='eight_table_intersection_mrns',count=len(intersection) if complete else None)]
    write(aggregate/'union_intersection_summary.csv',totals,['metric','count'])
    matrix=[];directed=[]
    for a in DATASETS:
        row={'dataset':a}
        for b in DATASETS:
            both=sets[a] is not None and sets[b] is not None
            row[b]=len(sets[a]&sets[b]) if both else None
            if a!=b:directed.append(dict(present_in=a,absent_from=b,patients=len(sets[a]-sets[b]) if both else None,status='available' if both else 'unavailable'))
        matrix.append(row)
    write(aggregate/'pairwise_overlap_matrix.csv',matrix,['dataset']+DATASETS)
    write(aggregate/'directional_patient_gaps.csv',directed,['present_in','absent_from','patients','status'])
    presence=[];patterns=Counter()
    for mrn in sorted(union):
        row={'MRN':mrn,**{d:('unknown' if sets[d] is None else 'present' if mrn in sets[d] else 'absent') for d in DATASETS}}
        presence.append(row);patterns[tuple(row[d] for d in DATASETS)]+=1
    write(restricted/'mrn_presence_by_dataset.csv',presence,['MRN']+DATASETS)
    write(aggregate/'patient_presence_patterns.csv',[dict(zip(DATASETS,pattern),patients=count) for pattern,count in sorted(patterns.items())],DATASETS+['patients'])
    write(restricted/'observed_union_mrns_absent_from_dataset.csv',
          (dict(dataset=d,MRN=mrn) for d in DATASETS if sets[d] is not None for mrn in sorted(union-sets[d])),['dataset','MRN'])
    all_pairs=set().union(*pairs.values());by_pat=defaultdict(set);by_mrn=defaultdict(set)
    for pat,mrn in all_pairs:by_pat[pat].add(mrn);by_mrn[mrn].add(pat)
    write(restricted/'identifier_mapping_pairs.csv',
          (dict(dataset=d,PAT_ID=pat,MRN=mrn) for d in DATASETS for pat,mrn in sorted(pairs[d])),['dataset','PAT_ID','MRN'])
    global_case=defaultdict(set)
    for mrn in union:global_case[mrn.casefold()].add(mrn)
    write(aggregate/'cross_dataset_identifier_consistency.csv',[
        dict(metric='mrn_case_variant_groups_across_available_tables',count=sum(len(v)>1 for v in global_case.values())),
        dict(metric='pat_ids_with_multiple_mrns',count=sum(len(v)>1 for v in by_pat.values())),
        dict(metric='mrns_with_multiple_pat_ids',count=sum(len(v)>1 for v in by_mrn.values()))],['metric','count'])
    if eligible is not None:
        coverage=[];missing=[]
        for d in DATASETS:
            current=sets[d];coverage.append(dict(dataset=d,reference_type='independently_confirmed_eligible_roster',reference_mrns=len(eligible),
                matched_mrns=len(current&eligible) if current is not None else None,roster_mrns_absent_from_dataset=len(eligible-current) if current is not None else None,
                dataset_mrns_outside_roster=len(current-eligible) if current is not None else None,coverage_pct=100*len(current&eligible)/len(eligible) if current is not None else None,status=stats[d]['status']))
            if current is not None:missing.extend(dict(dataset=d,MRN=m) for m in sorted(eligible-current))
        write(aggregate/'validated_roster_coverage.csv',coverage,list(coverage[0]))
        write(restricted/'roster_mrns_absent_from_dataset.csv',missing,['dataset','MRN'])
    excluded=sum(s.get('unlinked_identifier_rows',0) for s in stats.values())
    notes=[ '# Patient Coverage & Missingness Audit Summary', '',
        'Patient-level source presence only. This is not a clinical cohort definition, event-window analysis, or variable-level missingness report.',
        'Reference: '+reference_type+'. Demographics is one of eight equal source datasets, never the default study cohort.',
        'Eight-table union/intersection available: '+str(complete)+'. Blank cells mean unavailable or undefined, not zero.',
        'Usable MRNs are exact trimmed strings. Leading zeros/case/alphanumeric characters are preserved. No PAT_ID fallback, case folding or forced matching.',
        'Rows with withheld identifiers across successfully scanned files: '+str(excluded)+'. Missing-row counts cannot determine how many real people have missing identifiers.',
        'Internal blank rows count as source rows; trailing blank rows are ignored, matching the previous MRN audit convention.', '',
        '| Dataset | Status | Rows | Valid MRNs | Absent from this dataset (observed reference) | Coverage % |',
        '|---|---|---:|---:|---:|---:|']
    for r in rows:notes.append('| '+' | '.join(str(r[k]) if r[k] is not None else 'Unavailable' for k in ['dataset','status','total_rows','unique_valid_mrns','reference_mrns_absent_from_dataset','coverage_pct'])+' |')
    notes.extend(['','Use directional_patient_gaps.csv to answer “present in table A, absent from table B”; use the overlap matrix and presence-pattern counts to locate combinations of gaps.',
        'Known identifier issues (missing/nontext/conflicting columns or ambiguous PAT_ID↔MRN mappings) are separate from absence of source rows. Numeric Excel MRNs are withheld because leading zeros may already be lost.',
        'Notes coverage counts direct validated MRNs on source fragments only. It does not establish unique notes, complete reconstructions, anchor alignment, geriatrician identity or target GA-note availability.',
        'Medication coverage needs only patient identifiers: unresolved medication/date columns do not block this scan. There is no temporal or clinical-feature filtering.',
        'Expected event sparsity versus extraction error: NOT DETERMINED by set comparisons. A patient without labs/medications may have no qualifying events, or source queries may differ. Do not label either explanation as proven.',
        'Analyst checks: compare population/encounter inclusion SQL, date bounds, site filters, event requirements, joins that drop patients, MRN fields/types and Notes export linkage. Confirm whether all tables were intended to cover the same roster.',
        'Variable-level missingness (education, medication attributes, etc.) remains in the original audit and is not mixed into patient coverage.',
        'Validated-roster comparison: '+('provided with explicit confirmation/provenance; see validated_roster_coverage.csv.' if eligible is not None else 'not supplied; no research-cohort coverage claim.'),
        'Historical PAT_ID counts are not copied into this new MRN audit. No clinical validation or SQL error conclusion is implied.',
        'Only aggregate/ is a candidate for sharing, subject to institutional disclosure review (including small cells). restricted_SERDA_ONLY/ contains identifiers and must stay in approved restricted storage.'])
    (aggregate/'Patient_Coverage_Missingness_Summary.md').write_text('\n'.join(notes)+'\n',encoding='utf-8')
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError):commit='unavailable'
    report=dict(utc=datetime.now(timezone.utc).isoformat(),commit=commit,config_sha256=fingerprint(config_path),
        source_metadata=sources,reference_type=reference_type,completed=[d for d in DATASETS if d not in failed],failed=failed,
        linkage_unavailable=[d for d in DATASETS if sets[d] is None],eight_table_comparison_complete=complete,
        roster_sha256=fingerprint(roster_path) if roster_path else None,
        source_code_sha256={name:fingerprint(Path(__file__).parent/name) for name in ['patient_coverage.py','mrn_audit.py','notes.py']})
    (out/'execution_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return complete


def main():
    parser=argparse.ArgumentParser(description='Standalone MRN source coverage; no cohort, GA or feature changes.')
    parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path(__file__).resolve().parent.parent/'configs'/'serda_ga_erika.yaml')
    parser.add_argument('--roster',type=Path)
    args=parser.parse_args()
    try:complete=run(args.data_dir,args.output_dir,args.config,args.roster)
    except Exception as exc:
        print(str(exc) if isinstance(exc,CoverageError) else type(exc).__name__+': audit failed; inspect source/config locally.');return 2
    print('Coverage reports saved; '+('all eight tables usable.' if complete else 'incomplete: inspect execution_report.json; missing tables are not empty sets.'))
    return 0 if complete else 2


if __name__=='__main__':raise SystemExit(main())
