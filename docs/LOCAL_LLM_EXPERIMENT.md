# Offline local CPU LLM GA experiment

This separate workflow compares Qwen3 proposals with the existing Erika Regex
extractor on identical frozen text, note IDs and schema fields. The old Regex engine,
EDA/audits and source packages are unchanged. The default now requests all ten clinical domains and every clinical leaf in Erika’s
schema: performance status, physical function (including ADL/IADL and MOS), physical
performance, falls, cognition, psychological, comorbidity, nutrition, polypharmacy
and social support. No corpus discovery, Excel read, Prepare or note resampling.

## Optional diagnostic: synthetic text only

The user-reported SERDA model setup is Windows x64, four logical CPUs, 16 GiB RAM,
Qwen3-1.7B-Q4_K_M.gguf, llama.cpp b12125. The previously reported ~9.4 tokens/sec is
not a measurement of this new workflow. DGX tests use synthetic text and a mock
llama.cpp protocol process; actual Windows PowerShell and Qwen validation must occur
inside SERDA. No new model or weights are downloaded by any command below.

```powershell
cd "Z:\serda-project"
git pull --ff-only origin main
.\scripts\run_ga_local_llm.ps1 -OutputRoot 'Z:\ApprovedRestrictedProject\ga-experiments'
```

Replace OutputRoot with an **existing approved restricted project directory on Z:**.
It is deliberately required; no approved project storage is guessed. The launcher
rejects Desktop, other drives and UNC output paths. It uses repo `.venv` by default;
`-PythonPath` can select the existing approved environment. No new Python dependency
is added beyond this repository's requirements. No YAML edits are needed.

Tracked `configs/serda_ga_llm.yaml` sets:

- `Z:\LLM\llama-cpp\b12125\llama-server.exe`
- `Z:\serda-models\Qwen3-1.7B-Q4_K_M.gguf`
- literal `127.0.0.1:8097`, random per-run API key, no attachment to existing servers;
- CPU only (`--n-gpu-layers 0`), four threads, one parallel slot, batch 128;
- context 4096, maximum generated tokens 768, deterministic temperature 0/seed 42;
- Qwen thinking disabled in server template kwargs and each request;
- 2500-character overlapping windows (overlap 400), maximum 512 generation requests;
- maximum eight explicitly selected frozen notes, no automatic sample truncation.

One managed llama-server process serves the whole run and is stopped on exit/error.
The executable's version must identify build 12125. Model file existence is checked;
no HF/model download flags are used. Logs stay in the restricted result directory;
`--log-disable` suppresses normal server logging. Offline/telemetry environment
switches are set. No web UI, slots API, model tools, tools/functions in prompts,
external inference or external URLs are used. HTTP proxies and redirects are disabled.
Only `/health`, `/apply-template`, `/tokenize` and `/v1/chat/completions` are callable,
all at literal 127.0.0.1. This does not make third-party executable behavior auditable;
use the already approved local llama.cpp build.

The script creates `ga_local_llm_synthetic_<timestamp>_<unique>` below OutputRoot.
It uses **only built-in synthetic text**, never searches for a patient package.
`synthetic_smoke_checks.json` must show `passed: true` and the process must exit 0.
Checks include explicit MoCA numerator/denominator, falls count/period, an ADL item,
and weight-loss amount/unit/period. These are smoke checks, not clinical accuracy.

A JSON parse failure, truncation, unsupported server option/API, thinking/tool output,
failed field verification or missing expected synthetic values fails the smoke run.
A diagnostic failure is not a successful smoke receipt. Keep `execution_failure.json` (if startup failed),
`request_runtime.json`, `synthetic_smoke_checks.json` and local server log inside
SERDA for diagnosis. Terminal errors never print model responses or note excerpts.
If the fixed b12125 endpoints or flags differ in that installation, report the
non-PHI error type and command version so code/config can be corrected before PHI use.
The launcher has no automatic fallback to another API, host, model or unbudgeted prompt.

## Structured extraction and evidence

Each domain uses small field-specific prompts, with at most eight fields per batch
by default. Score/count/weight components stay together. The ten domains currently
produce 19 prompt batches per full-text window (rather than the former four-domain
workflow); expect more CPU time. Context and request-budget limits remain enforced.

