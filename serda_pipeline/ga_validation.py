"""SERDA-only development review packages. No clinical labels or accuracy claims."""
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import ga_extraction as ga
from .core import PipelineError


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def table(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as f: return list(csv.DictReader(f))


def write_table(path, rows, columns):
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=columns); w.writeheader(); w.writerows(rows)


def version():
    base = Path(__file__).resolve().parent
    try: commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=base, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError): commit = 'unavailable'
    return dict(commit=commit, source_sha256={p.name:digest(p) for p in [base/'ga_extraction.py',base/'note_grouping.py',base/'ga_validation.py',base/'ga_review_report.py',base/'notes.py',base/'mrn_audit.py',base/'core.py',base/'ga_input.py',base/'ga_schema_adapter.py']}, utc=datetime.now(timezone.utc).isoformat())


def registry():
    # Local paths, NOT a claimed mapping to Erika's unavailable schema.
    result = [dict(field_path='local.'+name, domain=name, support_status='score_extraction',
                   limitation='MoCA/GDS/SPPB require explicit denominator; VES-13 permits absent denominator; GDS version is not inferred.') for name in ga.INSTRUMENTS]
    for name in ga.DISCOVERY:
        result.append(dict(field_path='local.'+name, domain=name,
                           support_status='categorical_extraction' if name in {'falls','polypharmacy'} else 'mention_only',
                           limitation='Falls categories only, no count/timeframe; medication threshold text only.' if name in {'falls','polypharmacy'} else 'No structured value rule.'))
    result.append(dict(field_path='local.falls.number_of_falls',domain='falls_count',support_status='not_supported',limitation='No numeric fall-count rule.'))
    return result


def candidate(group):
    rows = group['rows']
    internal = hashlib.sha256(group['key'].encode()).hexdigest()
    _, issues, quality = ga.reconstruct_fragments([(r[0],r[5],r[6],r[7]) for r in rows],group['line_start'],group['separator'])
    hard = [x for x in group['reasons'] if x not in {'identity_unverified_candidate_group_only','line_gap_or_start','out_of_order_lines'}]
    hard += [x for x in issues if x not in {'line_gap_or_start','out_of_order_lines'}]
    # Gaps/order are review questions, not a conclusion that content is lost.
    text = ''; mapping = []; spans = {}
    if rows and not hard:
        for r in sorted(rows,key=lambda r:(r[5],r[0])):
            key = (r[5],r[7])
            if key not in spans:
                if spans: text += group['separator']
                start = len(text); text += r[7]; spans[key] = (start,len(text))
            start,end = spans[key]
            mapping.append(dict(source_file=group['source_file'],source_sheet=group['source_sheet'],
                source_excel_row=group['header_row']+2+r[0],original_line_number=r[6],
                text_start=start,text_end=end,original_text=r[7]))
    anchor_ok = bool(group['patient'] and group['day'] in group['reference_days'] and not group['invalid_reference'])
    reconstruction_blocked = bool(hard)
    anchor_status = ('unreliable' if not group['patient'] or group['invalid_reference'] or not group['reference_days']
                     else 'multiple_reference_anchors' if len(group['reference_days']) > 1
                     else 'matched' if anchor_ok else 'off_anchor')
    selection_blocks = []
    if anchor_status != 'matched': selection_blocks.append('anchor_' + anchor_status)
    if group.get('target_manifest_conflict'): selection_blocks.append('target_manifest_conflict')
    signatures = [name for name,pattern in [('GA',r'geriatric assessment|geriatric components'),('functional',r'functional assessment'),('adl_iadl',r'\bI?ADLs?\b'),('plan',r'assessment\s*/\s*plan')]
                  if re.search(pattern,text,re.I)]
    signature = '|'.join(signatures) or 'other'
    reasons = [signature, 'historical_language' if ga.HISTORICAL.search(text) else 'no_history_signal',
               'slash_score_layout' if re.search(r'\d+\s*/\s*\d+',text) else 'no_slash_score_layout']
    target_candidate = (group.get('target_confirmed', False) if group.get('target_manifest_enabled') else
                        bool(group['flag']=='Yes' and (signatures or re.search(r'geriatric',group['kind'] or '',re.I))))
    target_status = ('confirmed_by_manifest' if group.get('target_confirmed') else
                     'unresolved_manifest_conflict' if group.get('target_manifest_conflict') else
                     'not_listed' if group.get('target_manifest_enabled') else
                     'candidate' if target_candidate and anchor_status == 'matched' else
                     'not_target' if anchor_status == 'off_anchor' else 'unresolved')
    return dict(internal_note_id=internal, document_key=group['key'],
        anchor_linkage_status=anchor_status, target_note_status=target_status,
        selection_blocks=selection_blocks,patient_key=group['patient'],anchor_date=group['day'] if anchor_ok else '',
        note_date=group['day'],author_id_if_available=rows[0][9] if rows else '',template_group=signature,
        selection_reason=';'.join(reasons),reconstruction_status='blocked' if reconstruction_blocked else 'pending_human_confirmation',
        hard_blocks=sorted(set(hard + selection_blocks)),
        reconstruction_warnings=sorted(set(issues+quality.get('review_warnings',[])+group.get('warnings',[])+group.get('manual_review',[]))),
        metadata_evidence=group.get('metadata',{}),reference_days=group['reference_days'],
        target_candidate=target_candidate,
        text=text,source_rows=mapping,raw_rows=[dict(source_excel_row=group['header_row']+2+r[0],line=r[6],text=r[7],
            note_date=r[2],note_type=r[3],author=r[9],note_id=r[10],note_csn=r[11],
            pat_id=r[13] if len(r)>13 else None,mrn=r[14] if len(r)>14 else None,department=r[16] if len(r)>16 else None) for r in rows])


