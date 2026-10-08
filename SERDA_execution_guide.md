# Real-data execution in SERDA

Use the seven files under Z:\PHI. Source workbooks are opened read-only and never edited. Choose an approved, empty output folder outside the source tree. Run from the transferred code directory:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<approved output directory>"
```

Replace the output placeholder with the authorized SERDA path. A new folder per run is recommended. Do not place outputs under Z:\PHI. No network or online installation is needed during analysis.

First review execution_report.json and data_quality_report.md. Exit code 0 means configured modules completed; 2 means at least one module failed and available outputs may be partial. CLI/configuration errors may also return 2. A zero exit status is not a substitute for reviewing parse failures, unit coverage and post-anchor counts.

Resolve mismatches locally using config.yaml, using exact real values:

```yaml
files:
  medications: "exact existing workbook filename.xlsx"
sheets:
  medications: "exact existing sheet name"
header_rows:
  medications: 0
columns:
  medications:
    patient: "exact patient identifier header"
    medication: "exact medication name/description header"
    date: "exact order date header"
```

These are configuration placeholders, not claims about actual medication headers. Use the real headers listed in execution_report.json. Do not invent headers. Missing required columns stop their dataset module. For multiple-sheet errors, inspect workbook tabs locally and configure the correct sheet. If there is no usable header row, inspect the real export locally and configure its zero-based row index.

Dates accept strings and Excel serial dates in the configured range. NULL/null/(null)/None and blank cells are missing. NA is preserved as a literal value. Numeric dates outside the Excel range fail parsing; numeric YYYYMMDD dates require an explicitly reviewed parser extension. Set dayfirst based on verified export conventions; ambiguous strings cannot establish their convention automatically. Timezone-bearing or mixed timezone dates require export review; the pipeline never silently shifts timestamps.

Mandatory cohort linkage uses PAT_ID exclusively. Confirm identifiers are consistent text exports across files. No MRN fallback. In strict mode, multiple demographic anchors require an approved index-visit definition or cohort export. Provisional EDA can exclude ambiguous patients as documented below. Event rows outside the demographic cohort and rows with missing IDs are excluded and separately counted. Conflicting supplied anchors among matched rows stop that module. Missing event dates are excluded and counted. No contact-date fallback or imputation.

Review dataset_inventory.csv, patient_coverage.csv, missingness tables and temporal_summary.csv before using features. Verify ICD source labels and measurement labels/units against the real exports. Weight feature tolerances are configurable. Twelve-month weight availability may be limited because its search window is clipped to the one-year look-back. Medication counts are order counts, not active prescriptions. Lab tables report component coverage without mixing units.

Outputs include aggregate CSV tables, PNG figures, patient_features.csv, feature_dictionary.csv, feature_availability.csv, execution_report.json, data_quality_report.md, EDA_summary.md and slide_ready_findings.md. Unavailable module features are null and marked unavailable; some module-specific artifacts may be absent, with reasons in execution_report.json. Keep all outputs in SERDA. Review results locally; do not send patient records, names, MRNs or clinical outputs to DGX/Codex.


## Provisional EDA: next run in SERDA

Transfer the updated code. Keep verified real file/sheet/header settings. The default config remains strict; use these CLI overrides for the immediate exploratory run into a new approved empty SERDA folder:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA provisional output directory>" --config config.yaml --cohort-anchor-policy exclude_ambiguous_for_eda --anchor-day-policy pre_anchor_date_only
```

Alternatively copy config.yaml to config_provisional.yaml and set:

