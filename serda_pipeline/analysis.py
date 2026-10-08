"""CPU analyses of real records, restricted to the pre-anchor look-back."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .core import PipelineError


def plot(series, path, title, xlabel, histogram=False, report=None, ylabel=None, line=False):
    module = 'figure_' + path.stem
    fig = None
    try:
        values = series.dropna()
        if values.empty:
            if report: report.skip(module, 'No qualifying non-null observations to plot.')
            return
        fig, ax = plt.subplots(figsize=(10, 5))
        if histogram: ax.hist(values, bins=30, color='#286b8e')
        elif line: ax.plot(values.index, values.values, marker='o', color='#286b8e')
        else: values.plot.bar(ax=ax, color='#286b8e')
        if report and report.data.get('provisional'): title = 'PROVISIONAL EDA: ' + title
        ax.set(title=title, xlabel=xlabel, ylabel=ylabel or ('Fraction of cohort' if 'Fraction of cohort' in title else 'Count'))
        fig.tight_layout(); fig.savefig(path, dpi=180)
        if report: report.data['completed_modules'].append(module)
    except Exception as exc:
        if report: report.fail(module, f'{type(exc).__name__}: figure generation failed; no record values logged.')
        else: raise
    finally:
        if fig is not None: plt.close(fig)


DEMOGRAPHIC_ATTRIBUTES = ['birth', 'sex', 'race', 'ethnicity', 'marital',
                          'education', 'years_education', 'education_source']


def build_cohort(demo, report, config, out):
    if demo.empty: raise PipelineError('Demographic cohort is empty.')
    profile = demo.assign(anchor_day=demo.anchor.dt.normalize()).groupby('patient').agg(
        rows=('anchor','size'), distinct_timestamps=('anchor','nunique'),
        distinct_calendar_days=('anchor_day','nunique'))
    summary = {
        'patients': len(profile),
        'patients_multiple_timestamps': int(profile.distinct_timestamps.gt(1).sum()),
        'patients_multiple_calendar_days': int(profile.distinct_calendar_days.gt(1).sum()),
        'patients_same_day_multiple_timestamps': int((profile.distinct_timestamps.gt(1) & profile.distinct_calendar_days.eq(1)).sum()),
        'missing_patient_id_rows': int(demo.patient.isna().sum()),
        'invalid_or_missing_anchor_rows': int(demo.anchor.isna().sum()),
    }
    report.data['cohort_anchor_diagnostics'] = summary
    pd.Series(summary, name='count').rename_axis('metric').to_csv(out/'cohort_anchor_diagnostics.csv')
    profile.groupby(['distinct_timestamps','distinct_calendar_days']).size().rename('patients').to_csv(out/'anchor_multiplicity_distribution.csv')
    report.data['completed_modules'].append('cohort_anchor_diagnostics')
    policy = config.get('cohort_anchor_policy', 'strict_timestamp')
    if policy != 'exclude_ambiguous_for_eda' and (demo.patient.isna().any() or demo.anchor.isna().any()):
        raise PipelineError('Demographics contains missing patient IDs or missing/unparseable anchors.')
    provisional = policy == 'exclude_ambiguous_for_eda'
    report.data['provisional'] = provisional
    report.data['cohort_status'] = ('PROVISIONAL EDA ONLY; not the final validated research cohort.'
                                  if provisional else 'Strict cohort checks; research validation still required.')
    attributes = [c for c in DEMOGRAPHIC_ATTRIBUTES if c in demo]
    conflicts_by_attribute = demo.groupby('patient')[attributes].nunique().gt(1)
    conflicts_by_attribute.to_csv(out/'demographic_attribute_conflicts_patient_audit.csv', index_label='PAT_ID')
    conflict_patients = conflicts_by_attribute.any(axis=1)
    report.data['demographic_attribute_conflicts'] = {
        c: int(conflicts_by_attribute[c].sum()) for c in attributes}
    report.issue('cohort', f'{int(conflict_patients.sum())} patients have conflicting demographic attributes; affected attributes remain unavailable, including age for conflicting birth dates.')
    selected = demo[['patient','anchor']].copy()
    if policy in {'calendar_day', 'exclude_ambiguous_for_eda'}:
        selected['anchor'] = selected.anchor.dt.normalize()
    elif policy != 'strict_timestamp':
        raise PipelineError('Unknown cohort_anchor_policy.')
    conflicts = selected.groupby('patient').anchor.nunique().gt(1)
    invalid_anchor_patients = set(demo.loc[demo.anchor.isna(), 'patient'].dropna())
    eligible = conflicts.index[~conflicts & ~conflicts.index.isin(invalid_anchor_patients)]
    excluded = ~selected.patient.isin(eligible)
    selection = {
        'input_records': len(demo), 'input_patients': len(profile),
        'unambiguous_patients': int((profile.distinct_calendar_days.eq(1) & ~profile.index.isin(invalid_anchor_patients)).sum()),
        'ambiguous_patients': int(profile.distinct_calendar_days.gt(1).sum()),
        'excluded_patients': len(profile) - len(eligible) if provisional else 0,
        'patients_with_invalid_or_missing_anchors': len(invalid_anchor_patients),
        'missing_patient_id_records': int(demo.patient.isna().sum()),
        'excluded_records': int(excluded.sum()) if provisional else 0,
        'final_analyzable_patients': len(eligible) if provisional or not conflicts.any() else 0,
        'patients_with_demographic_attribute_conflicts': int(conflict_patients.reindex(eligible).sum()),
    }
    report.data['cohort_selection'] = selection
    pd.Series(selection, name='count').rename_axis('metric').to_csv(out/'cohort_selection_summary.csv')
    audit = profile.join(conflict_patients.rename('demographic_attribute_conflict'))
    audit['selected_for_analysis'] = audit.index.isin(eligible) if provisional or not conflicts.any() else False
    audit['selection_reason'] = np.where(audit.index.isin(eligible), 'unique_anchor', 'multiple_anchors')
    audit.loc[audit.index.isin(invalid_anchor_patients), 'selection_reason'] = 'invalid_or_missing_anchor'
    if not provisional and conflicts.any():
        audit.loc[audit.index.isin(eligible), 'selection_reason'] = 'strict_cohort_blocked'
    audit_excluded = excluded if provisional else pd.Series(False, index=demo.index)
    pd.DataFrame({'source_row_position_zero_based': np.flatnonzero(audit_excluded),
                  'PAT_ID': demo.loc[audit_excluded, 'patient'].to_numpy(),
                  'reason': np.where(demo.loc[audit_excluded, 'patient'].isna(), 'missing_patient_id',
                            np.where(demo.loc[audit_excluded, 'patient'].isin(invalid_anchor_patients),
                                     'invalid_or_missing_anchor', 'multiple_anchors'))}).to_csv(
        out/'cohort_excluded_records_patient_audit.csv', index=False)
    audit.to_csv(out/'cohort_selection_patient_audit.csv', index_label='PAT_ID')
    if conflicts.any() and not provisional:
        report.issue('cohort', f'{int(conflicts.sum())} patients have multiple anchors under {policy}; no anchor selected.')
        raise PipelineError('Multiple demographic anchors; explicit study index-visit definition required.')
    if provisional:
        selected = selected.loc[~excluded].copy()
        report.issue('cohort', f'PROVISIONAL EDA ONLY: {int(conflicts.sum())} ambiguous patients excluded; not the final research cohort. Unique calendar dates normalized to midnight; no earliest/latest anchor selection.')
    report.issue('cohort', f'{int(selected.duplicated(["patient","anchor"]).sum())} repeated cohort keys collapsed under {policy}.')
    cohort = selected.drop_duplicates()
    if cohort.empty: raise PipelineError('No analyzable patients after cohort selection.')
    cohort.attrs['excluded_ambiguous_ids'] = list(profile.index[profile.distinct_calendar_days.gt(1)])
    report.data['completed_modules'].append('cohort_selection')
    return cohort


def lookback_mask(data, config):
    lower = data.days_from_anchor.ge(-config['lookback_days'])
    if config.get('anchor_day_policy', 'at_or_before_timestamp') == 'pre_anchor_date_only':
        upper = data.date.dt.normalize().lt(data.cohort_anchor.dt.normalize())
    else:
        # Even calendar-day distances must not admit later anchor-day timestamps.
        upper = data.date.le(data.cohort_anchor)
    return lower & upper & data.date.notna()


def temporal(key, data, cohort, config, report, out):
    linked = data.merge(cohort.rename(columns={'anchor':'cohort_anchor'}), on='patient', how='left', validate='many_to_one', indicator=True)
    unmatched = linked['_merge'].eq('left_only')
    report.data['datasets'][key]['unmatched_rows'] = int(unmatched.sum())
    stats = report.data['datasets'][key]
    stats['outside_cohort_rows'] = int((unmatched & linked.patient.notna()).sum())
    ambiguous_ids = set(cohort.attrs.get('excluded_ambiguous_ids', []))
    stats['ambiguous_cohort_excluded_rows'] = int(linked.patient.isin(ambiguous_ids).sum())
    stats['ambiguous_cohort_excluded_patients'] = int(linked.loc[linked.patient.isin(ambiguous_ids), 'patient'].nunique())
    stats['outside_cohort_patients'] = int(linked.loc[unmatched, 'patient'].nunique())
    stats['missing_patient_id_excluded_rows'] = int(linked.patient.isna().sum())
    stats['matched_cohort_rows'] = int((~unmatched).sum())
    stats['matched_cohort_patients'] = int(linked.loc[~unmatched, 'patient'].nunique())
    if unmatched.any():
        report.issue(key, f'{stats["outside_cohort_rows"]} outside-cohort rows ({stats["outside_cohort_patients"]} patients) and {stats["missing_patient_id_excluded_rows"]} missing-ID rows excluded. Missing IDs require local data-quality review; cohort unchanged.')
    linked = linked.loc[~unmatched].copy()
    if 'anchor' in linked:
        invalid = linked.anchor.isna() | linked.anchor.dt.normalize().ne(linked.cohort_anchor.dt.normalize())
        if invalid.any(): raise PipelineError(f'{int(invalid.sum())} missing or conflicting supplied anchors. Module stopped.')
    if 'contact' in linked and key != 'demographics':
        conflicts = linked.contact.notna() & linked.contact.dt.normalize().ne(linked.cohort_anchor.dt.normalize())
        report.data['datasets'][key]['contact_anchor_differences'] = int(conflicts.sum())
    if 'date' not in linked: return linked, None
    precise_days = (linked.date - linked.cohort_anchor).dt.total_seconds()/86400
    stats['same_anchor_day_after_timestamp_rows'] = int((linked.date.dt.normalize().eq(linked.cohort_anchor.dt.normalize()) & precise_days.gt(0)).sum())
    if config.get('temporal_granularity', 'timestamp') == 'calendar_day':
        linked['days_from_anchor'] = (linked.date.dt.normalize() - linked.cohort_anchor.dt.normalize()).dt.days
    else:
        linked['days_from_anchor'] = precise_days
    days = linked.days_from_anchor
    window_mask = lookback_mask(linked, config)
    metrics = {'dataset':key, 'dated_records':int(days.notna().sum()), 'unknown_date_records':int(days.isna().sum()),
               'post_anchor_records':int(precise_days.gt(0).sum()),
               'anchor_day_excluded_records':int((linked.date.dt.normalize().eq(linked.cohort_anchor.dt.normalize()) & ~window_mask).sum()), 'before_lookback_records':int(days.lt(-config['lookback_days']).sum()),
               'lookback_records':int(window_mask.sum()),
               'lookback_patients':int(linked.loc[window_mask,'patient'].nunique())}
    if 'prior_date' in linked:
        prior = (linked.prior_date-linked.cohort_anchor).dt.total_seconds()/86400
        metrics.update(prior_dated_records=int(prior.notna().sum()), prior_post_anchor_records=int(prior.gt(0).sum()),
                       prior_outside_lookback_records=int(prior.lt(-config['lookback_days']).sum()))
    plot(days, out/'figures'/f'{key}_record_density.png', f'{key}: record dates relative to cohort anchor', 'Days from anchor', True, report=report)
    report.data['completed_modules'].append('temporal_'+key)
    return linked, metrics


def process_comorbidities(data, features, out, report):
    valid = data.dropna(subset=['icd']).copy()
    valid['icd'] = valid.icd.str.strip().str.upper()
    valid.icd.value_counts().rename_axis('ICD10').to_csv(out/'icd10_record_frequency.csv')
    valid.drop_duplicates(['patient','icd']).icd.value_counts().rename_axis('ICD10').to_csv(out/'icd10_patient_frequency.csv')
    features['unique_diagnosis_burden'] = valid.groupby('patient').icd.nunique().reindex(features.index, fill_value=0)
    features['diagnosis_record_count'] = valid.groupby('patient').size().reindex(features.index, fill_value=0)
    features['repeated_diagnosis_records'] = features.diagnosis_record_count-features.unique_diagnosis_burden
    if 'source' in valid:
        valid.groupby('source', dropna=False).agg(records=('patient','size'), patients=('patient','nunique')).to_csv(out/'diagnosis_source_comparison.csv')
    plot(valid.icd.value_counts().head(20),out/'figures'/'icd10_frequency.png','Most frequent ICD-10 codes (records)','ICD-10',report=report)
    features[['unique_diagnosis_burden','diagnosis_record_count']].describe().to_csv(out/'diagnosis_burden_summary.csv')
    plot(features.unique_diagnosis_burden,out/'figures'/'diagnosis_burden.png','Unique diagnosis burden','Unique ICD-10 codes',True,report=report)


def nearest(group, target, tolerance):
    distance = (group.days_from_anchor-target).abs()
    eligible = group.loc[distance.le(tolerance)]
    if eligible.empty: return np.nan
    best = eligible.loc[(eligible.days_from_anchor-target).abs().eq((eligible.days_from_anchor-target).abs().min())]
    return float(best.kg.iloc[0]) if best.kg.nunique()==1 else np.nan


def process_height_weight(data, features, config, report, out):
    data = data.copy()
    numeric = pd.to_numeric(data.value, errors='coerce')
    report.data['datasets']['height_weight']['numeric_parse_failures'] = int((data.value.notna() & numeric.isna()).sum())
    measurement = data.measurement.str.strip().str.casefold()
    # Exact labels only; other real labels can be reviewed in aggregate coverage output.
    weights = measurement.isin(['weight','body weight','weight (kg)','weight (lbs)'])
    heights = measurement.isin(['height','body height'])
    data.groupby(['measurement','units'],dropna=False).size().rename('records').to_csv(out/'measurement_unit_coverage.csv')
    unit = data.units.str.strip().str.casefold()
    data['kg'] = numeric * unit.map(config['weight_units'])
    data['m'] = numeric * unit.map(config['height_units'])
    report.data['datasets']['height_weight']['unsupported_weight_units'] = int((weights & data.kg.isna() & numeric.notna()).sum())
    report.data['datasets']['height_weight']['unsupported_height_units'] = int((heights & data.m.isna() & numeric.notna()).sum())
    w = data.loc[weights & data.kg.gt(0)].copy()
    h = data.loc[heights & data.m.gt(0)].copy()
    report.data['datasets']['height_weight']['nonpositive_measurements'] = int(((weights & data.kg.le(0)) | (heights & data.m.le(0))).sum())
    features['weight_measurement_count'] = w.groupby('patient').size().reindex(features.index, fill_value=0)
    for patient, group in w.groupby('patient'):
        baseline = nearest(group,0,config['baseline_tolerance_days'])
        features.loc[patient,'weight_kg_anchor'] = baseline
        for months, days in [(6,183),(12,365)]:
            previous = nearest(group,-days,config['followup_tolerance_days'])
            features.loc[patient,f'weight_kg_{months}m_prior'] = previous
            features.loc[patient,f'weight_change_{months}m_pct'] = 100*(baseline-previous)/previous if previous>0 and pd.notna(baseline) else np.nan
    for patient, group in h.groupby('patient'):
        candidate = group.loc[group.days_from_anchor.ge(-config['baseline_tolerance_days'])]
        if candidate.empty: continue
        latest = candidate.loc[candidate.date.eq(candidate.date.max())]
        if latest.m.nunique()==1: features.loc[patient,'height_m_anchor']=latest.m.iloc[0]
    if 'height_m_anchor' in features and 'weight_kg_anchor' in features:
        features['bmi_anchor'] = features.weight_kg_anchor/features.height_m_anchor.pow(2)
    for months in [6,12]:
        col=f'weight_change_{months}m_pct'
        if col in features: plot(features[col],out/'figures'/f'{col}.png',f'{months}-month pre-anchor weight change','Change (%)',True,report=report)
    if not w.empty:
        w['month_before_anchor'] = np.floor(w.days_from_anchor/30.4375).astype(int)
        # Aggregate trajectories, no named patient traces.
        monthly = w.groupby(['patient','month_before_anchor']).kg.median().groupby('month_before_anchor').agg(['median','count'])
        monthly.to_csv(out/'weight_trajectory_monthly.csv')
        plot(monthly['median'],out/'figures'/'weight_trajectories.png','Median patient weight by month relative to anchor','Month from anchor',report=report,ylabel='Weight (kg)',line=True)
    else:
        report.skip('figure_weight_trajectories', 'No qualifying positive weights with supported units.')
    columns = ['weight_kg_anchor','height_m_anchor','bmi_anchor','weight_change_6m_pct','weight_change_12m_pct']
    features[columns].describe().to_csv(out/'weight_bmi_summary.csv')
    for column in ['weight_kg_anchor','height_m_anchor','bmi_anchor']:
        plot(features[column],out/'figures'/f'{column}.png',column,column,True,report=report)


def latest_status(data, column):
    values={}
    for patient, group in data.dropna(subset=[column]).groupby('patient'):
        last=group.loc[group.date.eq(group.date.max())]
        if last[column].nunique()==1: values[patient]=last[column].iloc[0]
    return pd.Series(values,dtype=object)


def process_labs(data, features, report, out):
    numeric=pd.to_numeric(data.value,errors='coerce')
    report.data['datasets']['labs']['nonnumeric_lab_values']=int((data.value.notna() & numeric.isna()).sum())
    data.groupby('component',dropna=False).agg(records=('patient','size'),patients=('patient','nunique')).to_csv(out/'lab_component_coverage.csv')
    features['lab_record_count']=data.groupby('patient').size().reindex(features.index,fill_value=0)
    features['lab_component_count']=data.groupby('patient').component.nunique().reindex(features.index,fill_value=0)
    # No unit metadata in observed schema: numerical lab values cannot safely be pooled.

def process_medications(data, features):
    features['medication_order_count']=data.groupby('patient').size().reindex(features.index,fill_value=0)
    features['unique_medication_count']=data.groupby('patient').medication.nunique().reindex(features.index,fill_value=0)

def process_alcohol(data, features): features['alcohol_latest_status']=latest_status(data,'alcohol').reindex(features.index)
def process_smoking(data, features): features['smoking_latest_status']=latest_status(data,'smoking').reindex(features.index)


CLINICAL_FEATURES = {
    'comorbidities': ['unique_diagnosis_burden','diagnosis_record_count','repeated_diagnosis_records'],
    'height_weight': ['weight_measurement_count','weight_kg_anchor','weight_kg_6m_prior','weight_kg_12m_prior',
                      'weight_change_6m_pct','weight_change_12m_pct','height_m_anchor','bmi_anchor'],
    'labs': ['lab_record_count','lab_component_count'],
    'alcohol': ['alcohol_latest_status'], 'smoking': ['smoking_latest_status'],
    'medications': ['medication_order_count','unique_medication_count'],
}
for _key, _columns in CLINICAL_FEATURES.items():
    _columns.extend([_key+'_observed_lookback', _key+'_records_lookback'])


def feature_owner(column):
    return next((key for key, columns in CLINICAL_FEATURES.items() if column in columns), 'demographics')


EXPECTED_FIGURES = {
    **{key+'_record_density': 'temporal_'+key for key in CLINICAL_FEATURES},
    'icd10_frequency': 'features_comorbidities', 'diagnosis_burden': 'features_comorbidities',
    **{name: 'features_height_weight' for name in ['weight_kg_anchor','height_m_anchor','bmi_anchor',
       'weight_change_6m_pct','weight_change_12m_pct','weight_trajectories']},
    'observation_availability': 'patient_features',
}


def finalize_figure_status(report, out):
    """Every expected figure has a completion, failure, or explicit skip reason."""
    known = set(report.data['completed_modules'])
    known.update(item['module'] for item in report.data['failed_modules'])
    known.update(item['module'] for item in report.data['skipped_modules'])
    for name, dependency in EXPECTED_FIGURES.items():
        module = 'figure_'+name
        if module not in known:
            report.skip(module, f'Not generated: prerequisite {dependency} unavailable or stopped before plotting.')
    report.data['figure_files'] = sorted(path.name for path in (out/'figures').glob('*.png'))


def execute(datasets, config, report, out):
    inventory=[]
    for key, stats in report.data['datasets'].items():
        inventory.append({'dataset':key,**{k:stats.get(k) for k in ['row_count','unique_patients','duplicate_rows','missing_patient_ids']}})
        pd.Series(stats['missingness'],name='missing_fraction').rename_axis('column').to_csv(out/f'{key}_missingness.csv')
    pd.DataFrame(inventory).to_csv(out/'dataset_inventory.csv',index=False)
    if 'demographics' not in datasets:
        for module in ['cohort_selection','patient_features', *['temporal_'+k for k in CLINICAL_FEATURES], *['features_'+k for k in CLINICAL_FEATURES]]:
            report.skip(module, 'Demographics unavailable.')
        raise PipelineError('Demographics unavailable: cohort-dependent analyses cannot run.')
    # Patient-set intersections do not require a resolved anchor.
    demographic_ids = set(datasets['demographics'].patient.dropna())
    intersections = []
    for key, data in datasets.items():
        ids = set(data.patient.dropna())
        intersections.append({'dataset':key, 'source_patients':len(ids),
            'demographic_patients':len(demographic_ids), 'intersection_patients':len(ids & demographic_ids),
            'outside_demographics_patients':len(ids-demographic_ids),
            'demographic_patients_without_records':len(demographic_ids-ids),
            'outside_demographics_rows':int((data.patient.notna() & ~data.patient.isin(demographic_ids)).sum()),
            'missing_patient_id_rows':int(data.patient.isna().sum())})
    pd.DataFrame(intersections).to_csv(out/'patient_set_intersections.csv',index=False)
    report.data['completed_modules'].append('patient_set_intersections')
    try:
        cohort=build_cohort(datasets['demographics'],report,config,out)
    except PipelineError:
        for module in ['patient_features', *['temporal_'+k for k in CLINICAL_FEATURES], *['features_'+k for k in CLINICAL_FEATURES]]:
            report.skip(module, 'Cohort selection failed; see cohort diagnostics.')
        raise
    features=cohort.set_index('patient').copy()
    for columns in CLINICAL_FEATURES.values():
        for column in columns: features[column] = np.nan
    for key in CLINICAL_FEATURES:
        if key not in datasets:
            report.skip('temporal_'+key, 'Dataset unavailable; see load failure.')
            report.skip('features_'+key, 'Dataset unavailable; all associated features remain null.')
    metrics=[]
    coverage=[{'dataset':key,'cohort_patient_coverage':np.nan,'module_status':'unavailable'}
              for key in CLINICAL_FEATURES if key not in datasets]
    for key,data in datasets.items():
        coverage.append({'dataset':key,'module_status':'loaded','cohort_patient_coverage':data.patient.isin(cohort.patient).groupby(data.patient).any().sum()/len(cohort) if len(cohort) else np.nan})
        data.loc[data.patient.isin(cohort.patient)].groupby('patient').size().describe().to_csv(out/f'{key}_records_per_patient_summary.csv')
        if key=='demographics': continue
        try:
            linked, metric=temporal(key,data,cohort,config,report,out)
            if metric: metrics.append(metric)
            window=linked.loc[lookback_mask(linked,config)].copy()
        except Exception as exc:
            report.fail('temporal_'+key, str(exc) if isinstance(exc,PipelineError) else f'{type(exc).__name__}: temporal validation failed.')
            report.skip('features_'+key, 'Temporal validation failed; features remain null.')
            continue
        candidate=features.copy()
        try:
            observed=window.patient.unique()
            candidate[f'{key}_observed_lookback']=features.index.isin(observed)
            candidate[f'{key}_records_lookback']=window.groupby('patient').size().reindex(features.index,fill_value=0)
            if key=='comorbidities': process_comorbidities(window,candidate,out,report)
            elif key=='height_weight': process_height_weight(window,candidate,config,report,out)
            elif key=='labs': process_labs(window,candidate,report,out)
            elif key=='medications': process_medications(window,candidate)
            elif key=='alcohol': process_alcohol(window,candidate)
            elif key=='smoking': process_smoking(window,candidate)
            features=candidate
            report.data['completed_modules'].append('features_'+key)
        except Exception as exc:
            report.fail('features_'+key, str(exc) if isinstance(exc,PipelineError) else f'{type(exc).__name__}; inspect configuration and execution environment.')
    report.data['completed_modules'].extend(['temporal_summary','patient_coverage'])
    report.data['feature_module_status'] = {key: ('available' if 'features_'+key in report.data['completed_modules'] else 'unavailable') for key in CLINICAL_FEATURES}
    pd.DataFrame(metrics).to_csv(out/'temporal_summary.csv',index=False)
    pd.DataFrame(coverage).to_csv(out/'patient_coverage.csv',index=False)
    # Static demographics are isolated from clinical feature export.
    demo=datasets['demographics']
    candidate=features.copy()
    try:
        for col in [c for c in DEMOGRAPHIC_ATTRIBUTES if c != 'birth']:
            if col in demo:
                grouped=demo.groupby('patient')[col]
                candidate[col]=grouped.first().where(grouped.nunique().le(1)).reindex(features.index)
        if 'birth' in demo:
            grouped=demo.groupby('patient').birth
            birth=grouped.first().where(grouped.nunique().le(1)).reindex(features.index)
            age=(features.anchor-birth).dt.days/365.2425
            candidate['age_at_anchor']=age.where(age.between(0,120))
        features=candidate
        report.data['completed_modules'].append('features_demographics')
        report.data['feature_module_status']['demographics']='available'
    except Exception as exc:
        report.fail('features_demographics', f'{type(exc).__name__}: demographic features unavailable; clinical features retained.')
        report.data['feature_module_status']['demographics']='unavailable'
        for col in [c for c in DEMOGRAPHIC_ATTRIBUTES if c != 'birth' and c in demo]:
            features[col]=np.nan
        if 'birth' in demo: features['age_at_anchor']=np.nan
    plot(features.filter(like='_observed_lookback').mean(), out/'figures'/'observation_availability.png', 'Fraction of cohort with look-back records', 'Dataset',report=report)
    features.to_csv(out/'patient_features.csv',index_label='PAT_ID')
    availability = features.notna().mean().rename('available_fraction').to_frame()
    availability['module'] = [feature_owner(c) for c in availability.index]
    availability['module_status'] = availability.module.map(report.data['feature_module_status']).fillna('available')
    availability.loc['anchor','module_status']='available'
    availability['provisional']=report.data.get('provisional',False)
    availability.rename_axis('feature').to_csv(out/'feature_availability.csv')
    dictionary=[]
    for col in features:
        description='Observed export value; conflicting demographic values excluded.'
        if col.endswith('observed_lookback'):
            description='True when at least one dated record occurs in the configured pre-anchor look-back; null if module unavailable.'
        elif col.endswith('count') or 'records' in col or 'burden' in col: description='Count of records or unique observed entities in the configured pre-anchor look-back; zero denotes no qualifying records, not clinical absence.'
        elif 'weight_change' in col: description='100 * (anchor weight - prior weight) / prior weight; pre-anchor nearest observation within configured tolerance; conflicting ties unavailable.'
        elif 'latest_status' in col: description='Latest dated non-null status within look-back; conflicting statuses at latest timestamp unavailable.'
        elif col=='anchor': description='Unique demographic CONTACT_DATE anchor; provisional EDA normalizes the unique calendar date to midnight; no visit selected automatically.'
        elif col=='age_at_anchor': description='(Anchor date minus unambiguous birth date) / 365.2425 days; outside 0–120 years unavailable.'
        elif col.startswith('weight_kg_'): description='Weight in kg nearest the specified pre-anchor target within configured tolerance; unknown units and conflicting ties excluded.'
        elif col=='height_m_anchor': description='Latest unambiguous positive height in meters within the pre-anchor baseline tolerance.'
        elif col=='bmi_anchor': description='Anchor-window weight kg / height m squared; separately timed measurements, not necessarily a same-visit BMI.'
        owner=feature_owner(col)
        status='available' if col=='anchor' else report.data['feature_module_status'].get(owner, 'available')
        if status == 'unavailable': description += ' MODULE UNAVAILABLE: null values, never interpreted as zero.'
        dictionary.append({'feature':col,'dtype':str(features[col].dtype),'definition':description, 'module':owner, 'module_status':status, 'provisional':report.data.get('provisional',False)})
    pd.DataFrame(dictionary).to_csv(out/'feature_dictionary.csv',index=False)
    report.data['completed_modules'].extend(['patient_features','feature_dictionary','feature_availability'])
    return len(cohort), metrics
