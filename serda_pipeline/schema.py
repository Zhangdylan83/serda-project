"""Observed export schemas. Unknown medication fields are resolved at runtime."""
import re

def normalize(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())

COMMON = {
    'patient': ['PAT_ID'], 'encounter': ['PAT_ENC_CSN_ID'],
    'contact': ['CONTACT_DATE'], 'mrn': ['PAT_MRN_ID'], 'name': ['PAT_NAME'],
}
SCHEMAS = {
 'demographics': dict(COMMON, anchor=['CONTACT_DATE'], birth=['BIRTH_DATE'], sex=['SEX'],
    race=['DerivedRollUpRace'], ethnicity=['EthnicityRollUp'], marital=['MARITAL_STATUS'],
    education=['EDUCATION_LEVEL'], years_education=['YEARS_EDUCATION'],
    education_source=['EDUCATION_SOURCE'], procedure=['PRC_ID'], procedure_name=['PRC_NAME'],
    status=['STATUS'], department=['DEPARTMENT_NAME']),
 'comorbidities': dict(COMMON, date=['Encounter DX or Noted Date'], diagnosis=['Diagnosis'],
    diagnosis_name=['Diagnosis_Name'], icd=['ICD10_Code'], source=['Source']),
 'height_weight': dict(COMMON, date=['RECORDED_TIME'], measurement=['MeasurementName'], value=['EncValue'], units=['Units']),
 'labs': dict(COMMON, date=['DrawnDateTime'], order=['ORDER_PROC_ID'], test=['LabTestName'],
    component_id=['COMPONENT_ID'], component=['ComponentName'], value=['ORD_VALUE']),
 'alcohol': dict(COMMON, anchor=['AnchorEventDate'], date=['AlcoholStatusDate'], status_type=['StatusType'],
    alcohol=['AlcoholUse'], comment=['Alcohol_Comment']),
 'smoking': dict(COMMON, anchor=['Anchor Event Date'], smoking=['Current Smoking Status'],
    date=['Current Smoking Status Date'], prior_smoking=['Smoking Status One Year Prior'],
    prior_date=['Smoking Status One Year Prior Date']),
 'medications': dict(COMMON, anchor=['AnchorEventDate', 'Anchor Event Date'],
    medication=['MedicationName', 'Medication Name', 'Medication Description', 'MEDICATION_NAME', 'MED_DESCRIPTION'],
    date=['OrderDate', 'Order Date', 'ORDER_DATE', 'Medication Order Date'],
    route=['Route'], dosage=['Dosage Instructions', 'SIG', 'Dosage']),
}
STEMS = {'demographics':'Frailty Demographics', 'comorbidities':'Comorbidities',
         'height_weight':'Height and Weight', 'labs':'Labs', 'alcohol':'Alcohol Usage',
         'smoking':'Smoking Status', 'medications':'Medications'}
REQUIRED = {'demographics':['patient','anchor'], 'comorbidities':['patient','date','icd'],
 'height_weight':['patient','date','measurement','value','units'],
 'labs':['patient','date','component','value'], 'alcohol':['patient','anchor','date','alcohol'],
 'smoking':['patient','anchor','date','smoking'], 'medications':['patient','date','medication']}
