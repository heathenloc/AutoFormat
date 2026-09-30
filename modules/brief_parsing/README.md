# Brief Parser

Brief Parser converts untrusted text, DOCX, and text-based PDF briefs into an
evidence-backed Canonical Requirement IR and task-specific Execution Briefs.
It runs independently and exposes a host-neutral Parse Bundle for future
integration with Creator's Voice or other software.

## Current implementation status

Phases 0 through 6 are implemented. Phase 7 remains intentionally deferred
until a real host contract exists. Phase 8 evaluation and hardening is in
progress. The repository now provides:

- strict Pydantic v2 public contract models;
- versioned JSON Schema snapshots;
- validated environment configuration and safe error responses;
- a provider-neutral model port and deterministic fake provider;
- operational parse, validation, rendering, server, and version CLI commands;
- contract, round-trip, configuration, provider, CLI, and API tests;
- pre-model file security checks for UTF-8 TXT, DOCX, and PDF;
- request-level limits for at most 10 Sources, aggregate PDF pages, and
  aggregate extracted characters before any Provider call;
- DOCX ZIP-bomb, path traversal, macro, encryption, and unsafe XML rejection;
- encrypted, invalid, page-limit, and missing-text-layer PDF rejection;
- ordered text, heading, list, table-cell, header, footer, footnote, and page-break blocks;
- Unicode NFC and whitespace normalization with raw code-point mappings;
- extraction quality metrics and non-silent warnings.
- stable Clause Segmentation, including strong sentence boundaries in short
  Chinese paragraphs, with one primary chunk per clause;
- exact raw-text Evidence Index construction and hash validation;
- deterministic Chinese/English number, range, date, unit, operator, and modality signals;
- one-entry-per-clause Coverage Ledgers;
- deterministic `complete`, `usable_with_warnings`, and `incomplete` Readiness policy.
- strict internal Extractor, Auditor, and Resolver candidate schemas;
- immutable `extractor/v2`, `auditor/v1`, and `resolver/v1` prompts;
- provider-neutral model and prompt repository ports;
- a deterministic Fake Provider with refusal and incomplete outcomes;
- an OpenAI Responses API adapter using Pydantic Structured Outputs;
- a Qwen OpenAI-compatible Chat Completions adapter pinned by default to
  `qwen3.7-flash-2026-07-15`;
- bounded network/429/5xx and incomplete-output retries;
- post-provider Clause, Evidence, Candidate, and internal Schema validation.
- invalid model schemas, evidence references, and stage decisions fail closed into
  an inspectable `incomplete` result after bounded retries; accepted IR never
  contains rejected candidates, and available request IDs/token usage are kept;
- end-to-end Stage orchestration from secured source through Requirement IR;
- deterministic cross-chunk Candidate namespacing and stable artifact IDs;
- explicit and semantic-key conflict detection with evidence-gated resolution;
- deterministic IR assembly, numeric/modality verification, and audit-gap handling;
- request fingerprinting, Parse Manifest, provider usage, latency, and stage metrics;
- end-to-end synthetic acceptance tests for complete, conflict, refusal, and replay paths.
- safe declarative YAML Domain Pack loading with duplicate-key, alias, and registry checks;
- canonical compiled JSON for `generic_requirements@1.0.0` and
  `advertising_brief@1.0.0`, plus an academic schema example;
- trusted duration/date validators and `write_ad_script` Context Compiler;
- task-scoped Execution Brief projection with blocker and warning propagation;
- document meta-instruction filtering at the downstream context boundary;
- deterministic Markdown result rendering and combined output compilation;
- versioned, host-neutral Parse Bundle and diagnostics contracts;
- atomic five-artifact directory persistence with replay/conflict checks;
- Standalone FastAPI asynchronous Job endpoints and OpenAPI snapshot;
- SQLite-only standalone Job metadata with idempotency and restart recovery;
- owned upload/artifact lifecycle deletion and retention cleanup;
- bounded in-process concurrency, cancellation, and execution timeout;
- one shared overall Job timeout policy for CLI and Standalone API execution;
- a Provider-level concurrency semaphore shared across concurrent parse jobs;
- a configurable per-job Token Budget that stops later model stages and returns
  explicit `incomplete` diagnostics when exceeded;