Each batch uses a small field-specific prompt and a strict JSON Schema response:
`findings` contains field path, typed value, exact source quote and explicit/uncertain
status. Allowed paths/types/enums derive from Erika's actual schema. Cognitive
clinician judgments cannot be inferred from MoCA; unspecified denominators, labels
and missing clinical information cannot be filled. Notes are untrusted prompt data.

Every window is token-budgeted using the server's own chat template and tokenizer.
Windows shrink if needed, never silently truncate. Overlapping windows cover the
entire supplied text separately for each requested domain. This is not a target-note
classifier or domain-keyword prefilter. Very distant context can still be lost; review
is necessary. Exceeding the request budget or failing any window makes that domain
incomplete and withholds **all** accepted values for the affected note/domain, while
other successful domains remain reviewable. No automatic retry/repair pass is run.

Verification has distinct stages:

1. Validate model JSON and each field's type/enum against the domain schema.
2. Locate the quoted substring exactly and uniquely in that window; convert its
   position into unchanged full-note character offsets and original Excel rows.
3. Keep model-declared uncertainty for review and conflicting model values unresolved.
4. Run Regex separately on exactly the same frozen notes. Never pass Regex values,
   context rules or disagreements into LLM inference or acceptance.

This is an **independent LLM versus Regex experiment**. `accepted` is retained as a
file-format status meaning JSON and unique verbatim-quote checks passed; it does NOT
mean clinical correctness. A model can quote “MoCA 15/30” but predict 29, or misread
history: these errors remain LLM predictions for human adjudication, not silently
corrected or removed by Regex. Missing/fabricated quotes fail source checks; all raw
responses and rejected candidates remain available. Report these failures and
abstentions when evaluating the complete sample grid, not just accepted rows.

Read notes first and fill `reference_annotations.csv` independently of either method:
`reference_status` = documented / not_documented / unclear / not_reviewed;
`reference_value` contains a JSON scalar for documented fields. Record supporting
text and reviewer. Use the SAME adjudicated reference for both methods; a machine's
not_found is not clinically not_documented. Compare per-field correct values,
misses, wrong values, abstentions and failures, excluding unreviewed/unclear cells
from correctness denominators but reporting their counts. No accuracy evaluator or
clinical accuracy claim is supplied by this experiment. Agreement is not accuracy.
Metadata note_id/note_date are not clinical extraction performance endpoints.
The eight development samples cannot establish population-level accuracy.

Old rule-gated experiment outputs remain frozen and are not independent LLM
benchmarks. Explicitly authorize a NEW package run; do not overwrite old results.
Synthetic smoke is optional, including after updates.

## Outputs and runtime

- `llm_proposals_for_review.jsonl`: independent schema-valid LLM proposals whose
  quotes were located in source, including novel phrasings that Regex cannot verify.
  These are **human-review candidates**, not clinical truth; consult evidence statuses.
  Fabricated quotes, conflicting values and incomplete domains
  do not enter this file.
- `regex_ga_features.jsonl` and `regex_evidence.jsonl`: independent unchanged Regex outputs with sample IDs.
- `reference_annotations.csv`: blank shared human-reference grid, never seeded from predictions.
- `llm_ga_features.jsonl`: sparse accepted objects conforming to Erika's schema;
  unresolved fields omitted, not converted to clinical nulls.
- `llm_evidence.jsonl`: accepted/review/rejected proposals, quotes, offsets and Excel
  rows; stable sample/internal-note IDs.
- `llm_regex_comparison.csv`: one row per identical note/field, LLM proposals,
  accepted value/status and freshly recomputed existing Regex value/status.
  Existing saved Regex results remain untouched; code hashes identify the comparison.
- `raw_local_responses_SERDA_ONLY.jsonl`: raw responses, including unsuccessful
  parse/truncation outputs. Sensitive, never share or commit.
- `review.html`: escaped offline full-note reference-first review and side-by-side
  table. No external scripts/assets/network requests.
- `field_coverage.csv`: every requested clinical field plus two metadata fields,
  with accepted/review/missing/incomplete/source-metadata counts.
