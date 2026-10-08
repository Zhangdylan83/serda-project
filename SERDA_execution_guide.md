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

Mandatory cohort linkage uses PAT_ID exclusively. Confirm identifiers are consistent text exports across files. No MRN fallback. Multiple demographic anchors require an explicitly selected approved cohort export before rerunning. Event rows outside the demographic cohort and rows with missing IDs are excluded and separately counted. Conflicting supplied anchors among matched rows stop that module. Missing event dates are excluded and counted. No contact-date fallback or imputation.

Review dataset_inventory.csv, patient_coverage.csv, missingness tables and temporal_summary.csv before using features. Verify ICD source labels and measurement labels/units against the real exports. Weight feature tolerances are configurable. Twelve-month weight availability may be limited because its search window is clipped to the one-year look-back. Medication counts are order counts, not active prescriptions. Lab tables report component coverage without mixing units.

Outputs include aggregate CSV tables, PNG figures, patient_features.csv, feature_dictionary.csv, feature_availability.csv, execution_report.json, data_quality_report.md, EDA_summary.md and slide_ready_findings.md. Artifacts requiring failed modules will be absent. Keep all outputs in SERDA. Review results locally; do not send patient records, names, MRNs or clinical outputs to DGX/Codex.


## Next run after the observed real-data failures

Transfer the updated code and merge any local file/sheet/header settings into the updated config; do not lose your real medication column mappings. Run into a new empty approved output directory.

1. Review cohort_anchor_diagnostics.csv: patients_multiple_timestamps, patients_same_day_multiple_timestamps, and patients_multiple_calendar_days.
2. Review patient_set_intersections.csv. These are demographics-set comparisons before anchor selection, not validated temporal cohort coverage.
3. Enter the exact real medication/order-date headers under columns.medications. Do not substitute CONTACT_DATE for order date.
4. Keep strict defaults while the anchor definition is unresolved. This diagnostic run may still return exit code 2 and leave temporal figures absent.
5. If the research protocol explicitly uses an anchor calendar date, set both settings below:

```yaml
cohort_anchor_policy: calendar_day
temporal_granularity: calendar_day
```

This only resolves timestamps on the same day. It does not select among different dates. Different assessment dates require an approved index-visit definition or a separately implemented assessment-level design.

Timestamp mode reports same_anchor_day_after_timestamp_rows after successful cohort linkage. Calendar-day mode counts all timestamps on the anchor day as day 0. In either mode, missing/unparseable event dates are excluded and counted. Date parsing conventions remain unchanged.
