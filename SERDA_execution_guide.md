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
  note_key_fields: [note_csn]  # explicit candidate text grain; not globally verified
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

## MRN linkage validation after Erika's guidance

Run the full eight-dataset MRN audit into a **new empty approved SERDA output directory**. Keep all existing verified file, sheet, header, medication, and Notes settings in config.yaml:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA MRN full-audit directory>" --config config.yaml --patient-key mrn --cohort-anchor-policy exclude_ambiguous_for_eda --anchor-day-policy pre_anchor_date_only
```

`--patient-key mrn` always requires a new empty output directory, regardless of the `overwrite` setting. It runs the existing structured and Notes audits, then reads all eight files for the MRN audit. The existing structured/feature outputs keep their PAT_ID baseline meaning. The `mrn_*.csv` tables are authoritative for MRN patient counts, coverage and anchor comparisons. Clinical features, labels and cohort membership are not altered. Structured module failures, including unresolved medication clinical columns, do not prevent a separate MRN scan if that workbook and its MRN header can be read.

Run Demographics and Notes alone if Anchor validation is the immediate priority:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA MRN Notes-audit directory>" --config config.yaml --patient-key mrn --notes-audit-only
```

This command cannot assess all-eight coverage; it marks the other six datasets and all-eight intersection unavailable. Reproduce the previous PAT_ID audit separately by omitting `--patient-key` or setting `--patient-key pat_id`. Every MRN run recomputes its PAT_ID comparison from the same workbook versions, rather than reading or overwriting the earlier PAT_ID run.

### Discover and validate each MRN column locally

Inspect `mrn_schema_validation.csv` for all eight actual headers, selected MRN field, alternatives, file/sheet/header choices, missing values, numeric cell counts, conflicts and date parsing. Prefer `PAT_MRN_ID` if present and locally confirmed. Other recognized names include `MRN`, `PAT_MRN`, `PATIENT_MRN`, `PATIENT_MRN_ID`, `MRN_ID`, `MEDICAL_RECORD_NUMBER`, and `MEDICAL_RECORD_NUM`. Use each workbook's actual header; do not assume names match across exports. When necessary, add exact local overrides under the existing `columns` section, for example:

```yaml
columns:
  demographics:
    mrn: "PAT_MRN_ID"
  notes:
    mrn: "EXACT VERIFIED NOTES MRN HEADER"
  medications:
    mrn: "EXACT VERIFIED MEDICATIONS MRN HEADER"
mrn_audit:
  batch_rows: 2000
```

The last two quoted values are placeholders, not claims that these are real headers. Preserve any other `columns`, `files`, `sheets`, and `header_rows` settings already verified in SERDA. Confirm MRN meaning with Erika/export metadata before interpreting patient counts. PAT_ID and NOTE_CSN are never substituted for a missing MRN. If both PAT_MRN_ID and another MRN-like field exist, the preferred field is selected and row-level disagreements are counted and withheld. Blank preferred values are not filled from alternatives. Text values retain leading zeros and case; surrounding whitespace is trimmed and counted. Numeric Excel MRN cells are withheld because their original formatting may be unrecoverable. Invalid/ambiguous headers and files are reported as failed scans.

### Review order