MANIFEST = ['sample_id','internal_note_id','patient_key','anchor_date','note_date','author_id_if_available','template_group','selection_reason','reconstruction_status','identity_approved','reconstruction_approved','target_ga_approved','reviewer','review_comment']
REFERENCE = ['sample_id','field_path','reference_status','reference_value','reference_denominator','reference_evidence','reviewer','needs_erika_review','review_comment']
PREDICTIONS = ['sample_id','field_path','predicted_value','predicted_denominator','extraction_status','evidence_text','evidence_start_end','source_rows','rule_id','review_reason']


def prepare(root, out, config, patient_key):
    if out.exists() and any(out.iterdir()): raise PipelineError('Validation directory must be new and empty; existing manifest is never resampled.')
    n = config.get('ga_validation',{}).get('sample_size',8)
    if not isinstance(n,int) or not 5 <= n <= 10: raise PipelineError('ga_validation.sample_size must be 5–10.')
    out.mkdir(parents=True,exist_ok=True); (out/'candidates').mkdir(); (out/'prepare_audit').mkdir()
    meta = []
    def capture(group):
        item = candidate(group)
        save(out/'candidates'/ (item['internal_note_id']+'.json'),item)
        meta.append({k:v for k,v in item.items() if k not in {'text','source_rows','raw_rows'}})
    # Same loader/normalization/grouping as GA mode. No global verification switch changed.
    ga.run(root,out/'prepare_audit',config,patient_key,review_callback=capture)
    if config.get('ga_validation', {}).get('field_registry') == 'erika_draft' or config.get('ga_input', {}).get('target_note_manifest'):
        counts = Counter((m['patient_key'],m['note_date']) for m in meta if m['target_candidate'])
        for m in meta:
            if m['target_candidate'] and counts[m['patient_key'],m['note_date']] > 1:
                m['hard_blocks'].append('multiple_target_candidates')
                m['selection_blocks'].append('multiple_target_candidates')
                m['target_note_status'] = 'ambiguous_multiple_candidates'
                path = out/'candidates'/(m['internal_note_id']+'.json')
                item = read(path); item.update(m); save(path,item)
    selected=[]; patients=set(); strata=set()
    pool=sorted([m for m in meta if not m['hard_blocks'] and m['target_candidate']],key=lambda m:m['internal_note_id'])
    while pool and len(selected)<n:
        best=max(pool,key=lambda m:(m['patient_key'] not in patients,m['template_group'] not in strata,
                                    m['selection_reason'] not in strata))
        selected.append(best);patients.add(best['patient_key']);strata.update([best['template_group'],best['selection_reason']]);pool.remove(best)
    manifest=[]
    for i,m in enumerate(selected,1):
        row={key:m.get(key,'') for key in MANIFEST};row.update(sample_id=f'S{i:03}',identity_approved='no',reconstruction_approved='no',target_ga_approved='no')
        manifest.append(row)
    write_table(out/'sample_manifest.csv',manifest,MANIFEST)
    schema_mode = config.get('ga_validation', {}).get('field_registry', 'baseline')
    if schema_mode not in {'baseline','erika_draft'}: raise PipelineError('Unknown GA field_registry.')
    if schema_mode == 'erika_draft':
        from .ga_schema_adapter import registry as schema_registry, SCHEMA
        fields = schema_registry()
        (out/'erika_schema_snapshot.json').write_bytes(SCHEMA.read_bytes())
    else: fields = registry()
    write_table(out/'support_registry.csv',fields,list(fields[0]))
    refs=[dict(sample_id=m['sample_id'],field_path=f['field_path'],reference_status='not_reviewed',reference_value='',reference_denominator='',reference_evidence='',reviewer='',needs_erika_review='no',review_comment='') for m in manifest for f in fields]
    write_table(out/'reference_annotations.csv',refs,REFERENCE)
    write_table(out/'reconstruction_audit.csv',[dict(internal_note_id=m['internal_note_id'],status=m['reconstruction_status'],anchor_linkage_status=m['anchor_linkage_status'],target_note_status=m['target_note_status'],hard_blocks=';'.join(m['hard_blocks']),warnings=';'.join(m['reconstruction_warnings'])) for m in meta],['internal_note_id','status','anchor_linkage_status','target_note_status','hard_blocks','warnings'])
    from .mrn_audit import _workbook
    source = config.get('ga_input', {}).get('anchor_source', 'demographics_reference')
    inputs={name:digest(_workbook(root,name,config)) for name in (['notes'] if source == 'approved_master' else ['demographics','notes'])}
    for name in ['cohort_anchor_file','target_note_manifest']:
        path = config.get('ga_input', {}).get(name)
        if path: inputs[name] = digest(path)
    # All rows remain sensitive, including patients without a matched target document.
    from .ga_input import master
    approved = master(config, patient_key)
    if approved is not None:
        mapping=[]
        target_groups = defaultdict(list)
        for m in meta:
            if m['target_candidate']: target_groups[m['patient_key'],m['note_date']].append(m)
        for patient, days in approved[0].items():
            for day in days:
                linked=target_groups[patient,day]
                mapping.append(dict(patient_key=patient,anchor_date=day,target_count=len(linked),
                    link_status='missing_or_unresolved' if not linked else 'multiple_candidates' if len(linked)>1 else
                    'blocked' if linked[0]['hard_blocks'] else linked[0]['target_note_status']))
        write_table(out/'patient_target_mapping_SERDA_ONLY.csv',mapping,['patient_key','anchor_date','target_count','link_status'])
    frozen=dict(version=version(),config=config,patient_key=patient_key,input_sha256=inputs,
                schema_status=schema_mode, anchor_source=source,
                erika_schema_sha256=digest(out/'erika_schema_snapshot.json') if schema_mode == 'erika_draft' else None,frozen_sample_rows=manifest,
                grouping_audit_sha256={p.name:digest(p) for p in (out/'prepare_audit').glob('ga_note_grouping_*.csv')},
                linkage_schema=read(out/'prepare_audit'/'ga_linkage_schema.json') if (out/'prepare_audit'/'ga_linkage_schema.json').exists() else None,
                schema_sha256=digest(out/'prepare_audit'/'ga_schema_validation.json') if (out/'prepare_audit'/'ga_schema_validation.json').exists() else None,
                requested_samples=n,selected_samples=len(manifest),
                support_registry_sha256=digest(out/'support_registry.csv'),sample_membership=[(m['sample_id'],m['internal_note_id']) for m in manifest],
                sample_files={m['internal_note_id']:digest(out/'candidates'/(m['internal_note_id']+'.json')) for m in manifest})
    save(out/'run_manifest.json',frozen)
    (out/'input_scope_summary.md').write_text(
        'GA development review only; not a final validated research cohort.\n'
        + 'Anchor source: ' + source + '.\n'
        + ('Demographics dates are exploratory references, not confirmed study eligibility.\n' if source == 'demographics_reference' else
           'Eligibility and dates supplied by an externally approved master; this code does not establish clinical eligibility.\n')
        + 'Target manifest: ' + ('provided' if config.get('ga_input',{}).get('target_note_manifest') else 'absent; heuristic candidates only') + '.\n'
        + 'Reconstructed text still requires per-sample identity/completeness/target confirmation. '
        + 'Machine not_found is not clinical not_documented. No labels, predictor changes or real-data accuracy claims.\n', encoding='utf-8')
    from .ga_review_report import render
    render(out/'review.html',manifest,[read(out/'candidates'/(m['internal_note_id']+'.json')) for m in manifest],[])
    blocked=[m for m in meta if m['hard_blocks']][:10]
    render(out/'blocked_review.html',[dict(sample_id='BLOCKED-'+str(i),**m) for i,m in enumerate(blocked,1)],
           [read(out/'candidates'/(m['internal_note_id']+'.json')) for m in blocked],[])


