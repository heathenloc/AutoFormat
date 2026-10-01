# EasyFormat API package

The first module is a replaceable preview boundary in `easyformat.preview`.
Install the copied `modules/brief_parsing` package into the project virtual
environment first, then install this package in editable mode. Both installs
remain inside `E:\EasyFormat\.venv` during local development.

`LibreOfficeRenderer` requires an explicit `soffice.com` path and its expected
SHA-256. It uses the copied parser's DOCX security validator, rejects embedded
objects, external relationships and content-import fields, starts LibreOffice
with a separate profile per conversion, and bounds processing time and PDF
size/page count. The renderer publishes a PDF only after checking that it opens,
contains extractable text, and the source DOCX hash is unchanged.

`easyformat.selection.verify_pdf_selection` checks a saved preview's DOCX and
PDF hashes, page count, and a proposed selection's exact page text. It rejects
missing or repeated page text. The caller loads both artifact metadata and the
version DOCX path from trusted storage, then passes a trusted preview binding
to the C# DOCX locator. PDF.js text-layer offsets remain unverified hints.

For this development machine, the verified console launcher is
`E:\LibreOffice\26.8.0-admin\program\soffice.com` with SHA-256
`95016b59e08da1e6cbb02fc8f027593c076bf47df795092578afdd995306ac85`.
Pass these as `EASYFORMAT_TEST_SOFFICE` and
`EASYFORMAT_TEST_SOFFICE_SHA256` to run the integration test.

```powershell
$env:EASYFORMAT_TEST_SOFFICE = 'E:\LibreOffice\26.8.0-admin\program\soffice.com'
$env:EASYFORMAT_TEST_SOFFICE_SHA256 = '95016b59e08da1e6cbb02fc8f027593c076bf47df795092578afdd995306ac85'
.\.venv\Scripts\python.exe -m pytest -q tests\preview
```

The school template in `TestDocuments/` contains an embedded object and is
currently rejected by the renderer preflight. It was not handed to LibreOffice.
This conservative policy can be revisited only after there is an isolated
rendering environment and a safe fixture for that content type.

## Immutable local version storage

`easyformat.version_store.VersionStore` keeps task metadata in SQLite and copies
each version into its own directory. `create_task` checks and stores the original
as V0. `publish_version` takes a selected parent, its expected DOCX hash, an
idempotency request ID, a candidate DOCX, JSON and Markdown reports, a PDF
preview artifact, and version references. It stages copies, checks the DOCX,
report identity, PDF text and hashes, then moves the complete directory into
place before committing the version row. The first V1 may have the same DOCX
hash as V0; later unchanged candidates are rejected as `no_document_change`.
Selecting an older version changes only the task's working pointer; the next
successful publication creates a child without deleting existing descendants.

`record_decision` appends an answer, skip, defer or consultation event without
creating a DOCX version. Repeated request IDs return the prior event only when
the payload matches. On startup, the store removes unpublished staging and
orphan directories and marks rows with missing or modified artifacts as
`validation_failed`. Artifact reads recheck hashes. The store is a persistence
primitive; it does not authorize API downloads or implement task UI.
`easyformat.reports` builds `version-report/1.0` facts and
escapes them into deterministic Markdown. Before publication, the store checks
the full report Schema, its summary and evidence links, parent history,
version/preview references, and exact Markdown correspondence. It still relies
on upstream validators for the truth of individual formatting claims and
verification references. The current `easyformat.workflow` connects confirmed
`brief_explicit` paragraph-alignment rules. The rule's original Brief
wording and evidence are report facts; the typed property, value, scope and
target alone drive the editor. Its `DotnetEditor` runs an explicitly located,
hash-checked, previously built DLL without a shell or dependency restore. The
workflow checks the editor's JSON result and output hash, creates a selectable
preview, builds a report tied to the output DOCX, and publishes the version.
Already-satisfied operations add no version; repeated request IDs return the
same published version only for matching rule input. Template observations,
free-text feedback and other formatting properties are not accepted by this
narrow entry point. A global body rule can now be reviewed, have every
paragraph classified by a recorded user decision, and become an `edit-plan/1.0`
with explicit target IDs, previous direct alignments and a review hash. The
batch workflow re-indexes the parent, re-creates the plan, checks the recorded
decision, and publishes one version only after all target results agree.

