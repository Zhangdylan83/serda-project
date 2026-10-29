# GA schema extraction from existing frozen notes

This **new engine** operates on the selected notes in an existing validation package.
It never invokes Prepare, reads Demographics/Notes Excel, enumerates all candidate
JSON files, resamples notes or changes the original baseline. This is CPU-only Python;
no LLM, GPU, cloud service or external inference. Schema source is the unchanged
`schemas/ga_note_extraction_schema.json` (Erika draft, not a final clinical standard).

## SERDA: update and run

From the existing repository in PowerShell:

```powershell
cd "$env:USERPROFILE\Desktop\serda-project"
git pull --ff-only origin main
.\scripts\run_ga_erika_extract.ps1 `
  -PackagePath "$env:USERPROFILE\Desktop\serda-results\ga_grouping_review_02"
```

The launcher uses `.venv\Scripts\python.exe` and tracked
`configs/serda_ga_erika.yaml`. It does **not** read or edit `config_serda.yaml`.
The output is a uniquely named sibling of the source package, for example
`serda-results\ga_schema_v1_20261029_153000_<unique>`. The existing source package's
parent must be approved SERDA storage. To choose another approved existing directory
or existing Python environment:

```powershell
.\scripts\run_ga_erika_extract.ps1 `
  -PackagePath "$env:USERPROFILE\Desktop\serda-results\ga_grouping_review_02" `
  -OutputRoot 'Z:\ApprovedProject\ga-results' `
  -PythonPath 'C:\path\to\approved\.venv\Scripts\python.exe'
```

Those paths are examples; choose actual approved directories. Do not place results
inside the repository or source package. No routine YAML editing is required.
`jsonschema>=4.18,<5` is the only new dependency. One-time dependency update, if the
approved SERDA environment permits package downloads:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If internet is unavailable, use the existing approved offline wheel-installation
process in Windows_setup.md with the updated requirements and **Windows-compatible**
wheels (not DGX/Linux wheels). The launcher checks dependencies and fails before
extraction when they are missing; it never downloads or installs anything itself.

Direct Python equivalent (no PowerShell required):

```powershell
.\.venv\Scripts\python.exe -m serda_pipeline.ga_frozen_extract `
  --package "$env:USERPROFILE\Desktop\serda-results\ga_grouping_review_02" `
  --output-dir "$env:USERPROFILE\Desktop\serda-results\ga_schema_v1_run01" `
  --config configs/serda_ga_erika.yaml
