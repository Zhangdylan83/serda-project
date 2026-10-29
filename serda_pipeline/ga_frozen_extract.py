"""Read ONLY selected frozen notes (or explicitly curated JSONL); never Excel."""
import argparse
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from .ga_schema_engine import extract, schema_leaves, SCHEMA_PATH
from .ga_schema_review import render


class InputError(ValueError): pass


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def table(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def save(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def yes(value):return value is True or isinstance(value,str) and value.strip().lower()=='yes'


def validate_record(record):
    text=record.get('text');rows=record.get('source_rows')
    if not isinstance(text,str) or not text.strip() or not isinstance(rows,list) or not rows:
        raise InputError('Selected note lacks nonempty frozen text or source provenance.')
    for r in rows:
        a,b=r.get('text_start'),r.get('text_end')
        if type(a) is not int or type(b) is not int or not 0<=a<=b<=len(text) or text[a:b]!=r.get('original_text') or type(r.get('source_excel_row')) is not int:
            raise InputError('Frozen source mapping does not match unchanged text.')
    if not record.get('sample_id') or not yes(record.get('identity_approved')) or not yes(record.get('reconstruction_approved')):
        raise InputError('Each note requires existing identity and reconstruction approval; no automatic approval is allowed.')
    # Target confirmation is recorded separately, never a prerequisite for this development mode.
    return record


def load_package(package):
    package=Path(package).resolve(); frozen=read(package/'run_manifest.json'); manifest=table(package/'sample_manifest.csv')
    if not manifest:raise InputError('Frozen package has no selected samples.')
    membership=[(r['sample_id'],r['internal_note_id']) for r in manifest]
    if membership!=[tuple(r) for r in frozen.get('sample_membership',[])]:raise InputError('Frozen sample membership or order changed.')
    if len({r[0] for r in membership})!=len(membership):raise InputError('Duplicate sample IDs.')
    originals=frozen.get('frozen_sample_rows',[])
    if len(originals)!=len(manifest):raise InputError('Missing frozen sample metadata.')
    allowed={'identity_approved','reconstruction_approved','target_ga_approved','reviewer','review_comment'}
    records=[];hashes={'run_manifest.json':digest(package/'run_manifest.json'),'sample_manifest.csv':digest(package/'sample_manifest.csv')}
    for m,original in zip(manifest,originals):
        if any(str(original.get(k) or '')!=str(m.get(k) or '') for k in original if k not in allowed):raise InputError('Frozen sample metadata changed.')
        internal=m['internal_note_id']
        if not re.fullmatch(r'[a-f0-9]{64}',internal):raise InputError('Invalid frozen candidate identifier.')
        path=package/'candidates'/(internal+'.json')
        if not path.resolve().is_relative_to(package):raise InputError('Candidate path escapes source package.')
        checksum=digest(path)
        if checksum!=frozen.get('sample_files',{}).get(internal):raise InputError('Frozen candidate checksum mismatch.')
        item=read(path)
        if item.get('internal_note_id')!=internal:raise InputError('Frozen candidate identity mismatch.')
        if item.get('hard_blocks'):raise InputError('Selected frozen note has unresolved input blocks; resolve in a separate reviewed package.')
        if not m.get('reviewer','').strip():raise InputError('Existing sample approval requires a reviewer.')
        record=dict(sample_id=m['sample_id'],internal_note_id=internal,text=item.get('text'),source_rows=item.get('source_rows'),
                    identity_approved=yes(m.get('identity_approved')),reconstruction_approved=yes(m.get('reconstruction_approved')),
                    target_confirmed=yes(m.get('target_ga_approved')),target_confirmation_basis='source package manual approval',
                    source_package_candidate='candidates/'+internal+'.json')
        records.append(validate_record(record));hashes[record['source_package_candidate']]=checksum
    return records,hashes


def load_curated(path):
    # Future curated adapter: no note classifier, implicit patient/date linkage or Excel access.
    records=[]
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            if line.strip():
                record=json.loads(line)
                if not yes(record.get('target_confirmed')) or not record.get('confirmation_source'):
                    raise InputError('Curated records require explicit target confirmation and its source.')
                records.append(validate_record(record))
    if not records or len({r['sample_id'] for r in records})!=len(records):raise InputError('Curated samples missing or duplicated.')
    return records,{'curated_jsonl':digest(path)}


def load_config(path):
    cfg=yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(cfg,dict) or cfg.get('schema_extraction',{}).get('engine')!='ga_schema_v1':raise InputError('Configuration must select schema_extraction.engine: ga_schema_v1.')
    if cfg.get('notes',{}).get('note_key_fields')!=['note_csn'] or cfg['notes'].get('note_key_verified') is not False:raise InputError('Tracked exploratory document-key contract changed.')
    columns=cfg.get('columns',{}).get('notes',{})
    if columns.get('mrn')!='PAT_MRN_ID' or columns.get('note_csn')!='NOTE_CSN_ID':raise InputError('MRN/document column contract invalid.')
    return cfg


def write_csv(path,rows,fields):
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def run(source,output,config_path,curated=False):
    source=Path(source).resolve();output=Path(output).resolve();repo=Path(__file__).resolve().parent.parent
    if output.exists():raise InputError('Output must be a new directory; previous runs are immutable.')
    if output==repo or output.is_relative_to(repo) or repo.is_relative_to(output):raise InputError('Output must be outside the code repository.')
    source_dir=source.parent if curated else source
    if output==source_dir or output.is_relative_to(source_dir) or source_dir.is_relative_to(output):raise InputError('Output must be separate from the source package/directory.')
    cfg=load_config(config_path);schema,leaves=schema_leaves();Draft202012Validator.check_schema(schema)
    records,input_hashes=load_curated(source) if curated else load_package(source)
    # All input checks happen before any output is created. No workbook imports or reads.
    results=[extract(r['text'],r['source_rows']) for r in records]
    output.mkdir(parents=True,exist_ok=False)
    with (output/'ga_features.jsonl').open('w',encoding='utf-8') as clinical_file,(output/'extraction_evidence.jsonl').open('w',encoding='utf-8') as audit_file:
        for i,(record,(clinical,audit)) in enumerate(zip(records,results),1):
            clinical_file.write(json.dumps(clinical,ensure_ascii=False)+'\n')
            audit_file.write(json.dumps(dict(record_index=i,sample_id=record['sample_id'],identity_approved=record['identity_approved'],
                reconstruction_approved=record['reconstruction_approved'],target_confirmed=record['target_confirmed'],
                target_confirmation_basis=record.get('target_confirmation_basis',record.get('confirmation_source')),fields=audit),ensure_ascii=False)+'\n')
    states=['extracted','not_found','unsupported','ambiguous','conflicting']
    coverage=[]
    for path in leaves:
        counts=Counter(f['extraction_status'] for _,audit in results for f in audit if f['field_path']==path)
        coverage.append(dict(field_path=path,notes_denominator=len(records),**{s:counts[s] for s in states}))
    write_csv(output/'field_coverage.csv',coverage,['field_path','notes_denominator']+states)
    counts=Counter(f['extraction_status'] for _,audit in results for f in audit)
    write_csv(output/'extraction_summary.csv',[dict(metric=k,count=v) for k,v in dict(notes=len(records),field_note_pairs=len(records)*len(leaves),**{s:counts[s] for s in states}).items()],['metric','count'])
    _,support=extract('')
    write_csv(output/'support_registry.csv',[dict(field_path=f['field_path'],support='explicit_patterns_only' if f['rule_ids'] else 'unsupported',rule_ids=';'.join(f['rule_ids'])) for f in support],['field_path','support','rule_ids'])
    render(output/'review.html',records,results)
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError):commit='unavailable'
    save(output/'run_manifest.json',dict(engine='ga_schema_v1',utc=datetime.now(timezone.utc).isoformat(),commit=commit,
        input_mode='clinically_curated' if curated else 'frozen_development_samples',source_hashes=input_hashes,
        source_code_sha256={name:digest(Path(__file__).parent/name) for name in ['ga_schema_engine.py','ga_frozen_extract.py','ga_schema_review.py']},
        config=cfg,config_sha256=digest(config_path),schema_sha256=digest(SCHEMA_PATH),
        record_order=[dict(record_index=i,sample_id=r['sample_id'],target_confirmed=r['target_confirmed'],target_confirmation_basis=r.get('target_confirmation_basis',r.get('confirmation_source'))) for i,r in enumerate(records,1)],
        outputs_sha256={p.name:digest(p) for p in output.iterdir() if p.is_file()},
        clinical_json_policy='Sparse objects: unresolved fields omitted, not clinical nulls. JSON validity is not clinical correctness.',
        clinical_validation='Not established. Rule coverage and software tests are not accuracy estimates.'))
    (output/'schema_snapshot.json').write_bytes(SCHEMA_PATH.read_bytes())
    return len(records),counts


def main():
    parser=argparse.ArgumentParser(description='CPU GA extraction from selected frozen text; never scans Excel.')
    src=parser.add_mutually_exclusive_group(required=True);src.add_argument('--package',type=Path);src.add_argument('--curated-jsonl',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path(__file__).resolve().parent.parent/'configs'/'serda_ga_erika.yaml')
    args=parser.parse_args()
    try:
        n,counts=run(args.package or args.curated_jsonl,args.output_dir,args.config,curated=args.curated_jsonl is not None)
    except Exception as exc:
        # No raw exception text from parsers/schema validators: it can contain PHI.
        print('GA extraction failed: '+(str(exc) if isinstance(exc,InputError) else type(exc).__name__+'; check package integrity, dependencies and configuration locally.'))
        return 2
    print('GA extraction completed: '+str(n)+' notes; '+str(counts['extracted'])+' extracted field values. No clinical accuracy claim.')
    return 0


if __name__=='__main__':raise SystemExit(main())
