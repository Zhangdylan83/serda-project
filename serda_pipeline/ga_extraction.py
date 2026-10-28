"""Conservative, offline GA feasibility extraction. All row-level outputs are PHI."""
from collections import Counter, defaultdict
from contextlib import closing
import csv
import json
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory

import pandas as pd

from .core import PipelineError, parse_dates
from .schema import normalize
from .note_grouping import audit_grouping, group_global_blocks, group_global_review, metadata_evidence
from .mrn_audit import _rows, _discover, _clean_mrn
from .notes import (anchor_status, find_workbook, identifier, line_number,
                    line_quality, missing_value, schema_mapping, validate_settings)


INSTRUMENTS = {
    'moca': r'(?:\bMoCA\b|Montreal\s+Cognitive\s+Assessment)',
    'gds': r'(?:\bGDS\b|Geriatric\s+Depression\s+Scale)',
    'sppb': r'(?:\bSPPB\b|Short\s+Physical\s+Performance\s+Battery)',
    'ves_13': r'(?:\bVES\s*[- ]?\s*13\b|Vulnerable\s+Elders\s+Survey\s*[- ]?\s*13)',
}
DISCOVERY = {
    'adl': r'\bADLs?\b|activities\s+of\s+daily\s+living',
    'iadl': r'\bIADLs?\b|instrumental\s+activities\s+of\s+daily\s+living',
    'nutrition_weight_loss': r'\bnutrition\b|unintentional\s+weight\s+loss',
    'falls': r'\bfalls?\b',
    'social_support': r'\bsocial\s+support\b|\bcaregiver\b|lives?\s+(?:alone|independently)',
    'polypharmacy': r'\bpolypharmacy\b|\bmedications?\b|\bmeds\b',
    'gait_mobility': r'\bgait\b|\bmobility\b|\bwalker\b|\bcane\b',
    'fatigue_exhaustion': r'\bfatigue\b|\bexhaustion\b',
    'functional_trajectory': r'functional\s+(?:decline|trajectory)|declin(?:e|ing)\s+function',
}
HISTORICAL = re.compile(r'\b(?:previous(?:ly)?|prior|historical|history of|last visit|last year|baseline score|old score)\b', re.I)
NOT_DONE = re.compile(r'\b(?:not performed|not done|unable to (?:complete|perform)|declined|could not complete)\b', re.I)
DEFAULT_TYPE = [r'geriatric\s+oncology\s+initial\s+consult(?:ation)?', r'geriatric\s+assessment']
DEFAULT_TEMPLATE = [r'geriatric\s+components?', r'geriatric\s+assessment']


def _csv(path, header, rows):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _id(value):
    value = missing_value(value)
    return identifier(value) if value is not None else None


def _date(value, config):
    parsed, _ = parse_dates(pd.Series([value], dtype=object), config)
    result = parsed.iloc[0]
    return None if pd.isna(result) else result.strftime('%Y-%m-%d')


def _timestamp_and_day(value, config):
    parsed, _ = parse_dates(pd.Series([value], dtype=object), config)
    result = parsed.iloc[0]
    return (None,None) if pd.isna(result) else (result.isoformat(),result.strftime('%Y-%m-%d'))


def _value(row, index):
    return row[index] if index is not None and index < len(row) else None


def _patient(value, key):
    return _clean_mrn(value)[0] if key == 'mrn' else _id(value)


def reference_days(root, config, patient_key):
    """Stream only direct identifiers and CONTACT_DATE; never infer crosswalks."""
    from .mrn_audit import _workbook
    result = defaultdict(set)
    invalid = set()
    path = _workbook(root, 'demographics', config)
    with _rows(path, 'demographics', config) as (_, _, headers, stream):
        mapping = _discover(headers, 'demographics', config)
        col = mapping['mrn' if patient_key == 'mrn' else 'patient']
        if col is None or mapping['date'] is None:
            raise PipelineError('Demographics lacks a validated direct patient key or CONTACT_DATE for GA selection.')
        for row in stream:
            patient = _patient(_value(row, col), patient_key)
            if patient is None:
                continue
            if patient_key == 'mrn':
                if any((other := _clean_mrn(_value(row, i))[0]) is not None and other != patient
                       for i in mapping['alternatives']):
                    invalid.add(patient)
                    continue
            day = _date(_value(row, mapping['date']), config)
            if day is None:
                invalid.add(patient)
            else:
                result[patient].add(day)
    return result, invalid