```

## Input contract and approvals

The source package must contain its original `run_manifest.json`,
`sample_manifest.csv`, and the candidate JSON files named by its frozen membership.
The reader checks membership/order, immutable metadata, candidate hashes, source
text/offset agreement, and existing identity/reconstruction approvals with reviewer.
It does not require the source package to have been built with the current code,
current field registry, or a new schema snapshot. It reads no unselected candidates.

The previously approved identity and reconstruction fields must be `yes`; the new
extractor never modifies approvals or grants them automatically. Missing approvals,
content changes or hard input blocks fail early. Review the original package locally
if approval is missing; do not fabricate approval just to run the script. Existing
`target_ga_approved` is copied as a **source-package manual approval**, not promoted
to Erika/clinical-team confirmation. Unconfirmed targets can be used as development
samples if identity and reconstruction were approved. The whole frozen-package run
remains an exploratory development sample, regardless of that flag.

The tracked Excel mappings document the export contract, but are NOT used to reload
Excel during extraction. They keep MRN (`PAT_MRN_ID`) separate from PAT_ID, use
`NOTE_CSN_ID`, `LINE`, `NOTE_TEXT`, `NOTE_CONTACT_DATE`, `Anchor` and `SERVICE_NAME`.
Global `notes.note_key_verified` remains false. No cohort or target classifier is
added. Original EDA, audit, predictor features and old regex baseline are unchanged.

## Actual rule coverage

All rules below operate on exact source text with offsets. They cover **explicit
formats**, not arbitrary narrative. The generated `support_registry.csv` lists every
schema leaf and its rules. There are 114 rule-supported clinical leaves, each tested
with an explicit positive software example, and two unsupported metadata leaves
(`note_id`, `note_date`). This is a software inventory, **not 114 clinically validated
extractors or a real-data coverage rate**. Document identity is instead preserved in
the source package and run manifest; no note identifier/date is guessed from prose.

| Domain | Implemented explicit formats and limits |
|---|---|
| Performance | ECOG 0–4, KPS 0–100, with labels; no inferred functional scores |
| Physical function | VES-13; OARS IADL total; six ADL and seven IADL items; independent/needs assistance/dependent; scoped global ADL/IADL statements; named-item “otherwise independent”; explicit MOS/PF-10 score and labelled limitation items; cane/walker/wheelchair/explicit no device |
| Physical performance | SPPB total and **explicitly SPPB-labelled** balance/gait/chair-stand scores; gait speed in m/s; TUG in seconds. No unlabelled component assignment, total calculation, or missing subscore derivation |
| Falls | Explicit no falls, positive history/count, numeric or zero–ten word counts, qualifiers; explicitly stated 6/12 months or past year mapped to 12 months. No invented lookback or count from bare “no falls” |
| Cognition | MoCA, BOMC/full Blessed Orientation Memory Concentration name, Mini-Cog, MMSE, SLUMS; numeric values before or after instrument; explicit denominator only |
| Psychological | GDS-15 only with explicit 15-item name or /15 denominator; GAD-7. Generic GDS without version evidence is unresolved |
| Comorbidity | Explicit chronic-condition/comorbidity count; labelled vision/hearing ratings. No counting diseases from a problem list |
| Nutrition | Explicit loss, amount in lb/kg, stated month period; explicit current weight and units; BMI; MNA-SF. No unit conversion, BMI calculation or interpretation from thresholds |
| Polypharmacy | Explicit medication counts including approximately/about/roughly/around/~ and > / more-than qualifiers; explicit labelled PIM yes/no. No counting a medication list or inferring PIMs from drug names |
| Social support | Explicit living alone/with named household relationship, has/no caregiver; labelled MOS tangible/emotional scores; explicit labelled social-activity items including required 4-week/6-month context. “Lives independently” does not establish living alone |
| Interpretations/statuses | Explicit attached normal/borderline/impaired score interpretation; explicit “clinician/geriatrician/physician assessment/impression: [domain] impaired/not impaired”. Patient/family reports and tentative judgments do not become clinician status |

Numeric patterns accept `MoCA: 15/30`, `15/30 on MoCA`, full VES-13 followed by its
acronym, `SPPB of 1/12`, full Blessed test name, and `GDS of 7/15`. A documented
`MoCA score: 24` can yield value=24 with max **omitted**. Bounds/version guards do not
supply missing denominators. PF-10 lacks a fixed denominator in this draft; no
fixed denominator is imposed. Other instrument range guards follow the draft's
stated ranges, without threshold-based interpretations.

Important unsupported **expressions** even for rule-supported fields: arbitrary
paraphrases, broad clinical reasoning, long-range/section-level temporal context,
uncertain clinician impressions, generic “Blessed” without identifying the specific
test, unlabelled SPPB “stands” or subscores, complex ADL exceptions and mixed clauses,
implicit medication inventories, unlabelled MOS questionnaire responses, ambiguous
units/versions or intervals. These are retained as unresolved when a candidate is
recognized; otherwise rules may produce `not_found`. There is no claim of complete
negation, temporality or coreference handling.

SPPB draft instructions about assigning subscores to sum to total are not treated
as permission to invent values: explicit mismatches are flagged and values withheld.
The draft's binary clinician status cannot faithfully express “may have cognitive
issues”; such uncertainty is withheld for Erika's review. No Fit/Vulnerable/Frail
label or cognitive impairment label is inferred from scores.

## Clinical JSON and diagnostics

- `ga_features.jsonl`: one **sparse schema-valid object** per selected note, in frozen
  sample order. There are no extra metadata keys outside Erika's schema.
- `extraction_evidence.jsonl`: record index/sample ID, separate input approval flags,
  and one diagnostic per schema leaf with accepted evidence, unresolved/rejected
  candidates, original character offsets, Excel rows, rule ID and reason.
- `field_coverage.csv`: counts per field across notes; denominator explicitly given.
- `extraction_summary.csv`: notes, field–note pairs and status counts.
- `support_registry.csv`: actual explicit-format rules versus unsupported fields.
- `review.html`: full unchanged note first, then expandable predictions. Green means
  accepted by rules, amber unresolved/rejected/conflicting, grey keyword only. An
  overlapping unresolved span takes visual precedence. Unsupported fields are
  identified in table status, not highlighted as clinical evidence.
- `run_manifest.json`: source membership/content hashes, source-package approval
  provenance, code/config/schema fingerprints and output hashes; `schema_snapshot.json`
  preserves the exact draft used.

**Why unresolved keys are omitted instead of null:** Erika defines null as “not
documented.” A machine parse failure does not establish that. Her schema has no
required fields, so omitted unresolved fields are structurally valid. Always read
clinical JSON together with diagnostics; never count omission as clinical absence.
Statuses are `extracted`, `not_found`, `unsupported`, `ambiguous`, `conflicting`.
Every accepted non-null leaf has a source match and unchanged-text offsets; evidence
is captured during parsing, never found later by searching for an output number.
HTML highlights are not clinical validation. JSON Schema Draft 2020-12 validation
checks names/types/enums/structure, not clinical truth. Counts are feasibility
coverage, not accuracy/precision/recall. Human references remain necessary.

## Later curated-note interface

No curated dataset is currently invented or selected. A future resolved dataset can
be exported **inside SERDA** as JSONL records containing:

```
sample_id, text, source_rows,
identity_approved, reconstruction_approved,
target_confirmed, confirmation_source
```

`source_rows` uses the same provenance objects as the frozen package:
`source_excel_row`, `text_start`, `text_end`, `original_text` (plus original file/sheet
when available). Offsets are Python Unicode string character offsets, not UTF-8 byte
positions. Identity/reconstruction/target flags must be confirmed, with an explicit
confirmation source. No patient linkage is inferred by this adapter.

```powershell
.\.venv\Scripts\python.exe -m serda_pipeline.ga_frozen_extract `
  --curated-jsonl 'Z:\ApprovedProject\curated\confirmed_notes.jsonl' `
  --output-dir 'Z:\ApprovedProject\ga-results\curated_ga_v1' `
  --config configs/serda_ga_erika.yaml
```

The same extraction engine is used; no corpus scan or target-note classifier is
needed. All text, evidence, mappings, clinical JSON and review pages remain in SERDA.
No real notes or outputs are part of this repository.

The exact 116-path support/type/enum inventory is tracked at
[`schemas/ga_schema_rule_support.json`](../schemas/ga_schema_rule_support.json).
The runtime support registry adds rule identifiers. “Explicit formats only” means
that supported patterns exist, not that all prose expressions of that field are
recognized. Metadata `note_id`/`note_date` remain outside extracted clinical values;
record order and source hashes provide document traceability without guessing IDs.