1. `mrn_schema_validation.csv` and `mrn_patient_mapping_audit.csv`: establish which datasets have usable direct MRNs, how many rows/PAT_ID groups lack them, where multiple PAT_IDs share an MRN, where a PAT_ID spans MRNs, and whether case/numeric-cell issues affect comparison. `mrn_patient_mapping_detail_SERDA_ONLY.csv` contains identifiers and stays inside SERDA.
2. `mrn_dataset_inventory.csv`, `mrn_patient_intersections.csv`, `mrn_coverage_comparison.csv`, and `mrn_pairwise_intersections.csv`: compare unique MRNs, Demographics coverage, outside-reference patients, missing reference patients, pairwise Jaccard overlap, possible case-only discrepancies, and patients present in all eight. Compare with `mrn_vs_pat_id_comparison.csv`; blank unavailable counts are not zero. The prior 2,690 PAT_ID patients are a check on the rerun, not an assumed MRN count. Improved overlap is measured; patient sets are never forced to agree. “Approximately the same” has no preset cutoff, so report actual fractions and discuss the acceptable threshold locally.
3. `mrn_anchor_alignment_summary.csv` and `mrn_multiple_anchor_summary.csv`: compare original PAT_ID and new MRN numbers of unique-day, multiple-day and missing-date Demographics anchors; inspect how the previously ambiguous PAT_ID cases map to MRNs. `mrn_anchor_patient_detail_SERDA_ONLY.csv` preserves identifier-level transitions locally. Nothing selects a visit or changes the cohort.
4. In those anchor summaries, inspect Notes Anchor=Yes row date matches, no matches, multiple candidate note keys, and validated-note counts when available. Candidate NOTE_CSN groups do not prove unique notes. Validated-note counts require the original Notes reconstruction audit to verify the configured key; MRN auditing does not alter that process. `mrn_notes_anchor_patient_detail_SERDA_ONLY.csv` is local. The clinical meaning of Anchor=Yes still needs confirmation.
5. `mrn_temporal_summary.csv`, `Data_Audit_Summary.md` and `execution_report.json`: examine MRN-linked event timing, missing dates, module failures and the dedicated **MRN-Based Patient Linkage Validation** section. Patient-level temporal diagnostics exclude MRNs with multiple or insufficient Demographics anchor timestamps from a single-point timing calculation; they do not exclude those patients from set intersection or resolve their anchors.

The MRN pass stores only identifiers, dates and audit flags in a temporary SQLite stage under the approved output folder. The original Notes audit handles NOTE_TEXT and reconstruction. An interrupted run can leave `.mrn-stage-*` or `.notes-stage-*` folders requiring local review. Keep those folders, all CSVs, reports, figures, MRNs, identifiers and clinical outputs inside SERDA. Do not upload results to GitHub. These code changes have not been validated on the real clinical workbooks outside SERDA and no real MRN/overlap outcome is asserted here.

## Independent rule-based GA extraction

This mode reads only Frailty Demographics and Notes.xlsx. It does not run the eight-dataset EDA, change predictor features, generate frailty labels or overwrite prior audit outputs. It stages note fragments in a temporary SQLite folder inside the approved extraction output; interruption may leave `.ga-stage-*` with PHI for local SERDA review.

First inspect actual Notes headers locally using the existing `--notes-audit-only` command and `execution_report.json`. Verify the real note identifier and version granularity with Erika or export documentation; `NOTE_CSN`/`CSN_ID` alone is not proof. Create a separate SERDA-only config copied from `config.yaml` with verified mappings, for example **only if those actual fields and meanings are confirmed**:

```yaml
files:
  notes: "Notes.xlsx"
sheets:
  notes: "<actual sheet name>"
header_rows:
  notes: 0
columns:
  notes:
    note_csn: "<actual CSN column, if used>"
    note_id: "<verified true note identifier, if present>"
    author: "<actual author field, if present>"
    mrn: "<actual direct MRN field>"
  demographics:
    mrn: "<actual direct MRN field>"
notes:
  note_key_fields: [note_id]
  note_key_verified: true
  line_start: 1
ga_extraction:
  fragment_join: newline
  note_type_patterns: ["geriatric\\s+oncology\\s+initial\\s+consult(?:ation)?"]
  template_patterns: ["geriatric\\s+components?"]
```

The example is illustrative, not a claim about real headers or the right grouping key. Merge these values into the existing config rather than replacing its other settings. If unique note identity is unverified, leave verification false: the command emits candidate-group quality audits, extracts no values and reports `audit_only_identity_unverified` (exit code 2). If the direct patient key or Demographics date is absent, it reports a schema failure. Do not set `note_key_verified: true` merely to bypass the guard. Confirm whether fragments require a newline, literal space or no separator. A repeated identical LINE is de-duplicated for reconstruction; conflicting, missing, nonnumeric, gapped or out-of-order LINEs are flagged. Source-order inversions are sorted numerically and audited; they do not alone block reconstruction. Gaps trigger manual review rather than a claim of missing text. Contiguous lines cannot prove the last line is present.