def _patterns(settings, name, defaults):
    values = settings.get(name, defaults)
    if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
        raise PipelineError('ga_extraction.' + name + ' must be a list of nonempty regex strings.')
    try:
        return [re.compile(v, re.I) for v in values]
    except re.error as exc:
        raise PipelineError('Invalid ga_extraction.' + name + ' regex: ' + str(exc)) from exc


def _context(text, start):
    # Bound context to the current short clause, so a prior score is not confused
    # with an anchor-visit score elsewhere in the note.
    prefix = text[max(0, start-90):start]
    return re.split(r'[.\n;]', prefix)[-1][-70:]


def extract_text(text, validated_denominators=None):
    """Return evidence records; no clinical interpretation or probability score."""
    validated_denominators = validated_denominators or {}
    rows = []
    mentions = set()
    for instrument, alias in INSTRUMENTS.items():
        for found in re.finditer(alias, text, re.I):
            mentions.add(instrument)
            after = text[found.end():found.end()+35]
            # Only an adjacent explicitly delimited value is a score.
            score = re.match(r'\s*(?:score\s*)?(?::|=|of)?\s*(\d{1,2})(?:\s*/\s*(\d{1,2}))?\b', after, re.I)
            if score is None or (instrument != 'ves_13' and score.group(2) is None):
                rows.append((instrument, None, None, 'unsupported_format', found.start(), found.end(), found.group(), 'alias_only'))
                continue
            number = int(score.group(1))
            denominator = int(score.group(2)) if score.group(2) else None
            evidence = text[found.start():found.end()+score.end()]
            context = _context(text, found.start())
            suffix = re.split(r'[.\n;]', text[found.end()+score.end():found.end()+score.end()+35])[0]
            status = ('historical_context' if HISTORICAL.search(context) or HISTORICAL.search(suffix) else
                      'not_performed_context' if NOT_DONE.search(context) or NOT_DONE.search(suffix) else
                      'invalid_numeric_bound' if denominator is not None and (denominator == 0 or number > denominator) else
                      'unverified_denominator' if denominator is not None and instrument in validated_denominators and
                        denominator not in validated_denominators[instrument] else
                      'candidate_value')
            rows.append((instrument, number, denominator, status, found.start(), found.end()+score.end(), evidence, 'explicit_adjacent_score'))
    qualitative_matches = {}
    for domain, pattern in DISCOVERY.items():
        found = re.search(pattern, text, re.I)
        if found:
            mentions.add(domain)
            qualitative_matches[domain] = found
    # Categorical rules require explicit phrases; bare domain mentions are not values.
    for match in re.finditer(r'\b(?:no\s+(?:prior\s+)?falls?|denies\s+(?:any\s+)?falls?)\b', text, re.I):
        rows.append(('falls', 'no_falls_documented', None, 'candidate_value', match.start(), match.end(), match.group(), 'explicit_fall_negation'))
    for match in re.finditer(r'\b(?:history\s+of\s+falls?|[1-9]\d*\s+falls?\s+(?:in|over|during)\s+(?:the\s+)?(?:past|last))\b', text, re.I):
        before = _context(text,match.start())
        after = text[match.end():match.end()+25]
        uncertain = bool(re.search(r'\b(?:denies|denied|no|without)\s*$',before,re.I) or
                         re.match(r'\s*(?:denied|uncertain|unclear)\b',after,re.I))
        rows.append(('falls', 'falls_documented', None,
                     'negated_or_uncertain_context' if uncertain else 'candidate_value',
                     match.start(), match.end(), match.group(), 'explicit_fall_history'))
    for match in re.finditer(r'(?:\bpolypharmacy\s*[>:≥]\s*\d+\s*(?:med(?:ication)?s?)?|[>:≥]\s*\d+\s*(?:med(?:ication)?s?)\b)', text, re.I):
        rows.append(('polypharmacy', match.group(), None, 'candidate_value', match.start(), match.end(), match.group(), 'explicit_medication_threshold'))
    valued_domains = {row[0] for row in rows}
    for domain, found in qualitative_matches.items():
        if domain not in valued_domains:
            rows.append((domain,None,None,'mention_only',found.start(),found.end(),found.group(),'domain_mention'))
    return rows, mentions