def load_package(out):
    frozen=read(out/'run_manifest.json'); manifest=table(out/'sample_manifest.csv')
    if [(m['sample_id'],m['internal_note_id']) for m in manifest] != [tuple(x) for x in frozen['sample_membership']]:
        raise PipelineError('Frozen sample membership/order changed; prepare a separate package.')
    editable={'identity_approved','reconstruction_approved','target_ga_approved','reviewer','review_comment'}
    for m,original in zip(manifest,frozen['frozen_sample_rows']):
        if any(m[k] != str(original[k] or '') for k in MANIFEST if k not in editable):
            raise PipelineError('Frozen sample metadata changed; only approval/reviewer columns are editable.')
    for m in manifest:
        if digest(out/'candidates'/(m['internal_note_id']+'.json')) != frozen['sample_files'][m['internal_note_id']]:
            raise PipelineError('Frozen note content or source mapping changed.')
    if digest(out/'support_registry.csv') != frozen['support_registry_sha256']: raise PipelineError('Frozen support registry changed.')
    if frozen.get('erika_schema_sha256') and digest(out/'erika_schema_snapshot.json') != frozen['erika_schema_sha256']:
        raise PipelineError('Frozen Erika schema changed.')
    return frozen,manifest


def run(out,label='baseline'):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',label): raise PipelineError('Invalid validation run label.')
    frozen,manifest=load_package(out); dest=out/label
    if dest.exists(): raise PipelineError('Run already exists; baseline/revised results are immutable. Use another label.')
    if label=='baseline' and version()['source_sha256']['ga_extraction.py'] != frozen['version']['source_sha256']['ga_extraction.py']:
        raise PipelineError('Extractor changed since Prepare; baseline must use the prepared extractor version.')
    if label == 'baseline' and frozen.get('schema_status') == 'erika_draft' and version()['source_sha256']['ga_schema_adapter.py'] != frozen['version']['source_sha256']['ga_schema_adapter.py']:
        raise PipelineError('Schema adapter changed since Prepare; use prepared code for baseline.')
    fields=table(out/'support_registry.csv'); predictions=[];raw={}; notes=[]
    for m in manifest:
        note=read(out/'candidates'/(m['internal_note_id']+'.json'));notes.append(note)
        approved=all(m[k].strip().lower()=='yes' for k in ['identity_approved','reconstruction_approved','target_ga_approved']) and bool(m['reviewer'].strip()) and not note['hard_blocks']
        matches=ga.extract_text(note['text'],frozen['config'].get('ga_extraction',{}).get('validated_denominators',{}))[0] if approved else []
        raw[m['sample_id']]=matches
        resolved=ga.resolve_evidence(matches)
        for f in fields:
            hits=[r for r in resolved if r[0]==f['domain']]
            values=[r for r in hits if r[3]=='extracted'];unique={(r[1],r[2]) for r in values}
            state=('blocked' if not approved else 'not_supported' if f['support_status'] in {'mention_only','not_supported'} else
                   'extracted' if len(unique)==1 else 'ambiguous' if hits else 'not_found')
            value,denom=next(iter(unique)) if state=='extracted' else ('','')
            spans=[(r[4],r[5]) for r in hits]
            source=sorted({r['source_excel_row'] for r in note['source_rows'] if any(r['text_start']<end and r['text_end']>start for start,end in spans)})
            predictions.append(dict(sample_id=m['sample_id'],field_path=f['field_path'],predicted_value=value,predicted_denominator=denom,
                extraction_status=state,evidence_text=json.dumps([r[6] for r in hits],ensure_ascii=False),evidence_start_end=json.dumps(spans),
                source_rows=json.dumps(source),rule_id=';'.join(sorted({r[7] for r in hits})),review_reason=';'.join(sorted({r[3] for r in hits})) if approved else 'sample_scope_approval_required'))
    if frozen.get('schema_status') == 'erika_draft':
        from .ga_schema_adapter import adapt
        field_index = {f['field_path']:f for f in fields}
        predictions = [adapt(p,field_index[p['field_path']]) for p in predictions]
    dest.mkdir();write_table(dest/'predictions.csv',predictions,PREDICTIONS);save(dest/'raw_extractor_output.json',raw)
    if frozen.get('schema_status') == 'erika_draft':
        save(dest/'ga_extraction_results.json',dict(status='machine_results_not_clinical_missingness', fields=predictions))
    save(dest/'run_manifest.json',dict(version=version(),prepare_sha256=digest(out/'run_manifest.json'),approval_manifest_sha256=digest(out/'sample_manifest.csv'),predictions_sha256=None))
    snapshot=read(dest/'run_manifest.json');snapshot['predictions_sha256']=digest(dest/'predictions.csv');save(dest/'run_manifest.json',snapshot)
    write_table(dest/'sample_manifest_snapshot.csv',manifest,MANIFEST)
    from .ga_review_report import render
    render(dest/'review.html',manifest,notes,predictions)