Run in Windows SERDA CPU with a **new empty** approved output root:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<new approved SERDA GA output root>" --config "<verified SERDA GA config.yaml>" --ga-extraction-only --patient-key mrn
```

For a verified direct PAT_ID export, use `--patient-key pat_id`. `--ga-output-subdir ga_run_2` changes only the new extraction subdirectory name. Do not point output into the source data directory or code checkout. A schema or configuration failure appears in `<output root>\ga_extraction\ga_execution_report.json` with no identifiers. The mode does not launch the expensive full pipeline.

Review `ga_schema_validation.json`, `ga_note_selection_audit.csv`, `ga_ungroupable_fragments_SERDA_ONLY.csv`, `ga_domain_coverage.csv`, `ga_extracted_scores.csv`, `ga_extraction_review_queue.csv`, `ga_extraction_summary.md` and `ga_execution_report.json`. All record-level CSVs contain identifiers or evidence and must stay inside SERDA. Exact date matching and Anchor=Yes are required; a configured type plus GA template gives rule-confirmed selection, while one gives candidate selection. This is **not** expert confirmation. Historical values, conflicting values and unsupported formats go to review. Mention coverage is not extraction accuracy. No accuracy metric can be reported until reference annotations are available. Confirm Erika's intended note type/template, author and version rules, Anchor meaning, score formats and previous-score language before interpreting the output clinically.

## Small-sample GA validation: Prepare, Run, Evaluate

Use the existing CPU Python environment and dependencies. Keep `notes.note_key_verified: false` unless its global contract was actually verified. Configure real file/sheet/header/key mappings as usual. Validation supports sample-scoped human approvals without changing that flag or any predictor output. `ga_validation.sample_size` defaults to 8 and permits 5–10; available candidates may be fewer. Replace the paths below with approved locations; the package directory must initially be new/empty and outside both the source folder and repository.

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<approved SERDA storage>\ga_validation" --config config.yaml --patient-key mrn --ga-validation-prepare
```

Prepare scans Demographics and Notes through the existing GA loader. It writes `prepare_audit/`, `reconstruction_audit.csv`, full candidate note JSON files with raw rows and character mappings in `candidates/`, `sample_manifest.csv`, `support_registry.csv`, `reference_annotations.csv`, `run_manifest.json`, `review.html` and `blocked_review.html`. The blocked HTML shows at most ten blocked groups; the reconstruction CSV and candidate files retain the full audit. Source-order inversions are numerically sorted and recorded, without changing source rows. Gaps remain questions for human review; no lines are invented. Conflicting patient/date/note identity or same-LINE text remain hard blocks. Different nonempty type/author/encounter/department values require review; missing optional metadata is recorded separately. Complete-looking LINE sequences do not establish document boundaries or terminal completeness.

Selection uses different patients first, then template and historical/score-layout variation, never successful extraction. Author metadata is shown when present; template diversity alone is not evidence of different doctors. The manifest fixes membership and ordering; Prepare refuses to replace it. Source SHA-256 fingerprints, code hashes, config, candidate hashes and registry are frozen. `local.*` support paths are provisional and are not Erika schema mappings. Generic GDS denominator/version must be clinically reviewed.

Open `review.html` offline in SERDA. Inspect the full text and raw rows. In `sample_manifest.csv`, only edit `identity_approved`, `reconstruction_approved`, `target_ga_approved`, `reviewer`, and `review_comment`. Set the three approvals to `yes` only for the reviewed sample. Multiple source Anchor dates require an explicit target-note human decision; approval does not change the cohort. If no reliable document boundary can be confirmed, leave approvals `no` and retain the reconstruction audit. Do not mark groups approved merely to generate predictions.

Fill `reference_annotations.csv` independently: `documented`, `not_documented`, `unclear`, or `not_reviewed`; documented fields require value, verbatim supporting evidence and reviewer. Leave a denominator blank when absent in the text. Mark `needs_erika_review=yes` for clinical questions. Do not change sample IDs or field paths. Read full notes before revealing CPU predictions to reduce anchoring bias.

