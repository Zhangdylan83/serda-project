# Real-data execution in SERDA

Use the seven structured files plus Notes.xlsx under Z:\PHI. Source workbooks are opened read-only and never edited. Choose an approved, empty output folder outside the source tree. Run from the transferred code directory:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<approved output directory>"
```

Replace the output placeholder with the authorized SERDA path. A new folder per run is recommended. Do not place outputs under Z:\PHI. No network or online installation is needed during analysis.

First review execution_report.json and data_quality_report.md. Exit code 0 means no module reported a failure (skipped/unavailable Notes stages still require review); 2 means at least one module failed and available outputs may be partial. CLI/configuration errors may also return 2. A zero exit status is not a substitute for reviewing parse failures, unit coverage and post-anchor counts.

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

## Notes audit and Anchor validation

Run only Notes plus the original Demographics reference, independently of cohort selection and medication loading:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA Notes audit directory>" --config config.yaml --notes-audit-only
```

Keep outputs in a new approved empty SERDA folder outside both Z:\PHI and the code repository. Do not use the existing structured-results folder for this standalone audit: it generates its own inventory/summary and does not reload the other six structured files. The full command below retains all structured analyses and adds Notes as dataset eight:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA full audit directory>" --config config.yaml --cohort-anchor-policy exclude_ambiguous_for_eda --anchor-day-policy pre_anchor_date_only
```

For strict full analysis, omit the two policy overrides. Notes auditing still runs even if strict cohort selection stops on the 17 ambiguous patients. Notes reference intersections and Anchor comparisons always use every original Demographics patient/date, not the 2,673-patient provisional subset. Actual reference counts are computed and should be checked against the reported 2,690 patients and 17 multiple-calendar-day patients. Notes cannot change their cohort membership or resolve a visit.

### Local schema discovery

Start with default Notes settings. Inspect `execution_report.json` locally for notes real_columns, mapping, missing/ambiguous fields, date parsing, linkage counts and NOTE_CSN granularity. Configure only headers actually present in the workbook. Merge these settings into existing config; preserve all seven-dataset overrides:

```yaml
files:
  notes: "Notes.xlsx"
# Set the actual worksheet name only if needed (multiple sheets require it).
# sheets:
#   notes: "EXACT EXISTING WORKSHEET NAME"
header_rows:
  notes: 0
columns:
  notes:
    note_type: "NOTE_TYPE"
    note_csn: "NOTE_CSN"
    line: "LINE"
    date: "NOTE_CONTACT_DATE"
    text: "NOTE_TEXT"
    anchor_flag: "Anchor"
    # patient: "PAT_ID"             # only if this field actually exists
    # encounter: "PAT_ENC_CSN_ID"    # only if a genuine encounter field exists
    # note_id: "NOTE_ID"             # only if a genuine note identifier exists
notes:
  note_key_fields: []
  note_key_verified: false
  line_start: 1
  encounter_linkage_verified: false
  export_reconstructed_text: false
  batch_rows: 1000
  max_fragments_per_note: 100000
  max_note_characters: 5000000
```

These mappings are suggested aliases to investigate, not verified real headers. Header rows are zero-based. Notes supports .xlsx/.xlsm read-only, rejects populated rows beyond header width and blank/colliding headers, and never executes macros. NULL/null/(null)/None and whitespace-only cells are missing; literal NA is preserved. NOTE_TEXT whitespace is otherwise preserved. Only case-insensitive trimmed Yes/No are recognized as Anchor values; other nonmissing values are audited as Other, never coerced into Yes.

Do not declare NOTE_CSN a note ID merely because one patient/date/type appears per CSN. Review `notes_csn_granularity_patient_audit.csv` and aggregate granularity counts; repeated LINE values and multiple note IDs/dates/types can reveal encounter-level groups or note versions. Same-day/same-type collisions may remain invisible without a validated export contract. Confirm real note identifier and version granularity locally. Only then configure a verified key, for example **if NOTE_ID is confirmed and mapped**:

```yaml
notes:
  note_key_fields: [note_id]
  note_key_verified: true
  line_start: 1
  encounter_linkage_verified: false
  export_reconstructed_text: false
  batch_rows: 1000
  max_fragments_per_note: 100000
  max_note_characters: 5000000