def resolve_evidence(rows):
    """Conflicting eligible values stay ambiguous; historical values never win."""
    result = []
    by_domain = defaultdict(list)
    for row in rows:
        by_domain[row[0]].append(row)
    for domain, group in by_domain.items():
        current = [r for r in group if r[3] == 'candidate_value']
        distinct = {(r[1], r[2]) for r in current}
        for row in group:
            status = ('ambiguous_conflicting_values' if row in current and len(distinct) > 1 else
                      'extracted' if row in current else row[3])
            result.append((*row[:3], status, *row[4:]))
    return result


def reconstruct_fragments(rows, line_start=1, separator='\n'):
    """Rows are (source ordinal, numeric LINE, raw LINE, text).

    A repeated identical LINE is de-duplicated; conflicting or missing LINEs
    are rejected. Sortable source-order inversions and gaps are audited separately.
    """
    reasons = []
    if any(row[3] is None for row in rows): reasons.append('missing_fragment_text')
    if any(row[1] is None for row in rows): reasons.append('missing_or_nonnumeric_line')
    by_line = defaultdict(set)
    for row in rows:
        if row[1] is not None: by_line[row[1]].add(row[3])
    seen_fragments = set()
    ordered = []
    for row in sorted(rows):
        fragment = (row[1],row[3])
        if row[1] is not None and fragment not in seen_fragments:
            ordered.append(row[1])
        seen_fragments.add(fragment)
    quality = line_quality({n:len(texts) for n,texts in by_line.items()},ordered,
                           sum(row[1] is not None for row in rows),line_start)
    if quality['conflicting_lines']: reasons.append('conflicting_line_text')
    if quality['no_valid_lines']: reasons.append('no_valid_lines')
    quality['review_warnings'] = []
    if quality['missing_line_positions'] or quality['unexpected_first_line']: quality['review_warnings'].append('line_gap_or_start')
    if quality['out_of_order']: quality['review_warnings'].append('source_order_sorted_by_line')
    text = None if reasons else separator.join(next(iter(by_line[n])) for n in sorted(by_line))
    return text, reasons, quality