def compare(prediction, reference):
    machine=prediction['extraction_status'];human=reference['reference_status']
    if machine=='blocked': return 'blocked_reconstruction_or_selection'
    if human=='not_reviewed': return 'not_reviewed'
    if reference['needs_erika_review'].lower()=='yes' or human=='unclear': return 'needs_clinical_review'
    if machine=='not_supported': return 'unsupported_documented' if human=='documented' else 'not_supported'
    if machine=='extracted':
        if human=='not_documented': return 'false_extraction'
        same=(prediction['predicted_value'].strip()==reference['reference_value'].strip() and prediction['predicted_denominator'].strip()==reference['reference_denominator'].strip())
        return 'correct_value_and_denominator' if same else 'incorrect_value_or_denominator'
    if human=='documented': return 'missed_documented_value' if machine=='not_found' else 'unresolved_documented_value'
    return 'correct_no_output' if machine=='not_found' else 'ambiguous_without_documented_value'


def evaluate(out,label='baseline',evaluation='evaluation'):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',label) or not re.fullmatch(r'[A-Za-z0-9_-]+',evaluation): raise PipelineError('Invalid run/evaluation name.')
    load_package(out); run_dir=out/label; dest=run_dir/evaluation
    if dest.exists(): raise PipelineError('Evaluation exists; choose a new evaluation name.')
    snapshot=read(run_dir/'run_manifest.json')
    if digest(run_dir/'predictions.csv') != snapshot['predictions_sha256']: raise PipelineError('Frozen predictions changed.')
    predictions=table(run_dir/'predictions.csv'); refs=table(out/'reference_annotations.csv')
    index={(r['sample_id'],r['field_path']):r for r in refs}
    if len(index)!=len(refs) or set(index)!={(p['sample_id'],p['field_path']) for p in predictions}: raise PipelineError('Reference grid must exactly match prediction sample/field keys, without duplicates.')
    counts=defaultdict(Counter); errors=[]
    for p in predictions:
        r=index[p['sample_id'],p['field_path']]
        if r['reference_status'] not in {'documented','not_documented','unclear','not_reviewed'}: raise PipelineError('Invalid reference status.')
        if r['needs_erika_review'].lower() not in {'yes','no'}: raise PipelineError('needs_erika_review must be yes or no.')
        if r['reference_status']=='not_documented' and (r['reference_value'].strip() or r['reference_denominator'].strip()): raise PipelineError('not_documented reference cannot contain a value or denominator.')
        if r['reference_status']!='not_reviewed' and not r['reviewer'].strip(): raise PipelineError('Reviewed reference requires reviewer.')
        if r['reference_status']=='documented' and (not r['reference_value'].strip() or not r['reference_evidence'].strip()): raise PipelineError('Documented reference needs a value and source evidence.')
        result=compare(p,r);counts[p['field_path']][result]+=1
        counts[p['field_path']]['total_grid_rows']+=1
        if r['reference_status']=='documented': counts[p['field_path']]['reference_documented']+=1
        if p['extraction_status']=='extracted': counts[p['field_path']]['machine_output_values']+=1
        errors.append(dict(sample_id=p['sample_id'],field_path=p['field_path'],comparison=result,reference_status=r['reference_status'],machine_status=p['extraction_status'],review_comment=r['review_comment']))
    dest.mkdir();write_table(dest/'reference_snapshot.csv',refs,REFERENCE)
    write_table(dest/'error_cases.csv',errors,list(errors[0]) if errors else ['sample_id','field_path','comparison'])
    for c in counts.values():
        for metric in ['reference_documented','machine_output_values','correct_value_and_denominator',
                       'missed_documented_value','false_extraction','incorrect_value_or_denominator',
                       'unsupported_documented','not_supported','blocked_reconstruction_or_selection',
                       'needs_clinical_review','not_reviewed','unresolved_documented_value','correct_no_output']:
            c[metric]+=0
    rows=[dict(field_path=field,metric=metric,count=count) for field,c in counts.items() for metric,count in sorted(c.items())]
    write_table(dest/'evaluation_by_field.csv',rows,['field_path','metric','count'])
    save(dest/'evaluation_manifest.json',dict(version=version(),reference_sha256=digest(out/'reference_annotations.csv'),prediction_sha256=digest(run_dir/'predictions.csv')))
    (dest/'summary.md').write_text('Development / error-analysis sample. Counts only; no overall accuracy or population inference. Reference annotations are provisional unless clinically adjudicated. Blocked, unsupported, unclear and unreviewed cases remain visible. Same samples reused for revised runs are not an independent test set.\n',encoding='utf-8')