```

The list contains internal mapped field names. A verified composite key can be supplied when the export contract requires it; do not invent a metadata composite to hide duplicate notes. With unverified identity, rows/candidate-group quality and row-level Anchor date comparisons are still audited; distinct validated-note counts, note-level Anchor counts and text reconstruction stay unavailable. Patient linkage can be independently available even when note identity is unverified.

PAT_ID linkage uses text identifiers only. Numeric-coerced identifiers are withheld for review, not reformatted. If PAT_ID is absent, a true encounter field can link only through an unambiguous original-Demographics encounter-to-patient mapping; historical encounters not present there remain unlinked. NOTE_CSN is never automatically treated as PAT_ENC_CSN_ID. Any custom encounter mapping requires both an explicit columns.notes.encounter override and `notes.encounter_linkage_verified: true` after its clinical meaning is confirmed. Conflicting direct patient versus encounter assignments are withheld and counted. No names/MRNs are used. Unlinked rows remain in raw inventory but do not enter patient intersection/anchor counts.

### Review deliverables inside SERDA

| Output | Review |
| --- | --- |
| notes_inventory.csv | Row/patient/duplicate counts; candidate versus validated/reconstructed note counts; missing mapped fields; CSN granularity |
| notes_missingness.csv | All original columns, missing fractions and row counts |
| notes_type_distribution.csv | Fragment row frequencies and validated-note frequencies when identity is verified |
| notes_reconstruction_quality.csv | Missing/invalid LINE, gaps, duplicate/conflicting lines, source-order problems, metadata conflicts, failures and structural completeness |
| notes_anchor_summary.csv | Yes/No/Missing/Other/Conflicting at row, candidate and validated-note levels |
| notes_patient_intersections.csv | Notes source/matched/outside patients; Demographics without Notes; reference patients with Yes rows and verified Yes notes |
| notes_anchor_alignment_summary.csv | Yes notes/patients; row-date and validated-note date agreement; no matching note and multiple candidate notes |
| notes_multiple_anchor_summary.csv | Same alignment metrics restricted to original multiple-calendar-day Demographics patients; no patient is resolved |
| figures/notes_*.png | Type, Anchor row flags, candidate reconstruction quality, alignment and validated notes-per-patient distributions where available |
| Data_Audit_Summary.md | Combined audit summary and module status, also reflected in existing Markdown/JSON reports |

Full runs append Notes to dataset_inventory.csv and patient_set_intersections.csv without discarding the structured rows. Standalone runs include only Demographics/Notes because other structured datasets were not loaded. A Notes failure records a separate failure/skip and keeps structured feature tables, temporal outputs and figures available. Header-only Notes deliverables indicate a stage did not run; JSON gives the reason. Empty cells for unavailable counts are not zero. Exit code 2 can reflect a Notes failure while structured EDA succeeded; exit code 0 can still include intentional skipped reconstruction when note identity is unverified.

Local patient files include notes_reconstruction_patient_audit.csv, notes_per_patient_patient_audit.csv, notes_csn_granularity_patient_audit.csv and notes_anchor_alignment_patient_audit.csv. Review per-patient numbers of distinct Yes row dates, candidate/validated note dates, matching dates, multiple candidate notes, and the multiple-Demographics-anchor flag. Global aggregate agreement metrics without a validated prefix use row-level Anchor=Yes date evidence; validated-note metrics are separately labeled and unavailable until identity is verified. Missing or invalid dates are not matched. Multiple Yes notes on one day are counted separately from multiple days. Anchor clinical meaning still needs confirmation.

LINE ordering is numeric and uses configured line_start (confirm 0 versus 1). Identical same-line text is collapsed for reconstruction; conflicting text is never selected. Dates/types/patients that disagree within a key make its identity unresolved; conflicting flags/gaps/invalid fields prevent structurally complete reconstruction. Out-of-order fragments are flagged and sorted without modifying Excel. Structural completeness cannot establish missing trailing lines without a total/version specification. Oversized groups are explicitly withheld. With `export_reconstructed_text: true`, only verified structurally complete notes are optionally written to notes_reconstructed_text_SERDA_only.jsonl. All raw content stays in the source workbook; no snippets, identifiers or reconstructed text are printed.

Use adequate approved disk space for staging the approximately 200 MB Notes workbook. A read-only openpyxl iterator processes bounded batches, while exact-row duplicate checks and note grouping use SQLite under the approved output. Uncompressed text/indexes can exceed compressed workbook size by several times. openpyxl retains some workbook metadata/shared strings, so memory is not strictly constant. Temporary stages close/delete after handled failures; process interruption may leave `.notes-stage-*` folders. Review/delete them locally according to SERDA rules. All CSVs, Markdown/JSON clinical summaries, figures, staging data, identifiers and reconstructed note text must remain in SERDA and must never be pushed to GitHub.

No Notes clinical file has been analyzed outside SERDA. Local validation covers header-only workbooks, empty schemas, validation and failure isolation without fabricated clinical records. Test the actual headers, linkage, LINE start, note identity, reconstructed text and Anchor meaning inside SERDA before using results. No Frailty Label generation or predictor changes are included.