def run(root, output, config, patient_key='pat_id', review_callback=None):
    """Independent mode; leaves all original audit and predictor outputs untouched."""
    settings = config.get('ga_extraction', {})
    notes_settings = validate_settings(config)
    type_patterns = _patterns(settings, 'note_type_patterns', DEFAULT_TYPE)
    template_patterns = _patterns(settings, 'template_patterns', DEFAULT_TEMPLATE)
    join = settings.get('fragment_join', 'newline')
    if join not in {'newline', 'space', 'none'}:
        raise PipelineError('ga_extraction.fragment_join must be newline, space, or none.')
    validated_denominators = settings.get('validated_denominators', {})
    if not isinstance(validated_denominators,dict) or any(
        key not in INSTRUMENTS or not isinstance(values,list) or
        any(not isinstance(value,int) or isinstance(value,bool) or value<1 for value in values)
        for key,values in validated_denominators.items()):
        raise PipelineError('ga_extraction.validated_denominators must map known instruments to positive integer lists.')
    separator = {'newline':'\n', 'space':' ', 'none':''}[join]
    identity_verified = bool(notes_settings.get('note_key_verified') and notes_settings.get('note_key_fields'))
    reference, invalid_reference = reference_days(root, config, patient_key)
    path = find_workbook(root, config, type('LocalReport', (), {'data': {'missing_files': [], 'files_found': {} }})())
    summary = Counter()
    coverage = defaultdict(Counter)
    selection = []
    extracted = []
    review = []
    note_mentions = {}
    date_cache = {}
    def cached_note_date(raw):
        key = (type(raw).__name__,str(raw))
        if key not in date_cache:
            if len(date_cache)>=8192: date_cache.clear()
            date_cache[key] = _timestamp_and_day(raw,config)
        return date_cache[key]
    with TemporaryDirectory(prefix='.ga-stage-', dir=output) as stage:
        with closing(sqlite3.connect(str(Path(stage)/'ga.sqlite'))) as db:
            db.execute('PRAGMA temp_store=FILE')
            db.execute('CREATE TABLE fragments (ordinal INTEGER, group_key TEXT, patient TEXT, day TEXT, note_type TEXT, flag TEXT, line INTEGER, raw_line TEXT, text TEXT, encounter TEXT, author TEXT, note_id TEXT, note_csn TEXT, note_timestamp TEXT, pat_id TEXT, mrn TEXT, mrn_status TEXT, department TEXT)')
            with _rows(path, 'notes', config) as (source_sheet, header_row, headers, stream):
                _, mapping, ambiguous, absent = schema_mapping(headers, config)
                if ambiguous:
                    raise PipelineError('Ambiguous Notes columns: '+', '.join(ambiguous))
                required = {'line','date','text','anchor_flag'}
                if required-set(mapping):
                    raise PipelineError('Notes missing required GA columns: '+', '.join(sorted(required-set(mapping))))
                key_fields = notes_settings.get('note_key_fields', [])  # Explicit export granularity only.
                requested_key_fields = list(key_fields)
                unavailable_key_fields = [k for k in key_fields if k not in mapping]
                if identity_verified and any(k not in mapping for k in key_fields):
                    raise PipelineError('Verified Notes grouping key field missing: '+', '.join(k for k in key_fields if k not in mapping))
                if not identity_verified and any(k not in mapping for k in key_fields):
                    key_fields = []
                mrn_mapping = _discover(headers, 'notes', config)  # Audit both IDs regardless of linkage choice.
                patient_col = mrn_mapping['mrn'] if patient_key == 'mrn' else mapping.get('patient')
                if patient_col is None:
                    raise PipelineError('Notes lacks a direct validated '+patient_key+' column; GA extraction will not guess patient linkage.')
                encounter_col = mapping.get('encounter')
                author_override = config.get('columns',{}).get('notes',{}).get('author')
                author_candidates = [author_override] if author_override else ['AUTHOR_NAME','NOTE_AUTHOR','NOTE_AUTHOR_NAME','AUTHOR']
                author_matches = [i for i,h in enumerate(headers) if str(h).casefold() in {a.casefold() for a in author_candidates}]
                if len(author_matches)>1:
                    raise PipelineError('Multiple candidate Notes author columns; configure columns.notes.author.')
                author_col = author_matches[0] if author_matches else None
                if author_override and author_col is None:
                    raise PipelineError('Configured columns.notes.author is absent.')
                department_override = config.get('columns',{}).get('notes',{}).get('department')
                department_aliases = [department_override] if department_override else ['SERVICE_DEPARTMENT','DEPARTMENT_NAME','SERVICE_DEPARTMENT_NAME']
                department_matches = [i for i,h in enumerate(headers) if normalize(h) in {normalize(a) for a in department_aliases}]
                if len(department_matches)>1 or (department_override and not department_matches):
                    raise PipelineError('Missing/ambiguous Notes department column; configure columns.notes.department.')
                department_col = department_matches[0] if department_matches else None
                resolved_schema = {
                    'patient_linkage': {'logical_key':patient_key,'source_column':headers[patient_col]},
                    'note_reconstruction': {'logical_keys':key_fields,'source_columns':[headers[mapping[k]] for k in key_fields],
                        'requested_keys':requested_key_fields,'unavailable_key_fields':unavailable_key_fields,
                        'status':'configured_key_unavailable' if unavailable_key_fields else 'explicit_candidate_key' if key_fields else 'unconfigured_no_grouping'},
                    'cross_patient_consistency': {
                        'mrn_column':headers[mrn_mapping['mrn']] if mrn_mapping['mrn'] is not None else None,
                        'mrn_mapping_status':mrn_mapping['status'],
                        'pat_id_column':headers[mapping['patient']] if 'patient' in mapping else None},
                    'department_column':headers[department_col] if department_col is not None else None,
                    'department_provenance':'unverified; review evidence, never a grouping key',
                    'legacy_patient_key_meaning':'columns.notes.patient (default PAT_ID); independent of --patient-key',
                }
                (output/'ga_linkage_schema.json').write_text(json.dumps(resolved_schema,indent=2),encoding='utf-8')
                # Only logical names/column headers are printed, never patient values.
                print('Patient linkage: '+patient_key+' -> '+str(headers[patient_col]))
                print('Note reconstruction: '+str(resolved_schema['note_reconstruction']))
                print('Cross-patient consistency columns: '+str(resolved_schema['cross_patient_consistency']))
                for ordinal, row in enumerate(stream):
                    if not any(missing_value(v) is not None for v in row):
                        continue
                    if len(row)>len(headers) and any(missing_value(v) is not None for v in row[len(headers):]):
                        raise PipelineError('Notes row extends beyond configured header width.')
                    pat_id = _id(_value(row,mapping.get('patient')))
                    mrn,mrn_status,_ = _clean_mrn(_value(row,mrn_mapping['mrn']))
                    if mrn is not None:
                        for alternative in mrn_mapping['alternatives']:
                            other = _clean_mrn(_value(row,alternative))[0]
                            if other is not None and other != mrn:
                                mrn = None; mrn_status = 'conflicting_mrn_columns'
                                summary['conflicting_mrn_rows'] += 1
                                break
                    if mrn_mapping['mrn'] is None: mrn_status = mrn_mapping['status']
                    patient = mrn if patient_key=='mrn' else pat_id
                    department = missing_value(_value(row,department_col))
                    if department is not None: department = department.strip()
                    timestamp,day = cached_note_date(_value(row,mapping['date']))
                    kind = missing_value(_value(row,mapping.get('note_type')))
                    flag = anchor_status(missing_value(_value(row,mapping['anchor_flag'])))
                    raw_line = missing_value(_value(row,mapping['line']))
                    content = missing_value(_value(row,mapping['text']))
                    encounter = _id(_value(row,encounter_col))
                    author = missing_value(_value(row,author_col))
                    note_id = _id(_value(row,mapping.get('note_id')))
                    note_csn = _id(_value(row,mapping.get('note_csn')))
                    parts = []
                    for field in key_fields:
                        raw = _value(row,mapping[field])
                        parts.append(timestamp if field == 'date' else _id(raw) if field in {'patient','note_id','note_csn','encounter'} else missing_value(raw))
                    # Only explicit key fields define groups. Metadata differences remain visible.
                    group_key = json.dumps(parts,ensure_ascii=False) if key_fields and all(p is not None for p in parts) else None
                    db.execute('INSERT INTO fragments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (ordinal,group_key,patient,day,kind,flag,line_number(raw_line),raw_line,content,encounter,author,note_id,note_csn,timestamp,pat_id,mrn,mrn_status,department))
                    summary['source_fragment_rows'] += 1
            db.commit()
            grouping_stats = audit_grouping(db,output,{
                'mrn':mrn_mapping['mrn'] is not None,'pat_id':'patient' in mapping,
                'note_csn':'note_csn' in mapping,'note_id':'note_id' in mapping},
                path.name,source_sheet,header_row)
            metadata_rows=[]
            summary['ungroupable_fragment_rows'] = db.execute('SELECT COUNT(*) FROM fragments WHERE group_key IS NULL').fetchone()[0]
            _csv(output/'ga_ungroupable_fragments_SERDA_ONLY.csv',
                 ['source_row_position_zero_based','patient_identifier_SERDA_ONLY','note_day',
                  'note_id_SERDA_ONLY','note_csn_SERDA_ONLY','reason'],
                 ([ordinal,patient,day,note_id,note_csn,'missing_verified_group_key_component']
                  for ordinal,patient,day,note_id,note_csn in db.execute(
                      'SELECT ordinal,patient,day,note_id,note_csn FROM fragments WHERE group_key IS NULL')))
            for counts in db.execute('''SELECT COUNT(DISTINCT patient),COUNT(DISTINCT note_id),
                       COUNT(DISTINCT day),COUNT(DISTINCT note_type),COUNT(DISTINCT encounter),
                       COUNT(DISTINCT author),COUNT(*)-COUNT(DISTINCT line)
                       FROM fragments WHERE note_csn IS NOT NULL GROUP BY note_csn'''):
                summary['csn_groups'] += 1
                for index,name in enumerate(['multiple_patients','multiple_note_ids','multiple_dates',
                                              'multiple_note_types','multiple_encounters','multiple_authors']):
                    summary['csn_'+name] += counts[index]>1
                summary['csn_repeated_line_groups'] += counts[6]>0
            db.execute('CREATE INDEX ga_key ON fragments(group_key,ordinal)')
            groups = db.execute('SELECT group_key,COUNT(*),COALESCE(SUM(LENGTH(text)),0) FROM fragments WHERE group_key IS NOT NULL GROUP BY group_key')
            for key, size, chars in groups:
                summary['candidate_groups'] += 1
                note_ref = 'group_' + str(summary['candidate_groups'])
                reasons = group_global_blocks(db,key)
                warnings=[]; manual_review=[]; metadata={}
                if size > notes_settings.get('max_fragments_per_note',100000) or chars > notes_settings.get('max_note_characters',5000000):
                    reasons.append('group_size_limit')
                    rows = []
                else:
                    rows = db.execute('SELECT ordinal,patient,day,note_type,flag,line,raw_line,text,encounter,author,note_id,note_csn,note_timestamp,pat_id,mrn,mrn_status,department FROM fragments WHERE group_key=? ORDER BY ordinal',(key,)).fetchall()
                def single(index):
                    values = {r[index] for r in rows if r[index] is not None}
                    return next(iter(values)) if len(values)==1 else None
                patient, day, kind, flag = (single(i) for i in [1,2,3,4])
                if rows:
                    if not identity_verified: reasons.append('identity_unverified_candidate_group_only')
                    meta_hard,warnings,manual_review,metadata = metadata_evidence(rows,department_col is not None)
                    reasons.extend(meta_hard)
                    manual_review.extend(group_global_review(db,key))
                    if patient is None or any(r[1] is None for r in rows): reasons.append('unlinked_patient')
                    if day is None or any(r[2] is None for r in rows): reasons.append('missing_note_date')
                    text, fragment_reasons, quality = reconstruct_fragments(
                        [(r[0],r[5],r[6],r[7]) for r in rows],
                        notes_settings.get('line_start',1),separator)
                    reasons.extend(fragment_reasons)
                    warnings.extend(quality['review_warnings'])
                    if 'line_gap_or_start' in quality['review_warnings']: manual_review.append('line_gap_or_start')
                    if quality['duplicate_line_rows']: summary['duplicate_line_rows'] += quality['duplicate_line_rows']
                    if reasons: text = None
                else: text = None
                metadata_rows.append([note_ref,key,json.dumps(metadata,ensure_ascii=False),';'.join(warnings),';'.join(manual_review),';'.join(reasons)])
                if reasons: summary['reconstruction_failures'] += 1
                else: summary['reconstructed_notes'] += 1
                dates = reference.get(patient,set()) if patient else set()
                date_match = bool(day and day in dates)
                type_match = bool(kind and any(p.search(kind) for p in type_patterns))
                template_match = bool(text and any(p.search(text) for p in template_patterns))
                evidence = ';'.join(name for name,yes in [('anchor_yes',flag=='Yes'),('reference_date',date_match),('note_type',type_match),('ga_template',template_match)] if yes)
                if review_callback is not None:
                    review_callback(dict(key=key, rows=rows, reasons=reasons, warnings=warnings, manual_review=manual_review, metadata=metadata,
                        patient=patient, day=day, kind=kind, flag=flag,
                        reference_days=sorted(dates), invalid_reference=patient in invalid_reference,
                        source_file=path.name, source_sheet=source_sheet, header_row=header_row,
                        separator=separator, line_start=notes_settings.get('line_start',1)))
                if not identity_verified: status = 'excluded_identity_unverified'
                elif reasons: status = 'excluded_reconstruction'
                elif manual_review: status = 'pending_reconstruction_review'
                elif patient is None or not dates or patient in invalid_reference: status = 'excluded_linkage_or_reference'
                elif len(dates)>1: status = 'ambiguous_multiple_reference_anchors'
                elif not date_match or flag=='No': status = 'excluded_not_anchor_ga'
                elif flag=='Yes' and type_match and template_match: status = 'confirmed_by_configured_rules'
                elif flag=='Yes' and (type_match or template_match): status = 'candidate_ga_note'
                else: status = 'excluded_insufficient_ga_evidence'
                summary[status] += 1
                selection.append([note_ref,key,patient,day,kind,flag,status,evidence,';'.join(reasons),size,join])
                if status not in {'confirmed_by_configured_rules','candidate_ga_note'} or text is None:
                    if status.startswith('ambiguous') or status in {'excluded_reconstruction','excluded_identity_unverified','pending_reconstruction_review'}:
                        review.append([note_ref,patient,day,None,status,';'.join(reasons+manual_review),None,None])
                    continue
                if review_callback is not None:
                    continue  # Prepare reviews reconstruction only; never run the extractor.
                values, mentions = extract_text(text,validated_denominators)
                note_mentions[note_ref] = mentions
                resolved = resolve_evidence(values)
                by_domain = defaultdict(list)
                for item in resolved: by_domain[item[0]].append(item)
                for domain, items in by_domain.items():
                    for instrument,value,denominator,state,start,end,evidence_text,pattern in items:
                        record = [note_ref,patient,day,status,instrument,value,denominator,state,pattern,start,end,evidence_text]
                        extracted.append(record)
                        if state!='extracted': review.append([note_ref,patient,day,instrument,state,pattern,start,end])
                for domain in mentions - set(by_domain):
                    review.append([note_ref,patient,day,domain,'mention_without_supported_value','qualitative_mention',None,None])
    _csv(output/'ga_note_metadata_audit_SERDA_ONLY.csv',
         ['note_ref','candidate_key','metadata_evidence_json','warnings','manual_review_reasons','hard_blocks'],metadata_rows)
    # More than one rule-eligible note at a patient/anchor date is an unresolved
    # selection, even when each note separately passed the configured rules.
    eligible_statuses = {'confirmed_by_configured_rules','candidate_ga_note'}
    by_patient_day = Counter((row[2],row[3]) for row in selection if row[6] in eligible_statuses)
    ambiguous_refs = set()
    for row in selection:
        if row[6] in eligible_statuses and by_patient_day[row[2],row[3]]>1:
            summary[row[6]] -= 1
            row[6] = 'ambiguous_multiple_ga_notes'
            summary['ambiguous_multiple_ga_notes'] += 1
            ambiguous_refs.add(row[0])
            review.append([row[0],row[2],row[3],None,'ambiguous_multiple_ga_notes',
                           'multiple_rule_eligible_notes_same_patient_day',None,None])
    for row in extracted:
        if row[0] in ambiguous_refs:
            row[3] = 'ambiguous_multiple_ga_notes'
            row[7] = 'ambiguous_note_selection'
    extraction_status = defaultdict(list)
    for entry in extracted:
        extraction_status[entry[0],entry[4]].append(entry[7])
    for row in selection:
        if row[6] not in eligible_statuses: continue
        note_ref = row[0]
        for domain in note_mentions.get(note_ref,set()):
            coverage[domain]['notes_mentioned'] += 1
            statuses = extraction_status[note_ref,domain]
            if 'extracted' in statuses: coverage[domain]['notes_with_extracted_value'] += 1
            if any(state!='extracted' for state in statuses) or not statuses:
                coverage[domain]['notes_with_unresolved_match'] += 1
    _csv(output/'ga_note_selection_audit.csv',
         ['note_ref','verified_group_key_SERDA_ONLY','patient_identifier_SERDA_ONLY','note_day','note_type','anchor_flag','selection_status','selection_evidence','reconstruction_issues','fragment_rows','fragment_join_policy'],selection)
    _csv(output/'ga_extracted_scores.csv',
         ['note_ref','patient_identifier_SERDA_ONLY','note_day','note_selection_status','domain_or_instrument','value','denominator','extraction_status','pattern','start_offset','end_offset','matched_evidence_SERDA_ONLY'],extracted)
    _csv(output/'ga_extraction_review_queue.csv',
         ['note_ref','patient_identifier_SERDA_ONLY','note_day','domain_or_instrument','review_reason','pattern_or_issues','start_offset','end_offset'],review)
    fields = list(INSTRUMENTS)+list(DISCOVERY)
    eligible = summary['confirmed_by_configured_rules']+summary['candidate_ga_note']
    _csv(output/'ga_domain_coverage.csv',
         ['field','eligible_notes_denominator','notes_mentioned','notes_with_extracted_value','notes_with_unresolved_match'],
         ([name,eligible,coverage[name]['notes_mentioned'],coverage[name]['notes_with_extracted_value'],coverage[name]['notes_with_unresolved_match']] for name in fields))
    lines = ['# GA extraction feasibility audit','',
             'SENSITIVE SERDA OUTPUT. No accuracy, precision, recall, F1, clinical correctness or frailty label is claimed.',
             'All coverage denominators are confirmed plus candidate GA notes; only configured rule evidence determines selection.',
             'Instrument mentions are not diagnoses or current scores. Review patient-level outputs inside SERDA only.','',
             f'Patient linkage key: {patient_key}. Candidate note key fields: {key_fields}. Identity locally verified: {identity_verified}. Fragment join: {join}.',
             'Review ga_linkage_schema.json and ga_note_grouping_summary.csv for resolved columns and NOTE_CSN versus (MRN, NOTE_CSN) row-partition comparison. Equal partitions do not prove note identity or completeness.',
             'Schema: actual headers are recorded in ga_schema_validation.json; configurable through files.notes, sheets.notes, header_rows.notes and columns.notes.',
             f'Reconstructed notes: {summary["reconstructed_notes"]}; reconstruction failures: {summary["reconstruction_failures"]}; ungroupable fragment rows: {summary["ungroupable_fragment_rows"]}.',
             f'NOTE_CSN groups: {summary["csn_groups"]}; spanning multiple note IDs: {summary["csn_multiple_note_ids"]}; spanning multiple patients: {summary["csn_multiple_patients"]}; repeated LINE groups: {summary["csn_repeated_line_groups"]}. These are structural flags, not proof of note identity.',
             f'Confirmed by configured rules: {summary["confirmed_by_configured_rules"]}; candidate: {summary["candidate_ga_note"]}; eligible denominator: {eligible}.',
             f'Patient-level review queue entries: {len(review)}. Selection/exclusion counts:',
             'Anchor=Yes and exact Demographics date are necessary but not sufficient. Multiple Demographics anchor days remain ambiguous.',
             'Note-key verification is a local export contract; contiguous LINEs cannot prove a missing terminal fragment does not exist.',
             'No real-data evaluation or human-reference annotation is implied. Erika should verify key granularity, author/type metadata, GA templates, fragment joining and scoring formats before treating fields as final.']
    lines.extend(f'- {name}: {count} note groups.' for name,count in sorted(summary.items())
                 if name in {'confirmed_by_configured_rules','candidate_ga_note','ambiguous_multiple_ga_notes',
                             'ambiguous_multiple_reference_anchors','excluded_reconstruction',
                             'excluded_identity_unverified','pending_reconstruction_review','excluded_linkage_or_reference',
                             'excluded_not_anchor_ga','excluded_insufficient_ga_evidence'})
    for field in fields:
        counts=coverage[field]
        lines.append(f'- {field}: mentioned {counts["notes_mentioned"]}/{eligible}; extracted {counts["notes_with_extracted_value"]}/{eligible}; unresolved {counts["notes_with_unresolved_match"]}/{eligible}.')
    (output/'ga_extraction_summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (output/'ga_schema_validation.json').write_text(json.dumps({
        'note_columns':headers,'note_mapping':{k:headers[i] for k,i in mapping.items()},
        'direct_patient_column':headers[patient_col],
        'author_column':headers[author_col] if author_col is not None else None,
        'missing_optional_fields':absent,'patient_key':patient_key,
        'candidate_note_key_fields':key_fields,'note_identity_verified':identity_verified,
        'resolved_linkage_and_grouping':resolved_schema,'grouping_comparison':grouping_stats,
        'selection_counts':dict(summary)},
        indent=2),encoding='utf-8')
    for name in ['source_fragment_rows','ungroupable_fragment_rows','candidate_groups',
                 'reconstructed_notes','reconstruction_failures','confirmed_by_configured_rules',
                 'candidate_ga_note','ambiguous_multiple_reference_anchors','conflicting_mrn_rows']:
        summary[name] += 0
    summary['identity_verified'] = identity_verified
    return dict(summary)
