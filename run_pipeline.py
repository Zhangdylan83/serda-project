"""Offline Windows/CPU entry point for real SERDA Excel exports."""
import argparse
from pathlib import Path
import sys
import yaml
from serda_pipeline.schema import STEMS


def write_reports(out, report, cohort_count=None, temporal=None):
    lines=['# Real-data EDA summary', '', 'Generated locally from the configured SERDA Excel files.',
           f'Cohort patients: {cohort_count if cohort_count is not None else "unavailable"}.', '',
           'All event features use the configured inclusive look-back; timestamp/calendar-day semantics are recorded in execution_report.json. Missing/unparseable event dates are excluded.',
           'Record counts indicate documentation availability, not absence of disease or exposure.', '', '## Dataset inventory']
    for key, stats in report.data['datasets'].items():
        lines.append(f'- {key}: {stats["row_count"]} rows; {stats.get("unique_patients", "unavailable")} unique patients; {stats["duplicate_rows"]} exact duplicate rows.')
    lines.extend(['','## Temporal findings'])
    for row in temporal or []:
        lines.append(f'- {row["dataset"]}: {row["lookback_records"]} look-back records; {row["post_anchor_records"]} post-anchor records; {row["unknown_date_records"]} records without valid dates.')
    lines.extend(['', '## Limitations', 'No frailty labels or modeling. Medication counts describe orders, not confirmed use. Lab units are absent in the reference schema, so numerical values are not pooled. Weight trajectories summarize observed patients and may reflect changing documentation coverage. Exact duplicates are reported and retained in record counts; unique entity counts are deduplicated.'])
    (out/'EDA_summary.md').write_text('\n'.join(lines),encoding='utf-8')
    quality=['# Data quality report','','See execution_report.json for headers, mappings, date parsing, linkage and module status.']
    for item in report.data['issues']: quality.append(f'- {item["module"]}: {item["message"]}')
    for item in report.data['failed_modules']: quality.append(f'- FAILED {item["module"]}: {item["reason"]}')
    (out/'data_quality_report.md').write_text('\n'.join(quality),encoding='utf-8')
    slides=['# Slide-ready findings','',
      '## Slide 1 — Objectives and workflow','Describe structured EHR coverage, validate dates, characterize comorbidities and weight, and create patient-level features. Read-only Excel → schema checks → demographic cohort → temporal checks → real EDA → features.',
      '## Slide 2 — Inventory and coverage','Use dataset_inventory.csv, patient_coverage.csv, *_missingness.csv and *_records_per_patient_summary.csv. Dataset-specific loader failures are shown in execution_report.json.',
      '## Slide 3 — Temporal validation','Use temporal_summary.csv and figures/*_record_density.png. Post-anchor records are reported and excluded from features. Undated records are excluded. Smoking prior-status dates are separately audited.',
      '## Slide 4 — Comorbidities','Use icd10_record_frequency.csv, icd10_patient_frequency.csv and diagnosis_source_comparison.csv when available. Source categories are preserved exactly; verify Problem List and Encounter Diagnosis labels in the real output.',
      '## Slide 5 — Weight and BMI','Use measurement_unit_coverage.csv, weight_trajectory_monthly.csv, weight-change figures and feature_availability.csv when available. Six- and twelve-month changes compare pre-anchor observations to anchor-window weight.',
      '## Slide 6 — Unified features','Use patient_features.csv and feature_dictionary.csv. One row per demographic patient; failed modules have no feature columns. No supervised modeling.', '', '## Execution-derived findings']
    slides.extend(lines[3:])
    (out/'slide_ready_findings.md').write_text('\n'.join(slides),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--config',type=Path,default=Path(__file__).with_name('config.yaml'))
    args=parser.parse_args()
    from serda_pipeline import core
    from serda_pipeline.analysis import execute
    config=yaml.safe_load(args.config.read_text(encoding='utf-8'))
    root=args.data_dir.resolve(); out=args.output_dir.resolve()
    if not root.is_dir(): parser.error('data-dir must be an existing directory')
    if out==root or root in out.parents or out in root.parents:
        parser.error('output-dir must be separate from and not contain data-dir')
    if out.exists() and any(out.iterdir()) and not config.get('overwrite',False):
        parser.error('output-dir is not empty; choose a new run directory')
    if config['lookback_days'] <= 0: parser.error('lookback_days must be positive')
    if config.get('cohort_anchor_policy', 'strict_timestamp') not in {'strict_timestamp','calendar_day'}:
        parser.error('Invalid cohort_anchor_policy')
    if config.get('temporal_granularity', 'timestamp') not in {'timestamp','calendar_day'}:
        parser.error('Invalid temporal_granularity')
    if config.get('cohort_anchor_policy') == 'calendar_day' and config.get('temporal_granularity', 'timestamp') != 'calendar_day':
        parser.error('calendar_day anchor policy requires calendar_day temporal granularity')
    out.mkdir(parents=True,exist_ok=True); (out/'figures').mkdir(exist_ok=True)
    report=core.Report(); datasets={}; count=None; metrics=[]
    report.data['analysis_settings'] = {k:config[k] for k in ['lookback_days','baseline_tolerance_days','followup_tolerance_days','dayfirst','excel_date_min','excel_date_max']}
    report.data['analysis_settings'].update(cohort_anchor_policy=config.get('cohort_anchor_policy','strict_timestamp'), temporal_granularity=config.get('temporal_granularity','timestamp'))
    try:
        for key in STEMS:
            try:
                datasets[key]=getattr(core,'load_'+key)(root,config,report)
                print(f'{key}: loaded {len(datasets[key])} rows')
            except Exception as exc:
                reason=str(exc) if isinstance(exc,core.PipelineError) else f'{type(exc).__name__}: Excel read failed; verify format, sheet and header configuration.'
                report.fail('load_'+key,reason); print(f'{key}: module unavailable; see execution report')
        try: count,metrics=execute(datasets,config,report,out)
        except Exception as exc:
            report.fail('cohort_analysis',str(exc) if isinstance(exc,core.PipelineError) else f'{type(exc).__name__}: analysis failed; no raw data included in diagnostics.')
    finally:
        report.save(out); write_reports(out,report,count,metrics)
    print(f'Reports written to configured output directory. Failed modules: {len(report.data["failed_modules"])}')
    return 2 if report.data['failed_modules'] else 0

if __name__=='__main__': sys.exit(main())
