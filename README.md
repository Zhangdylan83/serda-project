# SERDA structured EHR pipeline

CPU-only, offline Python analysis for seven structured Excel exports plus Notes.xlsx as an eighth, audit-only dataset. No clinical data, mock records, or fabricated findings are included. Real-data execution has not been performed on DGX because datasets are available only in SERDA.

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<approved output directory>"
```

See [Windows_setup.md](Windows_setup.md) and [SERDA_execution_guide.md](SERDA_execution_guide.md). Code does not install packages or access the internet.

The supplied column names are the implementation reference; screenshots are not present in this workspace. Exact filenames are matched after punctuation/space normalization. The seven configured structured stems retain their existing analysis; Notes.xlsx has a separate audit pass. Imaging and panel_dataset_extra_vars642026 are ignored. .xlsx/.xlsm use openpyxl; legacy .xls uses xlrd. Workbook macros are never executed. Every sheet must be chosen explicitly if a workbook has multiple sheets. Headers default to row 1 (configuration is zero-based).

Demographics defines one anchor per PAT_ID. Strict mode stops cohort-dependent analyses on multiple anchors. Provisional EDA mode excludes ambiguous patients without selecting a visit; see the command below. Missing demographic IDs/anchors block cohort construction. Event rows with missing IDs or IDs outside the demographic cohort are excluded with aggregate warnings; conflicting supplied anchors among matched rows block affected temporal modules. Other modules continue. Contact dates are compared and reported but are not substituted for missing event dates. IDs remain strings; numeric-coerced identifiers require review. By default features use [-365, 0] days with exact timestamps; events later on the anchor day are post-anchor if the anchor is midnight. Confirm this convention against export semantics before interpreting results.

Weight and height require explicit supported units and exact measurement labels. Unsupported labels/units appear in measurement_unit_coverage.csv. No unit inference from values. Anchor weight/height uses up to 90 prior days; prior weights target -183/-365 days with 60-day tolerance, bounded by the look-back. Conflicting nearest weight ties remain missing. BMI can use measurements from different dates. Negative/zero measurements are excluded; extreme positive measurements are not silently corrected. Lab numerical values are not pooled without verified units. Alcohol comments, medication dosage text and raw records are not exported. Smoking prior status is inventoried and date-audited; latest status features use actual dated current statuses.

Outputs are sensitive and must remain inside SERDA: patient_features.csv contains PAT_ID and clinical features. Aggregate tables and figures are also clinical results. Diagnostic reports contain column names, file names, counts and issues, without names, MRNs or raw records. Small groups are not suppressed automatically; follow local rules before sharing any outputs.

Record counts retain duplicate rows; unique diagnoses and medication names collapse repeated entity values. Unavailable clinical modules have null feature columns and module_status=unavailable in the feature dictionary and availability table, never zero counts. Zero counts mean no qualifying recorded data. Feature availability measures non-null values, including zero counts; observed_lookback fields distinguish documentation coverage.

No frailty labels, supervised learning, GPU libraries, synthetic data or synthetic EDA. All figures and numerical reports are created only at runtime from actual supplied records.


## Real-run correction: anchor diagnostics and cohort scope

Before cohort construction, patient_set_intersections.csv reports source/demographic patient intersections and exclusions for successfully loaded datasets. A medication schema failure still prevents medication intersections, but its inventory now reports unique patients when PAT_ID matched.

cohort_anchor_diagnostics.csv and anchor_multiplicity_distribution.csv distinguish multiple timestamps on one day from genuinely different anchor dates. Both are aggregate outputs without patient identifiers. They are generated even if strict cohort construction stops. No earliest/latest visit selection and no deletion of multi-anchor patients occur.

Default cohort_anchor_policy is strict_timestamp, and temporal_granularity is timestamp. Only after study approval of date-based semantics may both be set to calendar_day. That collapses same-day timestamps but the anchor-day eligibility policy still excludes later timestamps; patients with different anchor calendar dates still stop cohort construction. An approved index-visit file or multiple-assessment sample definition remains future work if dates genuinely differ.

execution_report.json reports outside_cohort_rows, outside_cohort_patients, missing_patient_id_excluded_rows, matched_cohort_rows, matched_cohort_patients, and same_anchor_day_after_timestamp_rows for temporal modules. Missing IDs are a quality warning rather than evidence of outside-cohort membership. The program cannot identify whether an unmatched valid ID should have been in the research cohort without an independently approved cohort roster.

## Provisional EDA for the unambiguous subset

Strict mode remains the default. To unblock exploratory analysis in SERDA while excluding every patient with multiple calendar-day anchors, run:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA provisional output directory>" --config config.yaml --cohort-anchor-policy exclude_ambiguous_for_eda --anchor-day-policy pre_anchor_date_only
```