- `request_runtime.csv/json`: request wall time, actual prompt token count,
  completion usage and server timings where available. Output tokens/sec here is
  end-to-end, including template/tokenization/HTTP overhead, not raw eval speed.
- `run_manifest.json`: mode, code/config/schema/source hashes, model SHA-256, server
  executable hash, startup/total/Regex runtime, coverage and source approval flags.
- `schema_snapshot.json`, synthetic smoke checks, restricted local server log.

There are no real-note accuracy metrics without human references. Review compares
outputs, not ground truth. JSON structural validity is distinct from clinical truth.

## Direct inference on frozen S001–S008

An explicitly authorized Windows SERDA package run does **not** require a separate
synthetic smoke run or `-SyntheticPassRun`. Use the existing shared-drive checkout:

```powershell
cd 'Z:\serda-project'
git pull --ff-only origin main
$OutputRoot = Read-Host 'Existing approved restricted Z: output directory (outside repo and package)'
.\scripts\run_ga_local_llm.ps1 `
  -OutputRoot $OutputRoot `
  -PackagePath "$env:USERPROFILE\Desktop\serda-results\ga_grouping_review_02" `
  -AuthorizePatientInference
```

The package path is the previously reported frozen package location; if moved,
supply its actual path. Membership is read from the frozen manifest, never guessed
or resampled. An existing `.venv` under `Z:\serda-project` is used automatically;
otherwise pass `-PythonPath` pointing to the existing approved Python executable.
The launcher creates a unique `ga_local_llm_package_<timestamp>_<unique>` directory
under the existing approved Z: OutputRoot. No project-specific output path is assumed.

Authorization and Windows checks occur before reading note text. The model/server
are still checked locally and their hashes recorded, alongside code/config hashes.
`run_manifest.json` records `synthetic_receipt_status=not_supplied_optional` for a
direct run; it does not claim a synthetic test was performed.

Optionally supply `-SyntheticPassRun '<successful Windows synthetic run directory>'`.
If supplied, it must pass the existing runtime/code/config/model/server matching
checks; stale or failed receipts are rejected, not silently ignored. Without
PackagePath the launcher still runs built-in synthetic diagnostics only.

The reused frozen-package reader verifies membership, hashes, original text/row
mapping, existing identity/reconstruction approvals and reviewer. No target note
confirmation is invented; existing target approval remains a source-package flag.
LLM extraction quality is separately audited. All outputs must remain on approved
restricted Z: storage, outside both the repo and source package. No automatic access
to `Z:\PHI` occurs anywhere in this workflow.

## Development verification

Synthetic unit tests cover strict domain types, exact source quotes/offsets, fabricated
quotes, preservation of model errors for adjudication, model uncertainty, novel phrasing,
conflicts, incomplete domains, chunk coverage and context/request budgets, package
access gates, output immutability, fixed local endpoints and PowerShell contract.
A synthetic protocol executable exercises persistent startup, authenticated local
HTTP calls, proxy bypass, model/server fingerprints and process cleanup. That process
loads **no model**; its runtime is explicitly labelled mock/development and cannot
serve as a Windows patient-inference receipt. Actual PowerShell execution and Qwen
quality/speed remain to be measured in SERDA.

## Full-schema coverage and metadata

The full tracked configuration covers all **114 clinical leaves**. Tests check that
every clinical path appears exactly once in the field-batch partition. The audit
and comparison grid additionally contain `note_id` and `note_date`, for 116 rows per
note. These two fields are never guessed by the LLM: a document ID is copied only
from unanimous nonempty `raw_rows.note_id`; a date requires a valid frozen ISO date
consistent with all source-row dates. Missing metadata stays unavailable. NOTE_CSN,
MRN and internal sample hashes are never substituted for NOTE_ID. Source metadata
has a separate provenance/status, not an LLM extraction claim.

The synthetic smoke test now includes at least one explicit value in each of the
ten clinical domains. Passing it still does not prove full field accuracy or real-note
performance. The old four-domain receipt no longer matches this code/configuration:
rerun diagnostics if you want to supply a matching optional receipt.
The same launcher command is used, without YAML edits. Full schema means every
clinical field is offered to the model; it does not mean every field should be filled.
Unrecorded, unresolved and unsupported expressions must not be invented.
