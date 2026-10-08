"""CPU analyses of real records, restricted to the pre-anchor look-back."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .core import PipelineError


def plot(series, path, title, xlabel, histogram=False):
    values = series.dropna()
    if values.empty: return
    fig, ax = plt.subplots(figsize=(10, 5))
    if histogram: ax.hist(values, bins=30, color='#286b8e')
    else: values.plot.bar(ax=ax, color='#286b8e')
    ax.set(title=title, xlabel=xlabel, ylabel='Fraction of cohort' if 'Fraction of cohort' in title else 'Count')
    fig.tight_layout(); fig.savefig(path, dpi=180); plt.close(fig)


def build_cohort(demo, report):
    if demo.empty: raise PipelineError('Demographic cohort is empty.')
    if demo.patient.isna().any() or demo.anchor.isna().any():
        raise PipelineError('Demographics contains missing patient IDs or missing/unparseable anchors.')
    conflicts = demo.groupby('patient').anchor.nunique().gt(1)
    if conflicts.any():
        report.issue('cohort', f'{int(conflicts.sum())} patients have multiple anchors. Patient-level analysis requires one explicit cohort anchor per patient.')
        raise PipelineError('Multiple demographic anchors; cannot choose one silently.')
    report.issue('cohort', f'{int(demo.duplicated(["patient","anchor"]).sum())} repeated cohort rows; identical patient/anchor keys collapsed.')
    cohort = demo[['patient','anchor']].drop_duplicates()
    return cohort


def temporal(key, data, cohort, config, report, out):
    linked = data.merge(cohort.rename(columns={'anchor':'cohort_anchor'}), on='patient', how='left', validate='many_to_one', indicator=True)
    unmatched = linked['_merge'].eq('left_only')
    report.data['datasets'][key]['unmatched_rows'] = int(unmatched.sum())
    if unmatched.any():
        raise PipelineError(f'{int(unmatched.sum())} rows cannot link to demographic cohort (including missing IDs). Module stopped.')
    if 'anchor' in linked:
        invalid = linked.anchor.isna() | linked.anchor.dt.normalize().ne(linked.cohort_anchor.dt.normalize())
        if invalid.any(): raise PipelineError(f'{int(invalid.sum())} missing or conflicting supplied anchors. Module stopped.')
    if 'contact' in linked and key != 'demographics':
        conflicts = linked.contact.notna() & linked.contact.dt.normalize().ne(linked.cohort_anchor.dt.normalize())
        report.data['datasets'][key]['contact_anchor_differences'] = int(conflicts.sum())
    if 'date' not in linked: return linked, None
    linked['days_from_anchor'] = (linked.date - linked.cohort_anchor).dt.total_seconds()/86400
    days = linked.days_from_anchor
    metrics = {'dataset':key, 'dated_records':int(days.notna().sum()), 'unknown_date_records':int(days.isna().sum()),
               'post_anchor_records':int(days.gt(0).sum()), 'before_lookback_records':int(days.lt(-config['lookback_days']).sum()),
               'lookback_records':int(days.between(-config['lookback_days'],0).sum()),
               'lookback_patients':int(linked.loc[days.between(-config['lookback_days'],0),'patient'].nunique())}
    if 'prior_date' in linked:
        prior = (linked.prior_date-linked.cohort_anchor).dt.total_seconds()/86400
        metrics.update(prior_dated_records=int(prior.notna().sum()), prior_post_anchor_records=int(prior.gt(0).sum()),
                       prior_outside_lookback_records=int(prior.lt(-config['lookback_days']).sum()))
    plot(days, out/'figures'/f'{key}_record_density.png', f'{key}: record dates relative to cohort anchor', 'Days from anchor', True)
    report.data['completed_modules'].append('temporal_'+key)
    return linked, metrics


def process_comorbidities(data, features, out):
    valid = data.dropna(subset=['icd']).copy()
    valid['icd'] = valid.icd.str.strip().str.upper()
    valid.icd.value_counts().rename_axis('ICD10').to_csv(out/'icd10_record_frequency.csv')
    valid.drop_duplicates(['patient','icd']).icd.value_counts().rename_axis('ICD10').to_csv(out/'icd10_patient_frequency.csv')
    features['unique_diagnosis_burden'] = valid.groupby('patient').icd.nunique().reindex(features.index, fill_value=0)
    features['diagnosis_record_count'] = valid.groupby('patient').size().reindex(features.index, fill_value=0)
    features['repeated_diagnosis_records'] = features.diagnosis_record_count-features.unique_diagnosis_burden
    if 'source' in valid:
        valid.groupby('source', dropna=False).agg(records=('patient','size'), patients=('patient','nunique')).to_csv(out/'diagnosis_source_comparison.csv')
    plot(valid.icd.value_counts().head(20),out/'figures'/'icd10_frequency.png','Most frequent ICD-10 codes (records)','ICD-10')


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
        if col in features: plot(features[col],out/'figures'/f'{col}.png',f'{months}-month pre-anchor weight change','Change (%)',True)
    if not w.empty:
        w['month_before_anchor'] = np.floor(w.days_from_anchor/30.4375).astype(int)
        # Aggregate trajectories, no named patient traces.
        monthly = w.groupby(['patient','month_before_anchor']).kg.median().groupby('month_before_anchor').agg(['median','count'])
        monthly.to_csv(out/'weight_trajectory_monthly.csv')
        fig,ax=plt.subplots(figsize=(10,5)); ax.plot(monthly.index,monthly['median'],marker='o')
        ax.set(title='Median patient weight by month relative to anchor',xlabel='Month from anchor',ylabel='Weight (kg)')
        fig.tight_layout(); fig.savefig(out/'figures'/'weight_trajectories.png',dpi=180); plt.close(fig)


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


def execute(datasets, config, report, out):
    inventory=[]
    for key, stats in report.data['datasets'].items():
        inventory.append({'dataset':key,**{k:stats.get(k) for k in ['row_count','unique_patients','duplicate_rows','missing_patient_ids']}})
        pd.Series(stats['missingness'],name='missing_fraction').rename_axis('column').to_csv(out/f'{key}_missingness.csv')
    pd.DataFrame(inventory).to_csv(out/'dataset_inventory.csv',index=False)
    if 'demographics' not in datasets: raise PipelineError('Demographics unavailable: cohort-dependent analyses cannot run.')
    cohort=build_cohort(datasets['demographics'],report)
    features=cohort.set_index('patient').copy()
    metrics=[]; coverage=[]
    for key,data in datasets.items():
        coverage.append({'dataset':key,'cohort_patient_coverage':data.patient.isin(cohort.patient).groupby(data.patient).any().sum()/len(cohort) if len(cohort) else np.nan})
        data.groupby('patient').size().describe().to_csv(out/f'{key}_records_per_patient_summary.csv')
        if key=='demographics': continue
        try:
            linked, metric=temporal(key,data,cohort,config,report,out)
            if metric: metrics.append(metric)
            window=linked.loc[linked.days_from_anchor.between(-config['lookback_days'],0)].copy()
            observed=window.patient.unique()
            features[f'{key}_observed_lookback']=features.index.isin(observed)
            features[f'{key}_records_lookback']=window.groupby('patient').size().reindex(features.index,fill_value=0)
            if key=='comorbidities': process_comorbidities(window,features,out)
            elif key=='height_weight': process_height_weight(window,features,config,report,out)
            elif key=='labs': process_labs(window,features,report,out)
            elif key=='medications': process_medications(window,features)
            elif key=='alcohol': process_alcohol(window,features)
            elif key=='smoking': process_smoking(window,features)
            report.data['completed_modules'].append('features_'+key)
        except Exception as exc:
            report.fail(key, str(exc) if isinstance(exc,PipelineError) else f'{type(exc).__name__}; inspect configuration and execution environment.')
    pd.DataFrame(metrics).to_csv(out/'temporal_summary.csv',index=False)
    pd.DataFrame(coverage).to_csv(out/'patient_coverage.csv',index=False)
    # Static demographics: conflicting values remain unavailable.
    demo=datasets['demographics']
    for col in ['sex','race','ethnicity','marital','education','years_education']:
        if col in demo:
            grouped=demo.groupby('patient')[col]
            features[col]=grouped.first().where(grouped.nunique().le(1)).reindex(features.index)
    if 'birth' in demo:
        grouped=demo.groupby('patient').birth
        birth=grouped.first().where(grouped.nunique().le(1)).reindex(features.index)
        age=(features.anchor-birth).dt.days/365.2425
        features['age_at_anchor']=age.where(age.between(0,120))
    plot(features.filter(like='_observed_lookback').mean(), out/'figures'/'observation_availability.png', 'Fraction of cohort with look-back records', 'Dataset')
    features.to_csv(out/'patient_features.csv',index_label='PAT_ID')
    features.notna().mean().rename('available_fraction').rename_axis('feature').to_csv(out/'feature_availability.csv')
    dictionary=[]
    for col in features:
        description='Observed export value; conflicting demographic values excluded.'
        if col.endswith('count') or 'records' in col or 'burden' in col: description='Count of records or unique observed entities in the inclusive pre-anchor look-back; zero denotes no qualifying records, not clinical absence.'
        elif 'weight_change' in col: description='100 * (anchor weight - prior weight) / prior weight; pre-anchor nearest observation within configured tolerance; conflicting ties unavailable.'
        elif 'latest_status' in col: description='Latest dated non-null status within look-back; conflicting statuses at latest timestamp unavailable.'
        elif col=='anchor': description='Unique demographic CONTACT_DATE anchor; no visit selected automatically.'
        elif col=='age_at_anchor': description='(Anchor date minus unambiguous birth date) / 365.2425 days; outside 0–120 years unavailable.'
        elif col.startswith('weight_kg_'): description='Weight in kg nearest the specified pre-anchor target within configured tolerance; unknown units and conflicting ties excluded.'
        elif col=='height_m_anchor': description='Latest unambiguous positive height in meters within the pre-anchor baseline tolerance.'
        elif col.endswith('observed_lookback'): description='True when at least one dated record occurs in the inclusive pre-anchor look-back.'
        elif col=='bmi_anchor': description='Anchor-window weight kg / height m squared; separately timed measurements, not necessarily a same-visit BMI.'
        dictionary.append({'feature':col,'dtype':str(features[col].dtype),'definition':description})
    pd.DataFrame(dictionary).to_csv(out/'feature_dictionary.csv',index=False)
    report.data['completed_modules'].append('patient_features')
    return len(cohort), metrics
