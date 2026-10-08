"""No patient fixtures, synthetic clinical records, or fabricated EDA results.

These checks use empty schemas, injected failures and standalone date boundaries.
Real cohort selection and clinical figures must be validated inside SERDA.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
import yaml
from serda_pipeline import analysis
from serda_pipeline.core import Report, PipelineError


class PipelineContracts(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load(Path('config.yaml').read_text())
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        (self.out/'figures').mkdir()
        self.report = Report()

    def test_strict_default_and_empty_cohort_rejection(self):
        self.assertEqual(self.config['cohort_anchor_policy'], 'strict_timestamp')
        demo = pd.DataFrame({'patient': pd.Series(dtype=str), 'anchor': pd.Series(dtype='datetime64[ns]')})
        for policy in ['strict_timestamp','exclude_ambiguous_for_eda']:
            with self.assertRaises(PipelineError):
                analysis.build_cohort(demo,self.report,dict(self.config,cohort_anchor_policy=policy),self.out)

    def test_prediction_boundary_and_date_only_option(self):
        # Standalone temporal boundaries, without patient identifiers or clinical values.
        anchor = pd.Timestamp('2000-01-01 12:00')
        date = pd.Series([anchor-pd.Timedelta(days=366), anchor-pd.Timedelta(days=365),
                          anchor-pd.Timedelta(days=1), anchor.normalize(), anchor,
                          anchor+pd.Timedelta(seconds=1), pd.NaT], dtype='datetime64[ns]')
        point = pd.Series(anchor, index=date.index)
        boundaries = SimpleNamespace(date=date,cohort_anchor=point,
            days_from_anchor=(date-point).dt.total_seconds()/86400)
        self.assertEqual(analysis.lookback_mask(boundaries,self.config).tolist(),
                         [False,True,True,True,True,False,False])
        conservative = dict(self.config,anchor_day_policy='pre_anchor_date_only')
        self.assertEqual(analysis.lookback_mask(boundaries,conservative).tolist(),
                         [False,True,True,False,False,False,False])
        boundaries.days_from_anchor=(date.dt.normalize()-point.dt.normalize()).dt.days
        self.assertFalse(analysis.lookback_mask(boundaries,self.config).iloc[5])

    def test_empty_event_linkage_and_figure_skip(self):
        cohort=pd.DataFrame({'patient':pd.Series(dtype=str),'anchor':pd.Series(dtype='datetime64[ns]')})
        events=pd.DataFrame({'patient':pd.Series(dtype=str),'date':pd.Series(dtype='datetime64[ns]')})
        self.report.data['datasets']['comorbidities']={}
        linked,metrics=analysis.temporal('comorbidities',events,cohort,self.config,self.report,self.out)
        self.assertTrue(linked.empty)
        self.assertEqual(metrics['lookback_records'],0)
        self.assertEqual(self.report.data['datasets']['comorbidities']['outside_cohort_rows'],0)
        self.assertIn('figure_comorbidities_record_density', [x['module'] for x in self.report.data['skipped_modules']])

    def test_missing_medications_and_clinical_failure_preserve_feature_exports(self):
        demo=pd.DataFrame({'patient':pd.Series(dtype=str),'anchor':pd.Series(dtype='datetime64[ns]')})
        cohort=demo.copy()
        datasets={'demographics':demo,
                  'comorbidities':pd.DataFrame({c:pd.Series(dtype=str) for c in ['patient','icd']}),
                  'labs':pd.DataFrame({c:pd.Series(dtype=str) for c in ['patient','component','value']})}
        for key,data in datasets.items():
            if key!='demographics': data['date']=pd.Series(dtype='datetime64[ns]')
            self.report.data['datasets'][key]={'missingness':{},'row_count':0}
        self.report.fail('load_medications','Required columns missing: date, medication')
        # Inject a module failure without creating any clinical records/cohort.
        with patch.object(analysis,'build_cohort',return_value=cohort), patch.object(
                analysis,'process_comorbidities',side_effect=RuntimeError('injected')):
            count,_=analysis.execute(datasets,self.config,self.report,self.out)
        self.assertEqual(count,0)
        self.assertIn('features_labs',self.report.data['completed_modules'])
        self.assertIn('features_comorbidities',[x['module'] for x in self.report.data['failed_modules']])
        self.assertEqual(self.report.data['feature_module_status']['medications'],'unavailable')
        features=pd.read_csv(self.out/'patient_features.csv')
        self.assertIn('medication_order_count',features)
        dictionary=pd.read_csv(self.out/'feature_dictionary.csv')
        medication=dictionary.loc[dictionary.module.eq('medications')]
        self.assertTrue(medication.module_status.eq('unavailable').all())
        self.assertTrue((self.out/'feature_availability.csv').exists())

    def test_empty_weight_analysis_has_all_null_schema_and_skip_reasons(self):
        frame=pd.DataFrame({c:pd.Series(dtype=str) for c in ['patient','value','measurement','units']})
        frame['date']=pd.Series(dtype='datetime64[ns]')
        frame['days_from_anchor']=pd.Series(dtype=float)
        features=pd.DataFrame({c:pd.Series(dtype=float) for c in analysis.CLINICAL_FEATURES['height_weight']})
        self.report.data['datasets']['height_weight']={}
        analysis.process_height_weight(frame,features,self.config,self.report,self.out)
        self.assertTrue((self.out/'weight_bmi_summary.csv').exists())
        self.assertEqual(len(list((self.out/'figures').glob('*.png'))),0)
        self.assertIn('figure_bmi_anchor',[x['module'] for x in self.report.data['skipped_modules']])

    def test_plot_failure_is_recorded_and_does_not_raise(self):
        with patch.object(pd.Series,'dropna',side_effect=RuntimeError('injected')):
            analysis.plot(pd.Series(dtype=float),self.out/'figures'/'render.png','Title','Axis',report=self.report)
        self.assertEqual(self.report.data['failed_modules'][0]['module'],'figure_render')
        self.assertNotIn('injected',self.report.data['failed_modules'][0]['reason'])

    def test_expected_figures_have_explicit_status_without_data(self):
        analysis.finalize_figure_status(self.report,self.out)
        self.assertEqual(len(self.report.data['skipped_modules']),len(analysis.EXPECTED_FIGURES))
        self.assertEqual(self.report.data['figure_files'],[])


if __name__=='__main__': unittest.main()
