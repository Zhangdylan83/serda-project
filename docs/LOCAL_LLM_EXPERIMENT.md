# Offline local CPU LLM GA experiment

This separate workflow compares Qwen3 proposals with the existing Erika Regex
extractor on identical frozen text, note IDs and schema fields. The old Regex engine,
EDA/audits and source packages are unchanged. Initial domains: Falls, ADL/IADL,
Cognition, Nutrition. No corpus discovery, Excel read, Prepare or note resampling.

## First run: synthetic text only

The user-reported SERDA model setup is Windows x64, four logical CPUs, 16 GiB RAM,
Qwen3-1.7B-Q4_K_M.gguf, llama.cpp b12125. The previously reported ~9.4 tokens/sec is
not a measurement of this new workflow. DGX tests use synthetic text and a mock
llama.cpp protocol process; actual Windows PowerShell and Qwen validation must occur
inside SERDA. No new model or weights are downloaded by any command below.

```powershell
cd "$env:USERPROFILE\Desktop\serda-project"
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
- 2500-character overlapping windows (overlap 400), maximum 128 generation requests;
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
Do not bypass it. Keep `execution_failure.json` (if startup failed),
`request_runtime.json`, `synthetic_smoke_checks.json` and local server log inside
SERDA for diagnosis. Terminal errors never print model responses or note excerpts.
If the fixed b12125 endpoints or flags differ in that installation, report the
non-PHI error type and command version so code/config can be corrected before PHI use.
The launcher has no automatic fallback to another API, host, model or unbudgeted prompt.

## Structured extraction and evidence

Each domain uses a small field-specific prompt and a strict JSON Schema response:
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
3. Check full-source local context and existing rule conflicts. Historical,
   not-performed, negated or uncertain proposals go to review.
4. Require quote-local deterministic rules to verify the **field/value relationship**
   before automatic acceptance. A number merely appearing in a quote is insufficient.
5. Preserve novel source-grounded phrasings as `review_required`; contradictions or
   fabricated quotes are rejected. Resolve conflicting accepted values across windows
   by withholding them, not choosing first/latest. Coupled components stay unresolved
   when one has a conflict.

This is intentionally a **rule-verified LLM proposal experiment**, not an independent
LLM clinical-validity judge. Automatic acceptance is limited by the verifier's rule
coverage and possible rule errors. A grounded but novel phrasing can be useful for
human review even when no value enters clinical JSON. Compare raw proposals as well
as accepted values; accepted-only agreement with Regex is partly by construction and
must not be reported as independent model accuracy. Exact quote verification cannot
prove clinical entailment or eliminate all hallucination/interpretation errors.

## Outputs and runtime

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
- `request_runtime.csv/json`: request wall time, actual prompt token count,
  completion usage and server timings where available. Output tokens/sec here is
  end-to-end, including template/tokenization/HTTP overhead, not raw eval speed.
- `run_manifest.json`: mode, code/config/schema/source hashes, model SHA-256, server
  executable hash, startup/total/Regex runtime, coverage and source approval flags.
- `schema_snapshot.json`, synthetic smoke checks, restricted local server log.

There are no real-note accuracy metrics without human references. Review compares
outputs, not ground truth. JSON structural validity is distinct from clinical truth.

## Later patient inference — separate authorization required

**Not authorized or run as part of this implementation.** After a successful real
Windows synthetic run, and only after separately authorizing patient inference:

```powershell
.\scripts\run_ga_local_llm.ps1 `
  -OutputRoot 'Z:\ApprovedRestrictedProject\ga-experiments' `
  -PackagePath "$env:USERPROFILE\Desktop\serda-results\ga_grouping_review_02" `
  -AuthorizePatientInference `
  -SyntheticPassRun 'Z:\ApprovedRestrictedProject\ga-experiments\<successful-synthetic-run>'
```

The package must be explicitly supplied. The gate is checked before candidate text
is opened: Windows runtime, explicit authorization and a matching successful
synthetic receipt for the current code/config are required. The model/server hashes
must also match the receipt before any patient inference. A new code/config/model
version requires another synthetic smoke run. This is an operational guard, not a
replacement for institutional permission.

The reused frozen-package reader verifies membership, hashes, original text/row
mapping, existing identity/reconstruction approvals and reviewer. No target note
confirmation is invented; existing target approval remains a source-package flag.
LLM extraction quality is separately audited. All outputs must remain on approved
restricted Z: storage, outside both the repo and source package. No automatic access
to `Z:\PHI` occurs anywhere in this workflow.

## Development verification

Synthetic unit tests cover strict domain types, exact source quotes/offsets, fabricated
quotes, value mismatch, negation/history/uncertainty, new phrasing held for review,
conflicts, incomplete domains, chunk coverage and context/request budgets, package
access gates, output immutability, fixed local endpoints and PowerShell contract.
A synthetic protocol executable exercises persistent startup, authenticated local
HTTP calls, proxy bypass, model/server fingerprints and process cleanup. That process
loads **no model**; its runtime is explicitly labelled mock/development and cannot
serve as a Windows patient-inference receipt. Actual PowerShell execution and Qwen
quality/speed remain to be measured in SERDA.
