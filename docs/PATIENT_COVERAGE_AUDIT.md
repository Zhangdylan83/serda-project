# Patient Coverage & Missingness Audit Summary

This standalone audit answers “Where are they missing? What tables are they missing
from?” using direct MRNs in all eight source exports. It leaves the existing eight-table
audit, cohort logic, GA workflows and predictor features unchanged. It does not
reconstruct notes, parse event dates, select a cohort or run clinical EDA.

## Run inside SERDA

Update code and use the existing CPU environment. Supply an **existing approved
restricted SERDA project directory** as OutputRoot (the path below is a placeholder):

```powershell
cd "$env:USERPROFILE\Desktop\serda-project"
git pull --ff-only origin main
.\scripts\run_patient_coverage.ps1 `
  -DataDir 'Z:\PHI' `
  -OutputRoot 'Z:\ApprovedRestrictedProject\serda-results'
```

The script uses `.venv\Scripts\python.exe`, tracked
`configs/serda_ga_erika.yaml`, and a unique `mrn_coverage_<timestamp>_<suffix>` output
folder. Optional `-PythonPath` points to an existing approved Python environment.
No YAML edits are required for the known export headers. If actual files have changed,
read the status report; do not force patient matching. This task streams all eight
Excel exports, including the large Notes workbook, once for identifier coverage.
Unlike the frozen-note extractor, it necessarily reads the source datasets.

Direct Python equivalent:

```powershell
.\.venv\Scripts\python.exe -m serda_pipeline.patient_coverage `
  --data-dir 'Z:\PHI' `
  --output-dir 'Z:\ApprovedRestrictedProject\serda-results\mrn_coverage_run01' `
  --config configs/serda_ga_erika.yaml