Equivalent settings in a copied `config_provisional.yaml` (preserve all verified file, sheet and column overrides from config.yaml):

```yaml
cohort_anchor_policy: exclude_ambiguous_for_eda
temporal_granularity: timestamp
anchor_day_policy: pre_anchor_date_only
lookback_days: 365
```

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA provisional output directory>" --config config_provisional.yaml
```

The unique valid calendar anchor is normalized to midnight. Patients with multiple calendar dates, any missing/invalid anchor, or missing IDs are excluded. Same-day repeated rows collapse to one cohort key; demographic attributes are checked across all rows, and conflicting attributes remain null (birth conflicts also make age null). No earliest/latest visit is selected and no Excel file is modified. Same-day distinct timestamps, if encountered, are counted and collapse by calendar date only in this exploratory mode.

For the supplied SERDA counts, the expected subset is 2,673 of 2,690 patients, excluding 17; these are user-reported counts, not a result of a local clinical-file run. `cohort_selection_summary.csv` reports actual run counts, including excluded source records and final analyzable patients. `cohort_selection_patient_audit.csv`, `cohort_excluded_records_patient_audit.csv`, and `demographic_attribute_conflicts_patient_audit.csv` contain patient identifiers and must remain entirely inside SERDA. Row positions are zero-based imported dataframe positions, not Excel row numbers. Patient identifiers are never printed.

Provisional outputs are explicitly labeled in execution_report.json, Markdown reports, the feature dictionary, and plot titles. They are **not the final validated research cohort**. Missing IDs/anchors continue to fail strict mode; multiple anchors continue to fail strict mode. For strict cohort work, run the original command with `cohort_anchor_policy: strict_timestamp`.

`pre_anchor_date_only` includes the lower look-back boundary and excludes the entire anchor calendar day, undated events, and all later events. `at_or_before_timestamp` includes events at the prediction timestamp and excludes later timestamps even with calendar-day distance calculations. Calendar-day distance mode no longer admits the entire anchor day. In provisional mode midnight is a conservative calendar boundary, not a verified assessment timestamp. When event timing is insufficient, use the documented date-only exclusion. Temporal density figures show all valid linked event dates for auditing, including excluded post-anchor dates; clinical summaries/features use only the eligible window. No frailty labels or post-anchor predictors are constructed.

Medication header matching remains unresolved: enter verified exact headers locally when available. Its load failure is recorded and medication feature columns remain null/unavailable while other datasets continue. Exit code 2 can therefore accompany usable provisional features and PNGs. Review completed_modules, failed_modules, skipped_modules, feature_module_status and figure_files. Figure failures do not discard clinical features; absent figures have explicit skip/failure reasons. Successful ICD and weight analyses produce burden/weight/BMI summaries and PNGs when qualifying observations exist. Unsupported units or no eligible measurements are reported, not replaced with fabricated values.

The changes require validation on the actual files inside SERDA. No synthetic data or real clinical results were generated in this workspace.

## Notes.xlsx: eighth dataset, audit only

Run Notes profiling and Anchor validation independently inside SERDA:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA Notes audit directory>" --config config.yaml --notes-audit-only
```

This loads only original Frailty Demographics and Notes. It does not build a cohort, require resolved Demographics anchors, load medications, generate labels, or modify predictors. All 2,690 reported reference patients and the 17 reported multiple-calendar-day patients remain in the reference comparison; counts are measured locally, not hardcoded. Full EDA commands above now also run the Notes audit after the existing seven-dataset analysis, including when strict cohort construction fails. Notes failure is reported separately and leaves structured-EHR artifacts intact.