After reviewing reconstruction, freeze the original extractor run:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<approved SERDA storage>\ga_validation" --config config.yaml --ga-validation-run --ga-validation-label baseline
```

Run reads frozen candidate texts/config, not a new sample; it refuses baseline if extractor source changed since Prepare. Unapproved samples get blocked rows. It creates `baseline/predictions.csv` (one row per sample/field), `raw_extractor_output.json`, the approval snapshot, version manifest and `review.html`. Evidence comes directly from extractor matches, with original-text offsets and Excel rows; all raw candidates are preserved. Expand the CPU section only after writing provisional references. These HTML files have no external fonts, scripts or network resources and contain PHI.

Compare the human references:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<approved SERDA storage>\ga_validation" --config config.yaml --ga-validation-evaluate --ga-validation-label baseline
```

This creates `baseline/evaluation/` with `reference_snapshot.csv`, `evaluation_by_field.csv`, `error_cases.csv`, an evaluation manifest and limitations. Exact values and explicitly recorded denominators are compared as strings (no clinical unit/score inference). Error categories distinguish missed values, false extraction, wrong value/denominator, unsupported documented content, unresolved values, blocked records and pending clinical review. No overall accuracy or population precision/recall is asserted. Later reference revisions use `--ga-evaluation-name review2` and never overwrite earlier references/results.

Only after reviewing baseline may rules be revised. Use the same frozen samples and `--ga-validation-label revised` for Run and Evaluate; results remain separate. The same development samples cannot become an independent test set. Do not upload any generated package file, even HTML or aggregate results, outside SERDA. Actual runtime, schema, template diversity, complete-note identity and extraction performance still require real-data execution and Erika's review.

## Review document grain before changing keys

For the described export, use the explicit candidate setting below, without asserting global verification. Existing file/sheet/header mappings must be retained and checked in SERDA. A custom department header is optional; map it only when its actual full name is known.

```yaml
notes:
  note_key_fields: [note_csn]
  note_key_verified: false
# Merge into columns.notes if needed:
#   note_csn: "<actual full NOTE_CSN column>"
#   department: "<actual full service-department column>"
```

Run into a **new** validation package, leaving earlier manifests and baseline results intact:

```powershell
python run_pipeline.py --data-dir "Z:\PHI" --output-dir "<approved SERDA storage>\ga_grouping_review" --config config.yaml --patient-key mrn --ga-validation-prepare
```

Read `prepare_audit/ga_linkage_schema.json` first. It records the actual logical patient key and source column, separately the configured document key/source columns, MRN and PAT_ID consistency-check columns, and department mapping. Console output contains only these column mappings, never patient values. NOTE_ID presence does not override the explicit NOTE_CSN choice. Missing configured key fields never cause fallback to a different column.

Then read `ga_note_grouping_summary.csv` in that folder. All counts refer to nonblank source rows. It reports NOTE_CSN groups, complete `(MRN, NOTE_CSN)` groups, CSNs with multiple MRNs/PAT_IDs, missing MRN/CSN rows, NOTE_IDs spanning contacts, CSNs spanning NOTE_IDs, identifier mapping multiplicity, and blocked CSNs. `same_partition_on_complete_id_rows` compares only rows having both identifiers; it is unavailable if there are no such rows. `same_partition_on_all_source_rows` also requires no missing identifiers and nonempty input. A missing-column comparison is unavailable, not zero. Neither equality flag establishes document identity or text completeness.

Filter `ga_note_grouping_detail_SERDA_ONLY.csv` by `partition_comparison != same_membership` to inspect differences. Join by NOTE_CSN to `ga_note_grouping_members_SERDA_ONLY.csv`, which includes every nonblank source row, Excel row number, MRN, PAT_ID, NOTE_ID and identifier status; missing-CSN rows remain visible. `ga_note_identifier_relations_SERDA_ONLY.csv` preserves identifier relationship counts. These files contain PHI and remain in SERDA. Global CSN identity conflicts block affected groups even if a custom composite key would split them into apparently consistent subgroups; single-sample approval cannot override those hard blocks.

`ga_note_metadata_audit_SERDA_ONLY.csv` and the offline review HTML expose missing optional values separately from differing nonempty values. Mixed department/type/author/encounter values require investigation and sample approval, not automatic group splitting. Identity conflicts, conflicting note dates/timestamps, missing essential fragments and different text at the same LINE remain hard blocks. Identical duplicate fragments retain all Excel-row mappings. Numeric LINE order is recovered even if source rows are shuffled; gaps/starting position require review without asserting data loss or inserting text. Department provenance must be confirmed with the export owner before interpreting a difference clinically.

