# SERDA structured EHR pipeline

CPU-only, offline Python analysis for seven real Excel exports. No clinical data, mock records, or fabricated findings are included. Real-data execution has not been performed on DGX because datasets are available only in SERDA.

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<approved output directory>"
```

See [Windows_setup.md](Windows_setup.md) and [SERDA_execution_guide.md](SERDA_execution_guide.md). Code does not install packages or access the internet.

The supplied column names are the implementation reference; screenshots are not present in this workspace. Exact filenames are matched after punctuation/space normalization. Only the seven configured stems are processed; Imaging, Notes, and panel_dataset_extra_vars642026 are ignored. .xlsx/.xlsm use openpyxl; legacy .xls uses xlrd. Workbook macros are never executed. Every sheet must be chosen explicitly if a workbook has multiple sheets. Headers default to row 1 (configuration is zero-based).

Demographics defines one anchor per PAT_ID. Multiple anchors stop cohort-dependent analyses rather than selecting a visit. Missing IDs, invalid dates and conflicting export anchors block affected temporal modules. Other modules continue. Contact dates are compared and reported but are not substituted for missing event dates. IDs remain strings; numeric-coerced identifiers require review. Features use [-365, 0] days with exact timestamps; events later on the anchor day are post-anchor if the anchor is midnight. Confirm this convention against export semantics before interpreting results.

Weight and height require explicit supported units and exact measurement labels. Unsupported labels/units appear in measurement_unit_coverage.csv. No unit inference from values. Anchor weight/height uses up to 90 prior days; prior weights target -183/-365 days with 60-day tolerance, bounded by the look-back. Conflicting nearest weight ties remain missing. BMI can use measurements from different dates. Negative/zero measurements are excluded; extreme positive measurements are not silently corrected. Lab numerical values are not pooled without verified units. Alcohol comments, medication dosage text and raw records are not exported. Smoking prior status is inventoried and date-audited; latest status features use actual dated current statuses.

Outputs are sensitive and must remain inside SERDA: patient_features.csv contains PAT_ID and clinical features. Aggregate tables and figures are also clinical results. Diagnostic reports contain column names, file names, counts and issues, without names, MRNs or raw records. Small groups are not suppressed automatically; follow local rules before sharing any outputs.

Record counts retain duplicate rows; unique diagnoses and medication names collapse repeated entity values. Missing feature columns mean a module failed, not negative findings. Zero counts mean no qualifying recorded data. Feature availability measures non-null values, including zero counts; observed_lookback fields distinguish documentation coverage.

No frailty labels, supervised learning, GPU libraries, synthetic data or synthetic EDA. All figures and numerical reports are created only at runtime from actual supplied records.