Actual workbook headers are discovered locally and recorded in execution_report.json. The suggested field aliases (`NOTE_TYPE`, `NOTE_CSN`, `LINE`, `NOTE_CONTACT_DATE`, `NOTE_TEXT`, `Anchor`, optionally `PAT_ID`, `PAT_ENC_CSN_ID`, `NOTE_ID`) are not claims about the actual file. File/sheet/header/column overrides use `files.notes`, `sheets.notes`, `header_rows.notes`, `columns.notes`; see the execution guide for exact configuration examples.

Default `notes.note_key_verified: false` profiles rows and candidate groups only. NOTE_CSN is not assumed unique: the audit reports how many CSNs span multiple patients, note IDs, dates or types and repeat line numbers. Counts of distinct validated notes, reconstructed notes, and note-level Anchor flags stay unavailable until a genuine identifier/export granularity has been verified locally and `notes.note_key_fields` configured with `notes.note_key_verified: true`. Structural tests alone cannot prove that same-day/same-type notes have not collided. Composite metadata is not a substitute for a verified note identity.

A mapped PAT_ID is used as supplied after identifier checks. Encounter-only linkage uses the original Demographics encounter-to-patient mapping only when each encounter has one known patient; conflicting mappings remain unlinked. A custom encounter field, including any explicit NOTE_CSN encounter mapping, additionally requires `notes.encounter_linkage_verified: true`. No MRN, name, or implicit CSN fallback is used. Direct patient/encounter disagreements are withheld and counted. Missing linkage does not prevent row profiling.

Required aggregate deliverables are notes_inventory.csv, notes_missingness.csv, notes_type_distribution.csv, notes_reconstruction_quality.csv, notes_anchor_summary.csv, notes_patient_intersections.csv, notes_anchor_alignment_summary.csv, notes_multiple_anchor_summary.csv and Notes PNGs under figures/. Notes rows are appended to dataset_inventory.csv and patient_set_intersections.csv when available; original seven-dataset rows remain. Data_Audit_Summary.md, EDA_summary.md, data_quality_report.md and execution_report.json describe Notes status. Patient-linked detail files have `_patient_audit.csv` names and remain in SERDA.

Reconstruction uses verified keys and numerically ordered LINE values. Identical line fragments collapse for text; missing/noninteger lines, gaps, differing text for the same line, contradictory metadata, and size limits are audited. Source order is audited separately from sorted reconstruction. Contiguous lines show structural completeness only: missing trailing lines cannot be detected without an export total/version contract. Blank/NULL conventions match structured loading and raw NOTE_TEXT whitespace is preserved. `notes.export_reconstructed_text: true` optionally writes validated structurally complete text to `notes_reconstructed_text_SERDA_only.jsonl` inside the approved output; default is false.

Anchor comparison is an audit of calendar dates, not label generation or predictor engineering. Aggregate and local patient reports distinguish Yes fragment rows, candidate groups and validated Yes notes; compare exact date-set agreement, partial overlap, missing matches and multiple candidates across all reference patients and separately for the multiple-Demographics-anchor subgroup. Unknown/invalid dates and conflicting flags remain unresolved. Anchor=Yes clinical meaning still needs confirmation; no earliest/latest visit is chosen and the 17 patients are not automatically resolved.

Notes uses read-only openpyxl and bounded batches with a disk-backed SQLite stage under the approved output folder. That stage contains PHI and is deleted when the audit closes, including handled failures; interrupted runs may leave `.notes-stage-*` folders requiring local review. Reserve adequate approved disk space: the uncompressed staged data and indexes can exceed the 200 MB workbook size several times. openpyxl may retain the workbook shared-string table, so memory is not strictly constant. Keep output folders outside the code repository. Never upload Notes, any patient audits, reconstructed text, or patient-derived summaries/figures to GitHub.

The actual Notes workbook has not been accessed here. Local tests use header-only workbooks, empty schemas and injected failures, not synthetic clinical records. Schema semantics, reconstruction and real results still require testing inside SERDA.

## MRN-based linkage audit across eight datasets

