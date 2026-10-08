"""Read-only Excel ingestion and aggregate diagnostics; no raw rows in logs."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .schema import normalize, SCHEMAS, STEMS, REQUIRED

class PipelineError(Exception):
    pass

class Report:
    def __init__(self):
        self.data = {'files_found': {}, 'missing_files': [], 'datasets': {}, 'completed_modules': [], 'failed_modules': [], 'issues': []}
    def issue(self, module, message):
        self.data['issues'].append({'module': module, 'message': message})
    def fail(self, module, message):
        self.data['failed_modules'].append({'module': module, 'reason': message})
    def save(self, out):
        (out / 'execution_report.json').write_text(json.dumps(self.data, indent=2, default=str), encoding='utf-8')

def parse_dates(series, config):
    missing = series.isna()
    numeric = pd.to_numeric(series, errors='coerce')
    serial = numeric.between(config['excel_date_min'], config['excel_date_max'])
    result = pd.Series(pd.NaT, index=series.index, dtype='datetime64[ns]')
    result.loc[serial] = pd.to_datetime(numeric.loc[serial], unit='D', origin='1899-12-30', errors='coerce')
    # Numeric values outside the supported Excel range are never guessed as epochs.
    text = ~missing & numeric.isna()
    result.loc[text] = pd.to_datetime(series.loc[text], errors='coerce', format='mixed', dayfirst=config['dayfirst'])
    return result, int((~missing & result.isna()).sum())

def load_dataset(key, root, config, report):
    specified = config.get('files', {}).get(key)
    candidates = [root / specified] if specified else [p for p in root.iterdir() if p.is_file() and not p.name.startswith('~$') and p.suffix.lower() in {'.xlsx','.xlsm','.xls'} and normalize(p.stem) == normalize(STEMS[key])]
    if not candidates or not candidates[0].exists():
        report.data['missing_files'].append(key)
        raise PipelineError('No matching Excel file; configure files with an exact filename if needed.')
    if len(candidates) != 1:
        raise PipelineError('Ambiguous file matches; set files.' + key + ' explicitly.')
    path = candidates[0]
    if path.resolve().parent != root.resolve():
        raise PipelineError('Configured source file must be directly inside data-dir.')
    report.data['files_found'][key] = path.name
    with pd.ExcelFile(path, engine='xlrd' if path.suffix.lower()=='.xls' else 'openpyxl') as book:
        report.data.setdefault('workbook_sheets', {})[key] = book.sheet_names
        sheet = config.get('sheets', {}).get(key)
        if sheet is None:
            if len(book.sheet_names) != 1:
                raise PipelineError('Multiple sheets; configure sheets.' + key + ' explicitly.')
            sheet = book.sheet_names[0]
        header_row = config.get('header_rows', {}).get(key, 0)
        headers = pd.read_excel(book, sheet_name=sheet, header=None, skiprows=header_row, nrows=1).iloc[0].tolist()
        if len({normalize(x) for x in headers}) != len(headers):
            raise PipelineError('Duplicate or normalization-colliding headers; resolve export or header_rows setting.')
        frame = pd.read_excel(book, sheet_name=sheet, header=header_row, dtype=str,
                              na_values=['NULL','null','(null)','None'], keep_default_na=False)
    frame = frame.replace(r'^\s*$', np.nan, regex=True)
    mapping, missing, ambiguous = {}, [], []
    overrides = config.get('columns', {}).get(key, {})
    for field, aliases in SCHEMAS[key].items():
        choices = [overrides[field]] if field in overrides else aliases
        matches = [c for c in frame.columns if normalize(c) in {normalize(a) for a in choices}]
        if len(matches)==1: mapping[field]=matches[0]
        elif len(matches)>1: ambiguous.append(field)
        else: missing.append(field)
    stats = {'real_columns': list(frame.columns), 'column_mapping': mapping, 'missing_columns': missing,
             'ambiguous_columns': ambiguous, 'unexpected_columns': [c for c in frame if c not in mapping.values()],
             'row_count': len(frame), 'duplicate_rows': int(frame.duplicated().sum()),
             'missingness': {c: float(frame[c].isna().mean()) for c in frame}, 'date_parsing_failures': {}}
    report.data['datasets'][key] = stats
    # Basic patient profiling remains available even when clinical fields fail mapping.
    if 'patient' in mapping:
        ids = frame[mapping['patient']].str.strip()
        stats['missing_patient_ids'] = int(ids.isna().sum())
        stats['unique_patients'] = int(ids.nunique())
    if ambiguous: raise PipelineError('Ambiguous columns: ' + ', '.join(ambiguous))
    absent = set(REQUIRED[key]) - set(mapping)
    if absent: raise PipelineError('Required columns missing: ' + ', '.join(sorted(absent)))
    data = pd.DataFrame({field:frame[col] for field,col in mapping.items()})
    data['patient'] = data['patient'].str.strip()
    stats['missing_patient_ids'] = int(data.patient.isna().sum())
    stats['unique_patients'] = int(data.patient.nunique())
    # Numeric IDs with decimal/scientific notation need a verified export, never silent coercion.
    malformed = data.patient.str.contains(r'^[0-9]+\.0+$|^[0-9.]+[eE][+-]?[0-9]+$', na=False)
    if malformed.any(): raise PipelineError('Patient IDs appear numeric-coerced; export IDs as text before linkage.')
    for field in ['anchor','contact','date','prior_date','birth']:
        if field in data:
            data[field], failures = parse_dates(data[field], config)
            stats['date_parsing_failures'][field] = failures
    report.data['completed_modules'].append('load_' + key)
    return data

# Separate dataset entry points keep schema contracts explicit.
def load_demographics(*args): return load_dataset('demographics', *args)
def load_comorbidities(*args): return load_dataset('comorbidities', *args)
def load_height_weight(*args): return load_dataset('height_weight', *args)
def load_labs(*args): return load_dataset('labs', *args)
def load_alcohol(*args): return load_dataset('alcohol', *args)
def load_smoking(*args): return load_dataset('smoking', *args)
def load_medications(*args): return load_dataset('medications', *args)
