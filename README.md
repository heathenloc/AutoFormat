# EasyFormat

EasyFormat is under staged development. The approved product scope and technical
boundaries are in [EasyFormat_Technical_Architecture.md](EasyFormat_Technical_Architecture.md),
[EasyFormat_PRD.md](EasyFormat_PRD.md), and [BriefParsing_EasyFormat.md](BriefParsing_EasyFormat.md).

## Current development increment

- The copied Brief Parsing source remains in `modules/brief_parsing/` and is
  independent of the read-only source project. The 180 recorded source files
  currently match `SOURCE_SNAPSHOT.json`.
- `services/docx_engine/EasyFormat.DocxIndex` is a read-only DOCX paragraph
  index and exact selection anchor prototype. Its unique matches are safe
  candidates for later verification, not permission to edit yet.
- `services/docx_engine/EasyFormat.DocxEditor` applies one typed paragraph
  alignment operation to a new DOCX copy and verifies the result. The full
  rule planner, feedback workflow, version store, and UI have not been
  implemented.
- `apps/api` now has a replaceable LibreOffice preview adapter. It produces
  versioned PDF metadata and rejects unsafe input before launching the
  renderer. See [local setup](docs/libreoffice-local-setup.md).
- The API package now provides a PDF provenance and text check for preview
  selections. The C# index requires trusted version and preview metadata
  before locating a selection. Repeated text and complex paragraphs pause for
  user targeting. This read-only anchor is not an edit command.
- A local SQLite version store now publishes immutable V0/V1 and later
  branches, checks every artifact hash, and keeps user decisions separate from
  DOCX versions. It is not yet connected to the full task workflow or UI.

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