- a host-neutral Observation Port and allowlisted JSON operational events that
  cannot accept source text, filenames, prompts, or complete Provider responses;
- optional OTLP/HTTP traces and metrics through a replaceable OpenTelemetry
  Collector, while retaining fail-open allowlisted JSON logs;
- per-source Linux Parser processes with wall-clock, CPU, address-space,
  file-size, and open-file hard limits;
- a non-root multi-stage OCI image plus a read-only Docker Compose baseline
  with tmpfs, persistent data volume, CPU, memory, PID, and privilege limits;
- a commit-SHA-pinned GitHub Actions workflow for the complete offline gate,
  Linux isolation tests, image build, and read-only container smoke test;
- an offline wheel build check for required runtime assets, console entry points,
  version metadata, and forbidden runtime or secret-bearing files;
- a versioned 100-case synthetic Golden Dataset with the required 60/20/20 split;
- deterministic BP-TDR-009 quality metrics and machine-readable release gates;
- explicit provider pricing input and token-based cost reports;
- prompt-injection isolation, 429/timeout/incomplete/resolver failure tests;
- a dependency-free bounded-concurrency load probe with a 30-second p95 gate.

Concrete Creator's Voice integration is intentionally deferred because its
other runtime modules do not exist yet. Future hosts integrate through
`BriefParserService`, versioned contracts, or the Parse Bundle rather than
through standalone SQLite internals. The same boundary is available to other
software without Creator's Voice domain types.

## Document ingestion API

```python
from pathlib import Path

from brief_parser.adapters import DocumentIngestor, FileSecurityValidator

secured = FileSecurityValidator().secure_file(
    Path("synthetic.docx"),
    source_id="src_001",
    client_source_id="brand_brief",
    language_hints=("zh-CN",),
)
document = DocumentIngestor().ingest(secured)
```

Security validation must run before ingestion. Callers should not construct a
`SecuredSource` from untrusted bytes themselves.

## Deterministic foundation API

```python
from brief_parser.adapters import ClauseSegmenter, EvidenceIndexBuilder
from brief_parser.validators import DeterministicRuleAnalyzer

segmentation = ClauseSegmenter().segment(document)
evidence_index = EvidenceIndexBuilder().build(document, segmentation)
rule_analysis = DeterministicRuleAnalyzer().analyze(document, segmentation)
```

Clause and rule spans use Unicode code-point offsets and map back to exact
`raw_text`. Coverage classifications are supplied explicitly to
`CoverageLedgerBuilder`; missing classifications remain `unclassified` rather
than being guessed. `ReadinessPolicy` emits stable reason codes for every
warning or blocker.

## Model providers

The MVP online default is the fixed Alibaba Cloud Model Studio snapshot
`qwen3.7-flash-2026-07-15` for Extractor, Coverage Auditor, and Resolver.
Configure it without writing credentials to a file:

```powershell
$env:BRIEF_PARSER_PROVIDER = "qwen"
$env:DASHSCOPE_API_KEY = "<load-from-your-secret-manager>"
$env:DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
uv run python scripts/smoke_qwen.py
```

The Base URL must match the region in which the API Key was created. The
default is the China (Beijing) public compatible endpoint. For a
workspace-dedicated endpoint, set the exact HTTPS `compatible-mode/v1` URL
provided by Model Studio. The adapter only accepts the documented DashScope
public hosts or an Alibaba Cloud `*.maas.aliyuncs.com` endpoint, preventing a
misconfigured Base URL from forwarding the API Key to an unrelated host. Qwen
thinking is disabled by default for predictable latency and structured
extraction; enable it explicitly with
`BRIEF_PARSER_QWEN_ENABLE_THINKING=true` and re-run the Golden Dataset before
adopting that configuration.

The Qwen adapter uses Chat Completions `parse` with the internal Pydantic output
type, `temperature=0`, no tools, and no file uploads. Extractor v2 receives
trusted Domain Pack category IDs, while source content remains in a separate
untrusted message. Auditor evidence IDs come from the validated Clause map.
An unextracted quantitative duration produces an explicit warning rather than
an incorrect `complete` result. The adapter normalizes Qwen token usage, refusal,
length truncation, rate-limit, transient failure, and schema-invalid outcomes
into the provider-neutral result contract.