`--patient-key mrn` adds an MRN linkage audit for all eight source workbooks to the existing run. The seven structured analyses, Notes reconstruction, predictor columns, figures, and cohort rules continue to run as before. The new `mrn_*.csv` files and the **MRN-Based Patient Linkage Validation** section of `Data_Audit_Summary.md` are the patient-level MRN audit. Existing `dataset_inventory.csv`, `patient_set_intersections.csv`, `patient_features.csv`, and clinical figures remain the PAT_ID-based baseline for direct comparison; no clinical predictors, labels, or cohort membership are changed.

Use a **new empty approved output directory inside SERDA**, separate from any earlier PAT_ID output. The MRN command refuses to overwrite a nonempty output directory even if `overwrite: true` is configured:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA MRN full-audit directory>" --config config.yaml --patient-key mrn --cohort-anchor-policy exclude_ambiguous_for_eda --anchor-day-policy pre_anchor_date_only
```

For Demographics/Notes only, including MRN-based Anchor comparison without loading the other six structured workbooks:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA MRN Notes-audit directory>" --config config.yaml --patient-key mrn --notes-audit-only
```

To reproduce the prior PAT_ID audit in another new directory, omit `--patient-key` or set `--patient-key pat_id`. MRN comparison columns recompute PAT_ID counts from the same input workbooks as that MRN run; they do not read or alter any older results. The earlier 2,690 PAT_ID patients and 17 multiple-day cases are checkpoints supplied from the previous run, never hardcoded as MRN counts.

MRN headers are discovered separately in every workbook. The audit prefers `PAT_MRN_ID` when present; known aliases such as `MRN` are used only when unambiguous. Override an actual different header with `columns.<dataset>.mrn` in config.yaml. The selected MRN column is checked against any other recognized MRN column row by row. Disagreements are withheld and counted. No missing MRN is filled from PAT_ID, name, encounter, another MRN column, or Notes NOTE_CSN. MRNs are compared as exact trimmed strings; leading zeros and case are retained. Numeric Excel MRN cells are withheld because leading zeros may already have been lost. Case-only possible matches are reported as diagnostics and never merged. Mapping to multiple PAT_ID values and PAT_ID mapping to multiple MRNs are audited both per dataset and across datasets. Clinical/export owners must confirm that a discovered header has MRN semantics inside SERDA.

Requested outputs are `mrn_schema_validation.csv`, `mrn_patient_mapping_audit.csv`, `mrn_dataset_inventory.csv`, `mrn_patient_intersections.csv`, `mrn_coverage_comparison.csv`, `mrn_anchor_alignment_summary.csv`, `mrn_multiple_anchor_summary.csv`, and `mrn_vs_pat_id_comparison.csv`. Additional outputs include `mrn_pairwise_intersections.csv`, `mrn_temporal_summary.csv`, `mrn_pat_ids_per_mrn_distribution.csv`, `mrn_mrns_per_pat_id_distribution.csv`, `mrn_records_per_patient_summary.csv`, and local `_SERDA_ONLY.csv` mapping and anchor detail files. Unavailable counts are blank with a status or failure reason, never presented as zero. Only an eight-dataset run can calculate the all-eight intersection; `--notes-audit-only` marks it unavailable.

The MRN summary compares Demographics unique PAT_ID versus unique MRN counts, pairwise overlap changes, all-eight overlap, and anchor multiplicity. It tracks how the original multiple-day PAT_ID groups map to MRNs and identifies new MRN multiple-day groups, without selecting visits. Notes Anchor=Yes comparisons use MRN row dates; candidate NOTE_CSN or NOTE_ID groups remain explicitly unverified until note identity is confirmed. Validated note counts are taken only from the existing Notes reconstruction audit when its key is verified and consistent. The meaning of Anchor=Yes still requires clinical confirmation. Similar patient populations are an empirical question: the audit reports exact counts and overlap; it does not impose a threshold for “approximately the same.”

The MRN pass streams only identifiers, dates and audit flags to a temporary SQLite database inside the approved output folder. Notes text is not copied into this MRN stage. The original Notes audit retains its own validated reconstruction process. Both temporary stages contain PHI and are cleaned after handled runs; review any leftover `.mrn-stage-*` folder locally after interruption. Never move the output folder or identifier-bearing audit files to GitHub. The actual eight clinical workbooks are unavailable here and must be run in SERDA before making any real-data claim.