```yaml
cohort_anchor_policy: exclude_ambiguous_for_eda
temporal_granularity: timestamp
anchor_day_policy: pre_anchor_date_only
lookback_days: 365
```

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA provisional output directory>" --config config_provisional.yaml
```

This retains exactly one distinct valid calendar anchor date per patient, normalized to midnight. All patients with two or more distinct anchor days are excluded; none gets an earliest/latest anchor. Missing-ID rows and patients having any missing/invalid anchors are excluded too. Repeated same-anchor rows collapse to one patient key after demographic attribute conflicts are audited; affected attributes stay null rather than choosing a value. Birth conflicts make age unavailable. Same-day distinct timestamps are counted and collapse only under calendar-day selection. Strict timestamp mode retains its failure on any multiple timestamp anchors or invalid demographic IDs/anchors.

The supplied prior run reported 2,708 rows, 2,690 patients, 2,673 unique-day patients and 17 multiple-day patients, with no missing anchors or same-day timestamp ambiguity. These counts are not hardcoded. Confirm the new actual-run `cohort_selection_summary.csv` and audits: 17 excluded patients and 2,673 final analyzable patients are expected from those reported inputs, subject to local verification. Excluded record counts are computed from all imported rows, including duplicates. Demographic conflicts are separately counted and do not force an arbitrary anchor choice.

Keep `cohort_selection_patient_audit.csv`, `cohort_excluded_records_patient_audit.csv`, `demographic_attribute_conflicts_patient_audit.csv`, patient_features.csv, and every clinical output entirely inside SERDA. No patient identifiers are printed or included in aggregate JSON/Markdown. Audit record positions are zero-based imported dataframe positions. Source workbooks remain unchanged. All results are **PROVISIONAL EDA ONLY, not the final validated research cohort**.

Review in order:

1. `cohort_selection_summary.csv`, cohort anchor diagnostics, demographic conflict counts and local patient audits.
2. `execution_report.json`: completed, failed and skipped modules; per-dataset outside-cohort and ambiguous-patient excluded row/patient counts; missing-ID and matched counts. Legitimate outside-cohort records are excluded without stopping a module.
3. `temporal_summary.csv`: missing dates, post-anchor dates, anchor-day exclusions and eligible look-back counts. `pre_anchor_date_only` uses the inclusive lower look-back boundary and requires event calendar date strictly before anchor calendar date. This excludes the entire anchor day even when time is missing. `at_or_before_timestamp` includes events at the anchor timestamp only, never later timestamps, including in calendar-day distance mode. The provisional midnight anchor is a conservative date boundary, not a verified prediction timestamp. Temporal density plots include excluded dates for audit; downstream clinical features use only the eligible window.
4. `patient_coverage.csv` (source-record coverage of the selected cohort), observation fields (eligible look-back coverage), ICD frequency/burden outputs, weight/BMI summary, monthly trajectory, lab coverage and alcohol/smoking status. Review units and weight tolerances. Missing/contradictory supplied event anchors fail only their temporal module; other datasets continue.
5. `patient_features.csv`, feature_dictionary.csv and feature_availability.csv. Unavailable clinical-module features, including medications when loading fails, are null and explicitly marked unavailable; zero is reserved for available-module patients with no qualifying records. Conflicting demographic attributes stay null. A clinical failure discards partial feature assignments for that dataset while retaining successful datasets.
6. `figures/*.png` and JSON `figure_files`. Successful eligible ICD/weight/BMI analyses generate actual PNGs, including weight and BMI distributions and weight changes where available. Each expected figure has a completed/failed/skipped status. No qualifying data causes a stated skip; rendering errors are recorded without blocking features.

Medication matching remains unresolved until verified exact medication/order-date headers are configured locally. Do not substitute CONTACT_DATE for order date. A medication load failure can leave exit code 2 while temporal EDA, other clinical summaries, features and figures succeed. Review the report rather than treating code 2 as proof that all results are unavailable.

For final cohort analysis, use config.yaml with `cohort_anchor_policy: strict_timestamp` and the original command at the top of this guide. The 17 ambiguous patients still require an approved research cohort/index-visit decision. Provisional exclusion does not validate the final research cohort. No synthetic data was generated; actual clinical execution must be tested inside SERDA before claiming success on the real files.