`easyformat.target_planning.DotnetTargetIndexer` runs the pinned C# `inspect`
command against a version-bound DOCX and validates its target index. The
`build_body_alignment_review` combines that index with the typed academic rule
set. Its `target-review-plan/1.0` lists every paragraph's candidate role and
review disposition but has an empty executable operation list. A `Normal` style
paragraph is not proof of the paper's body scope. `confirm_body_scope` requires
an include or exclude decision for every paragraph and records it separately
from DOCX versions. `build_confirmed_body_alignment_plan` then admits only
nonempty, safe body targets. The user-facing review and confirmation API is
available for tasks whose trusted academic rule snapshot has been registered.

## Local HTTP boundary

`easyformat.rule_snapshots.RuleSnapshotStore` accepts a validated
`AcademicFormatRuleSet` only through its internal `register` method. It saves
one immutable, hash-checked snapshot for each task. There is no HTTP route for
uploading or replacing executable rules.

When the host injects `AcademicTaskIntake`, `POST /api/tasks` accepts one school
Brief (`.txt`, `.docx` or text PDF) and one paper DOCX. The request includes an
idempotency ID and acknowledgement that the configured model may process the
Brief. The desktop UI supplies those protocol fields when the user submits the
two files; it must show the Brief-processing disclosure without making source
classification or preview text a third initial input. Uploads are size bounded and checked by the copied parser's input
validator; only the Brief is passed to `parse_academic_with_timeout`. The
Brief, validated `AcademicParseBundle` and immutable V0 are published in one
version-store transaction. Reusing the request ID with different bytes returns
a conflict. `GET /api/tasks/{task_id}/academic-parse` returns the Parse Bundle,
including `format_ruleset`: typed academic rules, exact Brief evidence and
machine-readable missing-value issues (`academic-parse-bundle/1.2`). The upload
route then publishes V1 with a DOCX, report
and selectable preview before requesting any classification or preview
selection. The current initial publisher copies V0 unchanged and reports all
unplanned candidates; it does **not** yet achieve the product's target of
automatically fixing most supported format problems. Editor capability checks,
automatic planning and broad editor coverage remain development work. No unverified
model candidate is promoted into an executable rule.

`easyformat.local_api.bind_local_api` reserves a random `127.0.0.1` port,
creates a session token and origin-bound FastAPI app, and returns a binding
whose `serve()` method starts Uvicorn on that reserved socket. The desktop
shell must keep the token within its own UI. Every API request needs the
`X-EasyFormat-Session` header; browser `Origin` must match the bound local URL.
The API disables documentation routes, rejects non-loopback Host headers and
does not enable cross-origin access.

For an internally provisioned task, the current routes are:

| Route | Action |
| --- | --- |
| `POST /api/tasks` | Upload Brief and paper, run academic parse-only, publish V0 and initial V1 |
| `GET /api/tasks/{task_id}` | Read working version and rule snapshot ID |
| `GET /api/tasks/{task_id}/academic-parse` | Read stored Parse Bundle and evidence |
| `GET /api/tasks/{task_id}/versions` | List version metadata without disk paths |
| `GET /api/tasks/{task_id}/versions/{version_id}/body-alignment/review` | Read target review and review hash |
| `POST .../body-alignment/confirm` | Record a complete paragraph classification and return an executable plan |
| `POST .../body-alignment/execute` | Rebuild the plan from trusted rules and the saved decision, then publish one version |
| `GET /api/tasks/{task_id}/versions/{version_id}/artifacts/{kind}` | Download registered DOCX, JSON/Markdown report or PDF preview |

The upload response uses `task-intake/1.1` and returns the initial V1 ID and
its actual format status. The confirmation and execution requests use the versioned contracts in
`contracts/body-scope-confirmation/` and `contracts/body-plan-execution/`.
They carry an expected DOCX hash and separate request IDs. The execution
request cannot submit rule text, values, target paths or an editor manifest.
The server rechecks the plan before the editor runs. This API currently
executes one unambiguous, explicit Brief rule for body paragraph alignment
after trusted rule snapshot registration. That narrower later-edit route is
not part of the automatic first pass; the automatic planner and UI remain to
be implemented.

Run the storage checks with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\version_store
.\.venv\Scripts\python.exe -m pytest -q tests\workflow
.\.venv\Scripts\python.exe -m pytest -q tests\target_planning
.\.venv\Scripts\python.exe -m pytest -q tests\local_api
.\.venv\Scripts\python.exe -m pytest -q tests\academic_intake
```
