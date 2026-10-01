# EasyFormat

EasyFormat is under staged development. The approved product scope and technical
boundaries are in [EasyFormat_Technical_Architecture.md](EasyFormat_Technical_Architecture.md),
[EasyFormat_PRD.md](EasyFormat_PRD.md), and [BriefParsing_EasyFormat.md](BriefParsing_EasyFormat.md).

## Current development increment

- The copied Brief Parsing source remains in `modules/brief_parsing/` and is
  independent of the read-only source project. Its 180-file source snapshot is
  retained; intentional EasyFormat changes to copied files are pinned in
  `LOCAL_CHANGES.json` and checked separately.
- The copied parser has a formal `academic_paper` Domain Pack and a deterministic
  evidence pass for common paper formatting. `AcademicParseBundle/1.2` carries
  an `AcademicFormatRuleSet/1.2` handoff with typed values and exact Brief
  evidence. The supplied common-requirements DOCX is a capability checklist;
  realistic Brief sentences with concrete values are covered by category tests.
  The older
  `AcademicFormatCompiler` remains available for separately classified model
  candidates. See [the handoff guide](modules/brief_parsing/ACADEMIC_FORMAT_HANDOFF.md).
- `services/docx_engine/EasyFormat.DocxIndex` is a read-only DOCX paragraph
  index and exact selection anchor prototype. Its unique matches are safe
  candidates for later verification, not permission to edit yet.
- `services/docx_engine/EasyFormat.DocxEditor` applies one typed paragraph
  alignment operation or a confirmed batch to a new DOCX copy. A batch checks
  every target before editing and verifies all paragraph alignments and text
  before exposing one output. Hidden or revision content remains blocked.
- `apps/api` now has a replaceable LibreOffice preview adapter. It produces
  versioned PDF metadata and rejects unsafe input before launching the
  renderer. See [local setup](docs/libreoffice-local-setup.md).
- The API package now provides a PDF provenance and text check for preview
  selections. The C# index requires trusted version and preview metadata
  before locating a selection. Repeated text and complex paragraphs pause for
  user targeting. This read-only anchor is not an edit command.
- A local SQLite version store now publishes immutable V0/V1 and later
  branches, checks every artifact hash, and keeps user decisions separate from
  DOCX versions.
- Version reports now have a JSON fact contract and deterministic Markdown
  output. Publication checks evidence links, rule counts, preview metadata,
  and cumulative history against the selected parent version.
- `easyformat.workflow` connects a confirmed, typed Brief paragraph-alignment
  rule to the C# editor, LibreOffice preview, report, and version store. It
  supports V0→V1, later edits, and request replay. Rule extraction, broader
  formatting properties, feedback decisions, and UI remain separate work.
- The academic parse-only service returns a versioned Bundle without a generic
  `ExecutionBrief`. Its literal-format pass does not require a user to classify
  each explicit, deterministically verified line. Model-only candidates still
  need a trusted classification before they can become rules.
- The DOCX index exposes a versioned, read-only target profile, including
  direct paragraph alignment. The API checks the index binary and DOCX hashes
  before reviewing a global body rule. `Normal` is only a candidate. A complete
  user classification of every paragraph is recorded as a decision bound to
  the review hash; eligible body paragraphs then form a typed `edit-plan/1.0`.
  The batch workflow rechecks the plan and decision, edits one candidate DOCX,
  and publishes one version with per-target verification, report and preview.
  A session-protected local API now accepts a school Brief and paper DOCX,
  calls the copied parser's academic parse-only path, and stores the Brief,
  Parse Bundle and V0 together. It immediately publishes a V1 DOCX, report
  and preview before any selection or follow-up input. The current V1 publisher
  is a transparent unchanged-copy baseline: automatic rule planning and broad
  formatting coverage still need implementation before the product meets its
  first-pass quality target. Review, confirmation, execution, version listing
  and registered artifact downloads remain available for later edits.

## Local checks

Use Python 3.12 to install the parser copy and its test dependencies into an
ignored `.venv`. Then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_source_snapshot.ps1
cd modules/brief_parsing
../../.venv/Scripts/python.exe -m pytest -q --ignore=tests/contract/test_infrastructure_baseline.py
cd ../..
dotnet run --project tests/DocxIndex.Checks -- TestDocuments/材料学院毕业论文模板2026.docx
dotnet run --project tests/DocxEditor.Checks
./.venv/Scripts/python.exe -m pytest -q tests/preview
./.venv/Scripts/python.exe -m pytest -q tests/version_store
./.venv/Scripts/python.exe -m pytest -q tests/reports
./.venv/Scripts/python.exe -m pytest -q tests/workflow
./.venv/Scripts/python.exe -m pytest -q tests/target_planning
./.venv/Scripts/python.exe -m pytest -q tests/local_api
./.venv/Scripts/python.exe -m pytest -q tests/academic_intake
```

The four excluded infrastructure tests reference deployment files deliberately
omitted from the Brief Parsing copy (`Dockerfile`, `compose.yaml`, `deploy/`,
and `.github/`). They are not tests of this project's parser runtime. Two
Linux process isolation tests skip on Windows.

The DOCX prototype requires .NET 10. Preview conversion has been exercised
with a signed LibreOffice 26.8.0 administrative image in `E:\LibreOffice`;
the school template remains blocked by the renderer's embedded-object safety
check. See [the engine notes](services/docx_engine/README.md) and
[preview setup](docs/libreoffice-local-setup.md) for current boundaries.