Keep extraction comparison separate: this change alters preparation/auditing policy, not regex rules. An older package's baseline must use the prepared source version; do not edit its frozen notes or manifest. Re-prepare in a new folder to inspect the new grouping policy, and describe any changed sample/text boundaries when comparing outcomes. Real-file grouping equivalence and the clinical meaning of NOTE_CSN still require SERDA execution and export-definition review; no such result is claimed here.

## Approved GA inputs and draft-schema small-sample review (CPU only)

Use a new output directory outside the repository and input folder. Obtain approved
cohort/target lists before enabling `approved_master`; do not manufacture these lists
from keywords or set every record to confirmed. CSV columns and strict validation
contracts are documented in README's GA input contracts section.

Edit a local `config_serda.yaml` (merge these sections, do not duplicate YAML keys):

```yaml
notes:
  note_key_fields: [note_csn]  # recognizes NOTE_CSN and NOTE_CSN_ID
  note_key_verified: false   # per-sample approval remains required

ga_input:
  anchor_source: approved_master
  cohort_anchor_file: 'Z:\ApprovedProject\cohort_anchor_master.csv'
  target_note_manifest: 'Z:\ApprovedProject\target_ga_notes.csv'

ga_validation:
  sample_size: 8
  field_registry: erika_draft
```

`Z:\ApprovedProject` is a placeholder: use your actual approved SERDA project
storage. If authoritative files are unavailable, keep `anchor_source:
demographics_reference` and both file paths `null`; the package remains exploratory.
The target list is optional even with an approved master, but candidates then need
clinical selection. Missing/multiple/blocked patients remain in the coverage audit;
only unambiguous eligible candidates enter the sample pool.

PowerShell, from the repository directory:

```powershell
$gaOutput = 'Z:\ApprovedProject\ga_schema_review_01'
python run_pipeline.py --data-dir 'Z:\PHI' --output-dir "$gaOutput" --config config_serda.yaml --patient-key mrn --ga-validation-prepare
```

Read `input_scope_summary.md`, `reconstruction_audit.csv`, the SERDA-only target
mapping audits and `review.html`. Fill references using the full note. In
`sample_manifest.csv`, set the three approval fields to `yes` and supply a reviewer
only after individually verifying document identity, completeness and target status.
Then run:

```powershell
python run_pipeline.py --data-dir 'Z:\PHI' --output-dir "$gaOutput" --config config_serda.yaml --ga-validation-run --ga-validation-label baseline
python run_pipeline.py --data-dir 'Z:\PHI' --output-dir "$gaOutput" --config config_serda.yaml --ga-validation-evaluate --ga-validation-label baseline
```

Run/Evaluate use frozen samples/configuration, not the full Excel again. Prepare
scans Notes and the configured anchor source, not all eight clinical datasets.
Source Excel files and prior outputs are not modified. This mode reports coverage,
unsupported fields and reference comparisons; no overall accuracy, inferred labels,
clinical missingness claims or validated `ga_features.json` export is produced.

## Preferred next step: extract from the existing eight frozen notes

This new workflow replaces **repeated Prepare runs for extraction development**.
It does not replace or modify the previous audit or baseline. After updating code:

```powershell
cd "$env:USERPROFILE\Desktop\serda-project"
git pull --ff-only origin main
.\scripts\run_ga_erika_extract.ps1 `
  -PackagePath "$env:USERPROFILE\Desktop\serda-results\ga_grouping_review_02"
```

Use your actual existing code/package paths. The script uses tracked config without
changing local `config_serda.yaml`; creates a unique new sibling result directory;
and displays its `review.html` location. Source text and existing identity/reconstruction
approvals must pass integrity checks. Target approval is recorded separately; these
samples remain exploratory. Do not rerun Prepare or switch global verification on.

If the script reports missing `jsonschema`, install the updated requirements using
the approved SERDA online/offline dependency process once. No LLM/GPU is needed.
See [GA_SCHEMA_EXTRACTION.md](docs/GA_SCHEMA_EXTRACTION.md) for dependency commands,
`-OutputRoot`/`-PythonPath` options, sparse JSON semantics, actual field coverage,
known rule limitations and the later curated-note adapter.