The OpenAI adapter uses the Responses API with Pydantic Structured Outputs,
`store=false`, no tools, and no local file uploads. It sends source clauses only
inside a clearly marked user-data envelope; source text is never appended to
the system prompt. It remains available as an alternative Adapter but is no
longer the MVP default. API keys and Qwen workspace Base URLs are excluded from
configuration serialization and representations.

Provider and pipeline tests use injected clients and synthetic content. They do
not make live API calls or require a real API key. Live-provider validation is
intentionally not simulated. A real Beijing-region Qwen smoke and one complete
synthetic Chinese brief parse succeeded on 2026-09-23. The first 100-case
real-provider Golden run produced 78 valid artifacts and did not pass the
Phase 8 release gate; see the evaluation status in the Technical Design.
Fail-closed behavior, Domain Pack risk floors, and short-paragraph sentence
segmentation were verified offline after that run. The 78/100 result belongs
to the earlier Pipeline version; it has not been re-measured against Qwen and
does not imply the release gate now passes.

## Domain Packs and output compilation

YAML packs are loaded with a safe loader and may reference only registered
Validator and Compiler IDs. Checked-in JSON snapshots are generated from the
reviewed YAML sources:

```powershell
uv run python scripts/compile_domain_packs.py --check
```

For known categories, the reviewed Domain Pack `risk` is a deterministic
minimum Requirement priority. A model may raise but cannot lower it. This
normalization happens before conflict severity and IR assembly; the policy is
included in the request fingerprint. Current Pipeline version: `1.2.0`.

`OutputCompiler` accepts a validated Requirement IR, a matching Domain Pack,
and requested task types. It returns the final domain-validated IR, one
Execution Brief per task, and deterministic `result.md` content.
`ArtifactDirectoryStore` persists the complete set atomically.

## Standalone usage

Parse a file into the atomic artifact directory:

```powershell
brief-parser parse --input ".\\brief.pdf" --domain advertising_brief --task write_ad_script --output ".\\output\\brief-001"
```

The directory contains `manifest.json`, `requirement-ir.json`, one
`execution-brief.<task>.json` per task, `result.md`, and
`diagnostics.json`. Validate it with
`brief-parser validate-result .\\output\\brief-001`.

Start the local asynchronous API:

```powershell
brief-parser serve --host 127.0.0.1 --port 8000
```

Submit multipart form data to `POST /v1/parse-jobs`: the `request` field is
JSON containing `domain`, `task_types`, and optional `domain_version` /
`locale`; repeat the `sources` file field for each source. Poll the returned
status URL, then retrieve the stable Parse Bundle from the result URL.

## Evaluation and release gate

The checked-in dataset at `evals/golden/v1/dataset.json` expands to 100
synthetic cases: 60 advertising briefs, 20 edge/adversarial briefs, and 20
general requirement documents. Every expanded case contains a Clause Ledger,
Facts, Requirements, Evidence, Conflicts, Unresolved items, and expected
Readiness annotations.

During prompt or validator triage, preview a small named subset without loading
the Provider, then run only those cases into a separate prediction file:

```powershell
brief-parser-golden-run --case-id ad-duration-01 --case-id edge-cta-conflict-01 --plan
brief-parser-golden-run --case-id ad-duration-01 --case-id edge-cta-conflict-01 --output .\evals\runs\targeted.jsonl
```

For release evaluation, explicitly run all cases with the configured real
Provider, then evaluate the resulting full prediction file:

```powershell
brief-parser-golden-run --all --output .\evals\runs\predictions.jsonl
brief-parser-eval --dataset .\evals\golden\v1\dataset.json --predictions .\evals\runs\predictions.jsonl --output .\evals\reports\release.json
```

The runner requires either repeated `--case-id` options or explicit `--all`;
`--plan` makes zero Provider calls and does not require a key. A targeted
prediction file is for diagnosis, not release evidence. The runner refuses the
Fake Provider by default. `--allow-fake` exists only
for plumbing tests and produces a non-release result. The evaluator exits with
code 0 only when every BP-TDR-009 gate passes and there are no missing,
unexpected, or invalid cases.

Provider prices are deliberately not hard-coded. Supply a reviewed,
date/version-labelled JSON file with this shape when a cost report is needed:

