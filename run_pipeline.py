"""Offline Windows/CPU entry point for real SERDA Excel exports."""
import argparse
from pathlib import Path
import sys
import yaml
from serda_pipeline.schema import STEMS


def write_reports(out, report, cohort_count=None, temporal=None):
    lines=['# Real-data EDA summary', '', 'Generated locally from the configured SERDA Excel files.',
           f'Cohort patients: {cohort_count if cohort_count is not None else "unavailable"}.', '',
           report.data.get('cohort_status', 'Cohort unavailable.'),
           'All event features use the configured look-back and anchor-day policy recorded in execution_report.json. Missing/unparseable event dates are excluded.',
           'Record counts indicate documentation availability, not absence of disease or exposure.', '', '## Dataset inventory']
    for key, stats in report.data['datasets'].items():
        lines.append(f'- {key}: {stats["row_count"]} rows; {stats.get("unique_patients", "unavailable")} unique patients; {stats["duplicate_rows"]} exact duplicate rows.')
    if 'notes' in report.data['datasets']:
        notes = report.data['datasets']['notes']
        lines.extend(['', '## Notes audit (eighth dataset)',
            'Notes is an audit only: no predictor inputs, labels, or cohort membership changed.',
            'Anchor=Yes clinical meaning remains unconfirmed. Note dates are compared against all original Demographics calendar dates.',
            f'Note identity verified locally: {notes.get("note_identity_verified_by_local_configuration", False)}. Unique reconstructed notes: {notes.get("unique_reconstructed_notes", "unavailable")}.',
            'Review notes_inventory.csv, notes_reconstruction_quality.csv, notes_patient_intersections.csv, notes_anchor_alignment_summary.csv and notes_multiple_anchor_summary.csv. Candidate groups are not validated notes.',
            'All patient audits and optional reconstructed text must stay inside SERDA.'])
    if report.data.get('mrn_audit_lines'):
        lines.extend([''] + report.data['mrn_audit_lines'])
    lines.extend(['','## Temporal findings'])
    for row in temporal or []:
        lines.append(f'- {row["dataset"]}: {row["lookback_records"]} look-back records; {row["post_anchor_records"]} post-anchor records; {row["unknown_date_records"]} records without valid dates.')
    lines.extend(['', '## Limitations', 'No frailty labels or modeling. Medication counts describe orders, not confirmed use. Lab units are absent in the reference schema, so numerical values are not pooled. Weight trajectories summarize observed patients and may reflect changing documentation coverage. Exact duplicates are reported and retained in record counts; unique entity counts are deduplicated.'])
    (out/'EDA_summary.md').write_text('\n'.join(lines),encoding='utf-8')
    quality=['# Data quality report','','See execution_report.json for headers, mappings, date parsing, linkage and module status.']
    for item in report.data['issues']: quality.append(f'- {item["module"]}: {item["message"]}')
    for item in report.data['failed_modules']: quality.append(f'- FAILED {item["module"]}: {item["reason"]}')
    for item in report.data['skipped_modules']: quality.append(f'- SKIPPED {item["module"]}: {item["reason"]}')
    (out/'data_quality_report.md').write_text('\n'.join(quality),encoding='utf-8')
    (out/'Data_Audit_Summary.md').write_text('\n'.join(lines + ['', '## Audit module status'] + quality[3:]),encoding='utf-8')
    slides=['# Slide-ready findings','',
      '## Slide 1 — Objectives and workflow','Describe structured EHR coverage, validate dates, characterize comorbidities and weight, and create patient-level features. Read-only Excel → schema checks → demographic cohort → temporal checks → real EDA → features.',
      '## Slide 2 — Inventory and coverage','Use dataset_inventory.csv, patient_coverage.csv, *_missingness.csv and *_records_per_patient_summary.csv. Dataset-specific loader failures are shown in execution_report.json.',
      '## Slide 3 — Temporal validation','Use temporal_summary.csv and figures/*_record_density.png. Post-anchor records are reported and excluded from features. Undated records are excluded. Smoking prior-status dates are separately audited.',
      '## Slide 4 — Comorbidities','Use icd10_record_frequency.csv, icd10_patient_frequency.csv and diagnosis_source_comparison.csv when available. Source categories are preserved exactly; verify Problem List and Encounter Diagnosis labels in the real output.',
      '## Slide 5 — Weight and BMI','Use measurement_unit_coverage.csv, weight_trajectory_monthly.csv, weight-change figures and feature_availability.csv when available. Six- and twelve-month changes compare pre-anchor observations to anchor-window weight.',
      '## Slide 6 — Unified features','Use patient_features.csv and feature_dictionary.csv. One row per selected cohort patient; unavailable module features are null and marked unavailable in the dictionary. No supervised modeling.', '', '## Execution-derived findings']
    slides.extend(lines[3:])
    (out/'slide_ready_findings.md').write_text('\n'.join(slides),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--config',type=Path,default=Path(__file__).with_name('config.yaml'))
    parser.add_argument('--cohort-anchor-policy', choices=['strict_timestamp','calendar_day','exclude_ambiguous_for_eda'])
    parser.add_argument('--anchor-day-policy', choices=['at_or_before_timestamp','pre_anchor_date_only'])
    parser.add_argument('--notes-audit-only', action='store_true', help='Audit Notes and original Demographics only; no cohort selection or clinical feature engineering.')
    parser.add_argument('--ga-extraction-only', action='store_true', help='Run only conservative Notes GA extraction; no existing audit or predictor outputs are written.')
    validation = parser.add_mutually_exclusive_group()
    validation.add_argument('--ga-validation-prepare', action='store_true')
    validation.add_argument('--ga-validation-run', action='store_true')
    validation.add_argument('--ga-validation-evaluate', action='store_true')
    parser.add_argument('--ga-validation-label', default='baseline')
    parser.add_argument('--ga-evaluation-name', default='evaluation')
    parser.add_argument('--ga-output-subdir', default='ga_extraction', help='New extraction-only subdirectory within output-dir.')
    parser.add_argument('--patient-key', choices=['pat_id','mrn'], default='pat_id',
                        help='Add an MRN linkage audit alongside the unchanged structured analysis; default reproduces PAT_ID audit.')
    args=parser.parse_args()
    from serda_pipeline import core
    from serda_pipeline.analysis import execute, finalize_figure_status
    from serda_pipeline.notes import audit_notes
    from serda_pipeline.mrn_audit import audit_mrn
    config=yaml.safe_load(args.config.read_text(encoding='utf-8'))
    if args.cohort_anchor_policy: config['cohort_anchor_policy'] = args.cohort_anchor_policy
    if args.anchor_day_policy: config['anchor_day_policy'] = args.anchor_day_policy
    root=args.data_dir.resolve(); out=args.output_dir.resolve()
    if not root.is_dir(): parser.error('data-dir must be an existing directory')
    if out==root or root in out.parents or out in root.parents:
        parser.error('output-dir must be separate from and not contain data-dir')
    code_directory=Path(__file__).resolve().parent
    if out==code_directory or code_directory in out.parents:
        parser.error('output-dir must be outside the code repository to keep clinical results out of Git')
    if args.ga_validation_prepare or args.ga_validation_run or args.ga_validation_evaluate:
        if args.notes_audit_only or args.ga_extraction_only:
            parser.error('GA validation stages cannot be combined with other audit modes')
        from serda_pipeline import ga_validation
        try:
            if args.ga_validation_prepare: ga_validation.prepare(root,out,config,args.patient_key)
            elif args.ga_validation_run: ga_validation.run(out,args.ga_validation_label)
            else: ga_validation.evaluate(out,args.ga_validation_label,args.ga_evaluation_name)
        except Exception as exc:
            print(str(exc) if isinstance(exc,core.PipelineError) else type(exc).__name__+': validation stage failed; no patient details logged.')
            return 2
        print('GA validation stage completed in the configured SERDA directory.')
        return 0
    if args.ga_extraction_only:
        import json
        from serda_pipeline.ga_extraction import run as run_ga
        if args.notes_audit_only: parser.error('--ga-extraction-only and --notes-audit-only are mutually exclusive')
        subdir=Path(args.ga_output_subdir)
        if subdir.is_absolute() or len(subdir.parts)!=1 or subdir.name in {'', '.', '..'}:
            parser.error('--ga-output-subdir must be one new directory name')
        ga_out=out/subdir
        if ga_out.exists() and any(ga_out.iterdir()):
            parser.error('GA extraction directory is not empty; choose a new output directory or subdirectory')
        ga_out.mkdir(parents=True,exist_ok=True)
        try:
            counts=run_ga(root,ga_out,config,args.patient_key)
            audit_only=not counts.get('identity_verified',False)
            status={'status':'audit_only_identity_unverified' if audit_only else 'completed',
                    'selection_counts':counts,
                    'reason':'Candidate grouping audited; no note reconstructed or GA value extracted until note identity is verified.' if audit_only else None,
                    'real_data_validation':'Only the execution environment can establish whether real SERDA files were used.'}
        except Exception as exc:
            status={'status':'failed','reason':str(exc) if isinstance(exc,core.PipelineError)
                    else f'{type(exc).__name__}: GA extraction failed; inspect configuration and local logs.'}
        (ga_out/'ga_execution_report.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
        print('GA extraction status: '+status['status']+'; see ga_execution_report.json in the configured SERDA output.')
        return 0 if status['status']=='completed' else 2
    if out.exists() and any(out.iterdir()) and (args.patient_key == 'mrn' or not config.get('overwrite',False)):
        parser.error('output-dir is not empty; choose a new run directory')
    if not args.notes_audit_only:
        if config['lookback_days'] <= 0: parser.error('lookback_days must be positive')
        if config.get('cohort_anchor_policy', 'strict_timestamp') not in {'strict_timestamp','calendar_day','exclude_ambiguous_for_eda'}:
            parser.error('Invalid cohort_anchor_policy')
        if config.get('temporal_granularity', 'timestamp') not in {'timestamp','calendar_day'}:
            parser.error('Invalid temporal_granularity')
        if config.get('anchor_day_policy', 'at_or_before_timestamp') not in {'at_or_before_timestamp','pre_anchor_date_only'}:
            parser.error('Invalid anchor_day_policy')
        if config['baseline_tolerance_days'] < 0 or config['followup_tolerance_days'] < 0:
            parser.error('Weight tolerances must be nonnegative')
        if config.get('cohort_anchor_policy') == 'calendar_day' and config.get('temporal_granularity', 'timestamp') != 'calendar_day':
            parser.error('calendar_day anchor policy requires calendar_day temporal granularity')
    out.mkdir(parents=True,exist_ok=True); (out/'figures').mkdir(exist_ok=True)
    report=core.Report(); datasets={}; count=None; metrics=[]
    report.data['analysis_settings'] = {k:config[k] for k in ['lookback_days','baseline_tolerance_days','followup_tolerance_days','dayfirst','excel_date_min','excel_date_max'] if k in config}
    report.data['analysis_settings'].update(cohort_anchor_policy=config.get('cohort_anchor_policy','strict_timestamp'), temporal_granularity=config.get('temporal_granularity','timestamp'), anchor_day_policy=config.get('anchor_day_policy','at_or_before_timestamp'))
    report.data['provisional'] = config.get('cohort_anchor_policy') == 'exclude_ambiguous_for_eda'
    report.data['cohort_status'] = ('PROVISIONAL EDA ONLY; not the final validated research cohort.' if report.data['provisional'] else 'Strict cohort checks; research validation still required.')
    report.data['notes_audit_only'] = args.notes_audit_only
    report.data['patient_key'] = args.patient_key
    if args.notes_audit_only:
        report.data['cohort_status'] = 'Notes audit only; all original Demographics anchors retained; no clinical cohort selected.'
    try:
        for key in (['demographics'] if args.notes_audit_only else STEMS):
            try:
                datasets[key]=getattr(core,'load_'+key)(root,config,report)
                print(f'{key}: loaded {len(datasets[key])} rows')
            except Exception as exc:
                reason=str(exc) if isinstance(exc,core.PipelineError) else f'{type(exc).__name__}: Excel read failed; verify format, sheet and header configuration.'
                report.fail('load_'+key,reason); print(f'{key}: module unavailable; see execution report')
        if not args.notes_audit_only:
            try: count,metrics=execute(datasets,config,report,out)
            except Exception as exc:
                report.fail('cohort_analysis',str(exc) if isinstance(exc,core.PipelineError) else f'{type(exc).__name__}: analysis failed; no raw data included in diagnostics.')
        else:
            import pandas as pd
            pd.DataFrame([{'dataset':key,**{k:stats.get(k) for k in ['row_count','unique_patients','duplicate_rows','missing_patient_ids']}}
                          for key,stats in report.data['datasets'].items()]).to_csv(out/'dataset_inventory.csv',index=False)
            for key,stats in report.data['datasets'].items():
                pd.Series(stats['missingness'],name='missing_fraction').rename_axis('column').to_csv(out/f'{key}_missingness.csv')
            report.skip('cohort_analysis','--notes-audit-only: structured EDA not requested.')
        # Separate pass after structured results; Notes never enters execute()/predictors.
        audit_notes(root,config,report,out,datasets.get('demographics'))
        if args.patient_key == 'mrn':
            audit_mrn(root,config,report,out,notes_only=args.notes_audit_only)
    finally:
        if not args.notes_audit_only: finalize_figure_status(report,out)
        else: report.data['figure_files'] = sorted(p.name for p in (out/'figures').glob('*.png'))
        report.save(out); write_reports(out,report,count,metrics)
    print(f'Reports written to configured output directory. Failed modules: {len(report.data["failed_modules"])}')
    return 2 if report.data['failed_modules'] else 0

if __name__=='__main__': sys.exit(main())
