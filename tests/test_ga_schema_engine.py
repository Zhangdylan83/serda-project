"""Synthetic text/unit contracts only. No patients or real clinical evaluation."""
import unittest
from jsonschema import Draft202012Validator, FormatChecker
from serda_pipeline.ga_schema_engine import extract, schema_leaves


def flat(obj,prefix=''):
    result={}
    for k,v in obj.items():
        path=prefix+'.'+k if prefix else k
        if isinstance(v,dict):result.update(flat(v,path))
        else:result[path]=v
    return result


class EngineTests(unittest.TestCase):
    def check(self,text,expected):
        obj,audit=extract(text)
        values=flat(obj)
        for path,value in expected.items():self.assertEqual(values.get(path),value,(path,text,values))
        schema,leaves=schema_leaves();Draft202012Validator(schema,format_checker=FormatChecker()).validate(obj)
        self.assertEqual({a['field_path'] for a in audit},set(leaves))
        self.assertEqual({a['field_path'] for a in audit if a['extraction_status']=='extracted'},set(values))
        for f in audit:
            for m in f['accepted_evidence']+f['rejected_or_unresolved_candidates']:
                self.assertEqual(text[m['character_start']:m['character_end']],m['evidence_text'])
            if f['extraction_status']=='extracted':self.assertTrue(f['accepted_evidence'])
        return obj,{a['field_path']:a for a in audit}

    def test_requested_patterns(self):
        cases=[('MoCA: 15/30',{'cognition.moca.value':15,'cognition.moca.max':30}),
               ('15/30 on MoCA',{'cognition.moca.value':15,'cognition.moca.max':30}),
               ('Vulnerable Elders Survey-13 (VES-13): 10/10',{'physical_function.ves13.value':10}),
               ('SPPB of 1/12',{'physical_performance.sppb_total.value':1}),
               ('Blessed Orientation Memory Concentration Test: 6/28',{'cognition.bomc.value':6}),
               ('GDS of 7/15',{'psychological.gds15.value':7}),
               ('Independent with all ADLs',{'physical_function.adl.bathing':'independent','physical_function.adl.toileting':'independent','physical_function.adl.source':'global_statement'}),
               ('Needs assistance with shopping and medications',{'physical_function.iadl.shopping':'needs_assistance','physical_function.iadl.medications':'needs_assistance','physical_function.iadl.source':'itemized'}),
               ('Two falls during the past year',{'falls.any_fall':'yes','falls.number_of_falls.value':2,'falls.lookback_months':12}),
               ('No falls in the past 12 months',{'falls.any_fall':'no','falls.lookback_months':12}),
               ('Approximately 9 medications',{'polypharmacy.medication_count.value':9,'polypharmacy.medication_count.qualifier':'approximate'}),
               ('Lost 3 lb over the past 6 months',{'nutrition.weight_loss':'yes','nutrition.weight_loss_amount.value':3,'nutrition.weight_loss_amount.unit':'lb','nutrition.weight_loss_lookback_months':6})]
        for text,expected in cases:
            with self.subTest(text=text):self.check(text,expected)

    def test_all_numeric_instruments(self):
        cases={'ECOG: 2':'performance_status.ecog','KPS: 80%':'performance_status.kps',
               'Mini-Cog: 3/5':'cognition.mini_cog.value','MMSE 25/30':'cognition.mmse.value',
               'SLUMS 25/30':'cognition.slums.value','GAD-7: 8/21':'psychological.gad7.value',
               'MNA-SF: 9/14':'nutrition.mna_sf.value','OARS IADL total: 10/14':'physical_function.iadl.total.value',
               'PF-10 score: 80/100':'physical_function.mos_physical_function.score.value',
               'MOS tangible support: 70/100':'social_support.mos_social_support_tangible.value',
               'MOS emotional support: 80/100':'social_support.mos_social_support_emotional.value'}
        for text,path in cases.items():
            with self.subTest(text=text):
                obj,_=self.check(text,{});self.assertIn(path,flat(obj))

    def test_scalar_categorical_and_units(self):
        self.check('Gait speed: 0.8 m/s. TUG: 14 seconds. Current weight: 70 kg. BMI: 24.5. Vision: fair. Hearing: impaired. Uses a walker. Lives with spouse. Has a caregiver. PIMs: no. More than 10 medications. 3 chronic conditions.',
                   {'physical_performance.gait_speed_m_per_s':0.8,'physical_performance.timed_up_and_go_s':14,'nutrition.current_weight.value':70,'nutrition.current_weight.unit':'kg','nutrition.bmi':24.5,'comorbidity.vision':'fair','comorbidity.hearing':'impaired_unspecified','physical_function.assistive_device':'walker','social_support.lives_alone':'no','social_support.has_caregiver':'yes','polypharmacy.pims_present':'no','polypharmacy.medication_count.qualifier':'greater_than','comorbidity.condition_count.value':3})

    def test_no_inferred_denominators_or_interpretation(self):
        obj,_=self.check('MoCA score: 24.',{'cognition.moca.value':24})
        self.assertNotIn('max',obj['cognition']['moca']);self.assertNotIn('interpretation',obj['cognition']['moca'])
        obj,_=self.check('MoCA 15/30',{});self.assertNotIn('clinician_status',obj['cognition'])
        self.check('MoCA 15/30 (impaired)',{'cognition.moca.interpretation':'impaired'})

    def test_history_not_done_conflict(self):
        for text in ['Previous MoCA 15/30.','MoCA 15/30 last year.','MoCA 15/30 not performed.','No MoCA 15/30.','Mother scored MoCA 15/30.','MoCA 15/30 may be invalid.']:
            with self.subTest(text=text):
                obj,audit=self.check(text,{});self.assertNotIn('cognition.moca.value',flat(obj));self.assertEqual(audit['cognition.moca.value']['extraction_status'],'ambiguous')
        self.check('Previous MoCA 15/30; today MoCA 20/30.',{'cognition.moca.value':20})
        obj,audit=self.check('MoCA 15/30. MoCA 20/30.',{})
        self.assertEqual(audit['cognition.moca.value']['extraction_status'],'conflicting')
        self.assertNotIn('cognition.moca.value',flat(obj))

    def test_invalid_incomplete_and_version(self):
        for text in ['MoCA 31/30','MoCA 15/','MoCA -1/30','GDS 7/30','GDS 7']:
            with self.subTest(text=text):
                obj,_=self.check(text,{});self.assertFalse(any(p.endswith('.value') for p in flat(obj)))
        self.check('GDS-15: 7',{'psychological.gds15.value':7})

    def test_subscores_not_totals_no_arithmetic(self):
        obj,_=self.check('SPPB balance 3/4. SPPB gait 2/4.',{'physical_performance.sppb_balance.value':3,'physical_performance.sppb_gait.value':2})
        self.assertNotIn('physical_performance.sppb_total.value',flat(obj))
        obj,audit=self.check('SPPB total 9/12. SPPB balance 3/4. SPPB gait 2/4. SPPB chair stands 1/4.',{})
        self.assertEqual(audit['physical_performance.sppb_total.value']['extraction_status'],'ambiguous')
        self.assertNotIn('physical_performance.sppb_total.value',flat(obj))

    def test_function_negative_and_unspecified(self):
        obj,_=self.check('Impaired IADL. Does not need assistance with bathing.',{})
        self.assertNotIn('physical_function.adl.bathing',flat(obj));self.assertNotIn('physical_function.iadl.shopping',flat(obj))
        obj,_=self.check('Independent with ADLs except bathing.',{})
        self.assertNotIn('physical_function.adl.bathing',flat(obj))
        self.check('Bathing: dependent. Dressing: independent.',{'physical_function.adl.bathing':'dependent','physical_function.adl.dressing':'independent'})

    def test_clinician_not_patient_judgment(self):
        self.check('Clinician assessment: cognition impaired.',{'cognition.clinician_status':'impaired'})
        for text in ['Family reports cognition impaired.','Clinician assessment: cognition may be impaired.','Patient reports: clinician assessment: cognition impaired.']:
            obj,_=self.check(text,{});self.assertNotIn('cognition.clinician_status',flat(obj))

    def test_mos_explicit_items(self):
        self.check('Walking one block: limited a little. Social activity change over the past 6 months: much less active.',
                   {'physical_function.mos_physical_function.walking_one_block':'limited_a_little','social_support.mos_social_activity.change_6mo':'much_less_active'})

    def test_evidence_source_rows_and_null_distinction(self):
        text='MoCA 15/30';mapping=[dict(text_start=0,text_end=5,source_excel_row=8),dict(text_start=5,text_end=10,source_excel_row=9)]
        obj,audit=extract(text,mapping);field=next(f for f in audit if f['field_path']=='cognition.moca.value')
        self.assertEqual(field['accepted_evidence'][0]['source_excel_rows'],[8,9])
        obj,audit=extract('Nothing about GA documented in this software fixture.')
        self.assertEqual(obj,{})
        self.assertEqual(next(f for f in audit if f['field_path']=='note_id')['extraction_status'],'unsupported')
        self.assertEqual(next(f for f in audit if f['field_path']=='cognition.moca.value')['extraction_status'],'not_found')
        self.assertNotIn('null',__import__('json').dumps(obj))

    def test_otherwise_global_and_device_hierarchy(self):
        self.check('Needs assist with dressing, otherwise independent.',{'physical_function.adl.dressing':'needs_assistance','physical_function.adl.bathing':'independent','physical_function.adl.source':'global_statement'})
        self.check('Uses a cane. Uses a walker.',{'physical_function.assistive_device':'walker'})
        obj,audit=self.check('Uses a walker. No assistive device.',{})
        self.assertEqual(audit['physical_function.assistive_device']['extraction_status'],'conflicting')

    def test_negation_and_range_counts(self):
        for text in ['No history of falls.','Does not use a walker.','Two to three falls.','At least 9 medications.']:
            obj,_=self.check(text,{})
            if 'walker' in text:self.assertNotIn('physical_function.assistive_device',flat(obj))
            if 'medications' in text:self.assertNotIn('polypharmacy.medication_count.value',flat(obj))
            if 'falls' in text:self.assertNotIn('falls.number_of_falls.value',flat(obj))
        self.check('ECOG: 2.',{'performance_status.ecog':2})

    def test_every_supported_leaf_has_a_positive_software_example(self):
        from serda_pipeline.ga_schema_engine import SCORES, ADL, IADL, MOS
        examples=[]
        aliases=['VES-13','OARS IADL total','PF-10','SPPB total','SPPB balance','SPPB gait','SPPB chair stands','MoCA','BOMC','Mini-Cog','MMSE','SLUMS','GDS-15','GAD-7','MNA-SF','MOS tangible support','MOS emotional support']
        for (path,(_,maximum)),alias in zip(SCORES.items(),aliases):examples.append(f'{alias}: 1/{maximum or 100} (normal)')
        examples += ['Independent with all ADLs.','Independent with all IADLs.']
        mos_labels=['Vigorous activities','Moderate activities','Lifting groceries','Climbing several flights','Climbing one flight','Bending kneeling stooping','Walking more than a mile','Walking several blocks','Walking one block','Bathing and dressing']
        examples += [label+': limited a lot.' for label in mos_labels]
        examples += ['ECOG: 2.','KPS: 80%.','Gait speed: 0.8 m/s.','TUG: 12 seconds.','Two falls during the past year.',
                     '9 medications.','3 chronic conditions.','Vision: good.','Hearing: fair.','PIMs: yes.','Uses a walker.',
                     'Lives alone.','Has a caregiver.','Lost 3 lb over the past 6 months.','Current weight: 60 kg.','BMI: 23.4.',
                     'Social activity interference time over the past 4 weeks: some of the time.',
                     'Social activity change over the past 6 months: about the same.',
                     'Social activity versus peers: somewhat more limited.',
                     'Social activity interference extent over the past 4 weeks: slightly.']
        examples += ['Clinician assessment: '+name+' impaired.' for name in ['physical function','physical performance','falls','cognition','mood','comorbidity','nutrition','polypharmacy','social support']]
        seen=set()
        for text in examples:
            obj,_=self.check(text,{});seen.update(flat(obj))
        _,audit=extract('')
        supported={a['field_path'] for a in audit if a['rule_ids']}
        self.assertEqual(supported-seen,set())
        self.assertEqual(set(schema_leaves()[1])-supported,{'note_id','note_date'})

    def test_coupled_value_denominator_unit_and_qualifier_conflicts(self):
        for text,path in [('PF-10 10/20. PF-10 10/100.','physical_function.mos_physical_function.score.value'),
                          ('Current weight: 70 kg. Current weight: 70 lb.','nutrition.current_weight.value'),
                          ('9 medications. More than 9 medications.','polypharmacy.medication_count.value')]:
            obj,audit=self.check(text,{})
            self.assertEqual(audit[path]['extraction_status'],'conflicting')
            self.assertNotIn(path,flat(obj))

    def test_not_performed_without_numeric_value(self):
        obj,audit=self.check('MoCA not performed.',{})
        self.assertEqual(audit['cognition.moca.value']['extraction_status'],'ambiguous')
        self.assertEqual(audit['cognition.moca.value']['rejected_or_unresolved_candidates'][0]['review_reason'],'not_performed')

    def test_tracked_support_inventory_matches_actual_registry(self):
        import json
        from pathlib import Path
        data=json.loads((Path(__file__).resolve().parents[1]/'schemas'/'ga_schema_rule_support.json').read_text())
        _,audit=extract('')
        expected={f['field_path']:'explicit_formats_only' if f['rule_ids'] else 'unsupported_metadata' for f in audit}
        self.assertEqual({f['field_path']:f['support'] for f in data['fields']},expected)
