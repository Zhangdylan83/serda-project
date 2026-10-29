"""Explicit GA input contracts. CSV identifiers are read as strings, never inferred."""
import csv
import re
from collections import defaultdict
from pathlib import Path
from .core import PipelineError


def read_csv(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not required.issubset(reader.fieldnames or []):
            raise PipelineError('GA input CSV lacks required contract columns.')
        return [{k: (v or '').strip() for k, v in row.items() if k is not None} for row in reader]


def day(value):
    from datetime import date
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise PipelineError('GA master dates must use YYYY-MM-DD.')
    try: date.fromisoformat(value)
    except ValueError: raise PipelineError('GA master contains an invalid date.') from None
    return value


def master(config, patient_key):
    settings = config.get('ga_input', {})
    source = settings.get('anchor_source', 'demographics_reference')
    if source not in {'demographics_reference', 'approved_master'}:
        raise PipelineError('Unknown ga_input.anchor_source.')
    if source == 'demographics_reference': return None
    if not settings.get('cohort_anchor_file'):
        raise PipelineError('approved_master requires ga_input.cohort_anchor_file.')
    rows = read_csv(settings['cohort_anchor_file'], {'patient_key','patient_key_type','anchor_date','eligible','confirmation_status','source','reviewer'})
    reference = defaultdict(set); seen = set()
    for row in rows:
        if not row['patient_key'] or row['patient_key_type'] != patient_key:
            raise PipelineError('GA master patient key missing or key type differs from CLI.')
        if row['patient_key'] in seen:
            raise PipelineError('Duplicate/conflicting patient rows in GA master; resolve explicitly.')
        seen.add(row['patient_key'])
        if row['eligible'] not in {'yes','no'} or row['confirmation_status'] != 'confirmed' or not row['source'] or not row['reviewer']:
            raise PipelineError('GA master requires explicit eligibility, confirmation, source and reviewer.')
        if row['eligible'] == 'yes': reference[row['patient_key']].add(day(row['anchor_date']))
    if not reference: raise PipelineError('GA master has no confirmed eligible patients.')
    return reference, set()


def targets(config, patient_key):
    path = config.get('ga_input', {}).get('target_note_manifest')
    if not path: return None
    rows = read_csv(path, {'patient_key','patient_key_type','anchor_date','target_note_key','selection_source','confirmation_status','reviewer'})
    if not rows: raise PipelineError('Target manifest is empty; no confirmed targets supplied.')
    seen = set(); keys = set()
    for row in rows:
        if not row['patient_key'] or row['patient_key_type'] != patient_key or not row['target_note_key']:
            raise PipelineError('Target manifest requires direct patient and document keys matching CLI.')
        day(row['anchor_date'])
        pair = (row['patient_key'], row['anchor_date'])
        if pair in seen or row['target_note_key'] in keys:
            raise PipelineError('Duplicate/multiple target mappings; resolve the manifest before extraction.')
        seen.add(pair); keys.add(row['target_note_key'])
        if row['confirmation_status'] != 'confirmed' or not row['selection_source'] or not row['reviewer']:
            raise PipelineError('Target mappings require confirmation, selection source and reviewer.')
    return rows