```

The output directory must not exist and must be outside the source directory and
code repository. Previous audits and source Excel files are never overwritten.

## Reference and calculations

Let S_D be the set of usable direct MRNs observed in dataset D. Demographics is an
equal source table; it is **not** treated as the study cohort.

- Observed union U = union of all eight S_D sets.
- Eight-table intersection = patients observed in every S_D.
- Per-table absent count = |U minus S_D|, i.e. observed reference MRNs absent from
  **this dataset**, not patients outside a research cohort.
- Coverage = 100 × |S_D| / |U|; an empty denominator is undefined, not 0%.
- Pairwise overlap(A,B) = |S_A intersect S_B|, symmetric; diagonal = |S_A|.
- Directional gap(A,B) = |S_A minus S_B|. This is generally NOT symmetric.

A failed/missing table, ambiguous MRN column, or nonempty table with no usable MRNs
is unavailable, **not an empty set**. The global eight-table union/intersection are
left unavailable unless all eight sets are usable. Other tables can still have
coverage computed against the explicitly labelled **partial observed union of
available tables**. Pairwise cells involving unavailable tables stay blank. An
actually empty table with a resolved MRN header is an observed empty set.

The per-table denominator excludes records whose patient cannot be identified.
Counts cannot recover the number of distinct people behind missing MRNs. Missing
patients and missing identifiers are therefore separate quantities. Both exact-set
equality and apparent completeness require interpretation of excluded rows.

## Outputs for Erika and the analyst

Only `aggregate/` contains candidate shareable aggregate reports:

| File | Purpose |
|---|---|
| `Patient_Coverage_Missingness_Summary.md` | Main eight-table summary, definitions, limitations and SQL-review questions |
| `patient_coverage_summary.csv` | Source row count, valid MRNs, coverage, reference MRNs absent from each table, identifier quality and PAT_ID mapping counts |
| `union_intersection_summary.csv` | Available-table union; full eight-table union/intersection only when available |
| `pairwise_overlap_matrix.csv` | 8×8 shared-MRN matrix |
| `directional_patient_gaps.csv` | All ordered A→B gaps: present in A, absent from B |
| `patient_presence_patterns.csv` | Aggregate combinations of presence/absence/unknown across tables |
| `cross_dataset_identifier_consistency.csv` | Global PAT_ID↔MRN multiplicity and possible case-format variation |
| `validated_roster_coverage.csv` | Only generated if an independently confirmed eligible roster is provided |

`restricted_SERDA_ONLY/` contains actual MRNs/PAT_IDs, the per-patient presence matrix,
per-dataset discrepancy lists, mapping pairs, and problematic identifier source rows.
Keep this folder inside approved restricted storage. No note text or other clinical
fields are copied into reports. Aggregate files have no patient identifiers; any
external sharing still follows institutional disclosure requirements, including
small-cell review. The program never emails or uploads reports.

`execution_report.json` records completed/failed scans, unavailable linkage, code and
configuration hashes, source filename/sheet/header/size/modification-time metadata,
and optional roster hash. It does not claim immutable full-workbook snapshots.
An incomplete run exits with code 2 but preserves usable results and clearly labels
the incomplete denominator.

## Identifier and row conventions

Reuse the existing MRN audit's streaming workbook reader, schema discovery and
identifier normalization. Prefer PAT_MRN_ID; discover other aliases per dataset or
use explicit configured mappings. No PAT_ID/name/encounter substitution. Preserve
string leading zeros, alphanumerics and case; trim outer whitespace only. Numeric
Excel MRNs are withheld because leading zeros may already have been lost. Conflicting
nonempty alternative MRN columns cause the row to be withheld; a blank primary is
not filled from another column silently. Partial/nontext alternatives are counted.
Case-variant groups and PAT_ID mapping multiplicity are reported, never forcibly
merged. A PAT_ID with several MRNs is a review flag, not proof that one MRN is correct.

Rows include internal blank rows but exclude trailing blank rows, matching the
previous MRN scan convention. For .xlsx/.xlsm the reader streams rows; it does not
load the full Notes text table into a dataframe. It retains identifier sets/mappings,
not note text. No exact-row duplicate analysis or variable-level missingness is
recomputed here; those remain in the original audit outputs.

## Optional independent eligible roster

Do not manufacture this from Demographics or the observed union. Only when a roster
has been independently confirmed, supply a UTF-8 CSV with these headers:

```
mrn,eligible,confirmation_status,source,reviewer
```

MRNs must remain strings; eligibility is `yes`/`no`; every row must be `confirmed`
with nonempty source and reviewer. Missing/duplicate IDs or unconfirmed rows fail
before scanning. This is explicit provenance input, not clinical verification by
software. Add the parameter:

```powershell
.\scripts\run_patient_coverage.ps1 `
  -OutputRoot 'Z:\ApprovedRestrictedProject\serda-results' `
  -RosterPath 'Z:\ApprovedRestrictedProject\confirmed_socare_roster.csv'
```

The additional table reports roster patients present/absent in each dataset, coverage
against eligible roster patients, and source MRNs outside the roster. The observed
union report remains separate; neither changes study eligibility or existing cohorts.

## What this can and cannot conclude

Notes coverage = patients with usable direct MRNs on source fragments. It does not
prove note-level identity, complete reconstruction, anchor alignment, geriatrician
assessment or a one-note-per-patient mapping. Medication coverage requires only MRN
linkage; unresolved medication names/date columns do not block it.

No-event sparsity and extraction defects cannot be distinguished by a set difference
alone. Identifier-quality problems are observed data-quality evidence; an absence
from a table is not by itself evidence of an SQL error. Ask the original analyst to
compare intended populations, encounter/event requirements, date windows, sites,
MRN sources and joins that can drop patients. Check whether equal population coverage
was actually expected for each export.

Keep variable-level missingness (e.g. education or medication attributes) in the
separate existing audit. Historical October PAT_ID figures are not reused as latest
MRN counts. Actual eight-table numbers must be generated inside SERDA; software tests
use tiny synthetic identifier fixtures only, not a real-data evaluation.