```json
{
  "pricing_version": "replace-with-reviewed-pricebook-version",
  "currency": "USD",
  "models": {
    "configured-model-id": {
      "input_usd_per_million_tokens": 1.23,
      "output_usd_per_million_tokens": 4.56
    }
  }
}
```

Run a repeatable local load baseline against the same host-neutral service:

```powershell
brief-parser-load --input .\synthetic-brief.txt --requests 20 --concurrency 2 --output .\evals\reports\load.json
```

The local probe is an implementation baseline, not a production capacity
claim. Final release evidence still requires the approved Provider and target
deployment environment.

Provider concurrency and cost containment are configurable with
`BRIEF_PARSER_PROVIDER_MAX_CONCURRENCY` (default `4`) and
`BRIEF_PARSER_JOB_TOKEN_BUDGET` (default `100000`). The budget counts actual
input plus output tokens reported by the Provider. Crossing it never triggers
an automatic budget increase; remaining Provider stages are skipped and the
result includes `job_token_budget_exceeded`.

Request-level resource limits use `BRIEF_PARSER_MAX_SOURCES` (maximum `10`),
`BRIEF_PARSER_MAX_PAGES` (aggregate PDF pages, maximum `100`), and
`BRIEF_PARSER_MAX_EXTRACTED_CHARS`. These checks are shared by the CLI, the
Standalone API, and future host-neutral service callers and complete before
any Provider invocation.

## Runtime isolation and telemetry

The supported production isolation target is Linux amd64 in an OCI container.
Each secured Source is parsed in a fresh spawn-process. Defaults are 60 seconds
wall time, 60 seconds CPU time, 1 GiB address space, 256 MiB writable file size,
and 128 open files. `BRIEF_PARSER_PARSER_ISOLATION_MODE=process` fails fast on
non-Linux systems. The default `auto` mode falls back to in-process parsing only
for local development and tests; production configuration cannot select
`in_process`.

Start the hardened local stack when Docker is available:

```powershell
docker compose up --build
```

The app listens on `127.0.0.1:8000`. Its root filesystem is read-only and
runtime state is written only to the mounted `/var/lib/brief-parser` volume;
`/tmp` is a bounded tmpfs. The bundled OpenTelemetry Collector receives
OTLP/HTTP and exposes Prometheus metrics on `127.0.0.1:9464`. It uses a debug
trace exporter and has no persistent telemetry storage.

Outside Compose, leave `OTEL_EXPORTER_OTLP_ENDPOINT` unset to disable OTLP
export while retaining JSON operational logs, or point it at an approved
Collector base endpoint such as `http://collector:4318`. The application
appends `/v1/traces` and `/v1/metrics`. Source text, filenames, prompts, and
complete Provider responses are not accepted by the observation contract.

The checked-in GitHub Actions workflow uses Provider-free tests only. It is
inactive until this repository is pushed to a GitHub remote. The final
production container platform, region, data residency, storage class, and
Collector exporters remain deployment decisions.

## Development

Python 3.12 and uv are required.

```powershell
uv sync --frozen
uv run pytest
uv run ruff check .
uv run mypy
uv run python scripts/export_schemas.py --check
uv run python scripts/export_openapi.py --check
uv run python scripts/compile_domain_packs.py --check
uv run brief-parser version
uv run brief-parser-golden-run --help
uv run brief-parser-eval --help
uv run brief-parser-load --help
```

Run the same complete, Provider-free local gate with one command:

```powershell
uv run python scripts/verify.py
```

The default Fake Provider safely exercises the complete path but returns
`incomplete` rather than inventing semantic results. Configure an approved
real Provider for meaningful extraction.

## Contract source of truth

Pydantic models under `src/brief_parser/domain/` and
`src/brief_parser/evaluation/` are the executable sources of truth. Files
under `contracts/` are generated snapshots and must be updated in the same
change as their models:

```powershell
uv run python scripts/export_schemas.py
```

The accepted implementation baseline is
`Brief_Parsing_Technical_Design.md`. The earlier
`Brief_Parsing_Intro.md` remains supporting context.

## Data safety

Do not commit `.env`, `var/`, `output/`, generated `evals/runs/` or
`evals/reports/`, real customer briefs, API keys, model prompts containing
private content, or provider responses. Tests and the checked-in Golden
Dataset use synthetic data only.
