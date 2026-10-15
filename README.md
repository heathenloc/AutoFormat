# AutoFormat

源码仓库：[heathenloc/AutoFormat](https://github.com/heathenloc/AutoFormat)。产品网页与交互原型的 GitHub Pages 配置见 [发布说明](docs/github-pages.md)。

在线展示：[产品网页](https://heathenloc.github.io/AutoFormat/) · [交互原型](https://heathenloc.github.io/AutoFormat/prototype/index.html#upload)。

项目于 2026-10-08 由 EasyFormat 更名为 AutoFormat。更名范围、开发环境更新和历史兼容说明见 [更名记录](docs/project-rename-autoformat.md)。

> 2026-10-07 流程修订：待确认项在解析完成后、首次格式编辑前处理。用户逐项选择候选答案或明确暂时忽略，之后才能生成 V1；没有待确认项时直接继续。下文带历史日期的增量保留当时状态，当前流程以本修订和 `docs/pre-edit-review.md` 为准。


AutoFormat is under staged development. The approved product scope and technical
boundaries are in [AutoFormat_Technical_Architecture.md](AutoFormat_Technical_Architecture.md),
[AutoFormat_PRD.md](AutoFormat_PRD.md), and [BriefParsing_AutoFormat.md](BriefParsing_AutoFormat.md).

## Current development increment

- `apps/web` now provides the TypeScript/PDF.js local preview workspace:
  immutable version browsing, paging/zoom, text selection, bound reports,
  authenticated downloads and feedback receipts. Step 3 verifies PDF.js item offsets against the saved PDF,
  resolves same-version DOCX character anchors and persists explicit target
  choices for ambiguous or structurally sensitive selections. Step 4 adds
  deterministic feedback parsing, pre-submission scope reviews, structured
  missing-value answers and append-only scope confirmation. Step 5 adds conflict
  decisions, local exceptions and replayable rule snapshots. Step 6 applies ready
  snapshots to new DOCX copies, verifies results, renders previews and publishes
  immutable versions with idempotent recovery. Step 7 restores per-version feedback
  work items, exposes pending report evidence and explicitly continues historical
  versions with append-only branch resets that isolate later exceptions. Pending fragments currently block
  the entire round. See [the preview UI](docs/preview-ui-step2.md),
  [selection resolution](docs/preview-selection-step3.md) and
  [feedback parsing and scopes](docs/preview-feedback-parsing-step4.md),
  [rules and exceptions](docs/preview-feedback-rules-step5.md) and
  [feedback editing and publication](docs/preview-feedback-editing-step6.md) and
  [work items and history branches](docs/preview-workspace-step7.md).

- The copied Brief Parsing source remains in `modules/brief_parsing/` and is
  independent of the read-only source project. Its 180-file source snapshot is
  retained; intentional AutoFormat changes to copied files are pinned in
  `LOCAL_CHANGES.json` and checked separately.
- The copied parser has a formal `academic_paper` Domain Pack and a deterministic
  evidence pass for common paper formatting. `AcademicParseBundle/1.6` carries
  an `AcademicFormatRuleSet/1.5` handoff with typed values and exact Brief
  evidence. The supplied common-requirements DOCX is a capability checklist;
  realistic Brief sentences with concrete values are covered by category tests.
  `AcademicRequirementProjector` now validates model Requirements against
  independent literal proofs, preserves full scope and records candidate reviews.
  The older `AcademicFormatCompiler` remains a body-alignment compatibility demo.
  See [expression and candidate checks](docs/brief-parsing-expression-candidates.md)
  and [the handoff guide](modules/brief_parsing/ACADEMIC_FORMAT_HANDOFF.md).
- The academic parser now filters content/count requirements before model
  calls and checks outputs again. Its source review separates explicit rules,
  examples, background, observations and uncertain evidence, and reports
  property-level omissions and reading blindspots in the parse and V1 reports.
  Word counts, text/page limits and semantic content create no rules or questions.
  History uses frozen 1.1/1.2/1.3/1.4 extractors and versioned source/template helpers. Source diagnostics are not measured recall.
  See [this increment's checks and limitations](docs/brief-parsing-source-review.md).
- `template_layout` now carries read-only DOCX geometry, font/paragraph style
  inheritance, theme origins, table borders, headers/footers and note observations.
  Each observation is pending confirmation and has a source hash and XML location.
  Category groups compare explicit rules and template values; intake and reopening
  recompute the report from the actual Brief. Observations never authorize an edit.
  Complex visual layouts remain future work. Explicit decisions now compile
  observations into a separate, versioned effective-rule snapshot.
  See [template reading checks and boundaries](docs/brief-parsing-template-layout.md).
- Typed rule semantics now preserve object/script/region/chapter/ordinal and
  submission scopes, size intervals/bounds, and unknown conditions. Conflict
  analysis computes intersections and keeps unaffected scope fragments;
  print/electronic branches do not create false conflicts, while system upload
  can overlap electronic submission. No implicit specific-rule priority applies.
  The academic editor now executes verified fragments with full scope preserved.
  See [semantic examples and checks](docs/brief-parsing-rule-semantics.md).
- The parser decision loop now exposes question and answer APIs from V0,
  scenario binding, scoped conflict selection, template confirmation, typed
  clarification, skip/defer and explicit answer revision. Append-only SQLite
  events and `AcademicDecisionSnapshot/1.0` preserve source parsing and paper
  history, validate replay, reject stale/concurrent writes and support exact retries.
  Free-text answer parsing and the product question UI remain future work.
  See [the decision API and editor handoff](docs/brief-parsing-decision-loop.md).
- `services/docx_engine/AutoFormat.DocxIndex` is a read-only DOCX paragraph
  index and exact selection anchor prototype. Its unique matches are safe
  candidates for later verification, not permission to edit yet.
- `services/docx_engine/AutoFormat.DocxEditor` applies one typed paragraph
  alignment operation or a confirmed batch to a new DOCX copy. A batch checks
  every target before editing and verifies all paragraph alignments and text
  before exposing one output. Hidden or revision content remains blocked.
- The new academic editor covers all 35 currently registered typed formatting
  properties, with semantic indexing, safe scope fragments, effective-property
  readback, mixed-script text handling and immutable output. `AcademicEditor`
  replays the parser decision snapshot before calling .NET. Configured local
  hosts now apply safe rules before publishing V1. TOC/page caches remain pending
  a separate verified field refresh. See [the core coverage and boundaries](docs/docx-engine-core-v1.md).
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
- `autoformat.workflow` connects a confirmed, typed Brief paragraph-alignment
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
  Parse Bundle and V0 together. It presents unresolved questions before editing;
  users choose an answer or explicitly skip each item before publishing V1.
  A task with no pending questions proceeds directly. With the real editor
  configured, V1 applies independently verified rules through the 35-property
  academic core; parser-only hosts retain the unchanged-copy baseline. Field
  cache refresh and uncertain targets remain explicit in the report. Review,
  confirmation, execution, version listing
  and registered artifact downloads remain available for later edits.

## Local checks

The complete local host now opens a dual-file home page, pre-edit review and the
preview workspace, with a session-protected task catalog for reopening saved work.
Windows test bundles include the copied parser and runtime dependencies; targets
still need Python 3.12, Node 24, .NET 10 and LibreOffice. See the
[step 8 setup and remaining delivery work](docs/preview-desktop-step8.md) and
[test bundle instructions](desktop/README.md). The native WebView2 shell and a
standalone installer remain unfinished.

Use Python 3.12 to install the parser copy and its test dependencies into an
ignored `.venv`. Then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_source_snapshot.ps1
cd modules/brief_parsing
../../.venv/Scripts/python.exe -m pytest -q --ignore=tests/contract/test_infrastructure_baseline.py
cd ../..
dotnet run --project tests/DocxIndex.Checks -- TestDocuments/材料学院毕业论文模板2026.docx
dotnet run --project tests/DocxEditor.Checks
dotnet run --project tests/AcademicEditor.Checks
./.venv/Scripts/python.exe -m pytest -q tests/preview
./.venv/Scripts/python.exe -m pytest -q tests/version_store
./.venv/Scripts/python.exe -m pytest -q tests/reports
./.venv/Scripts/python.exe -m pytest -q tests/workflow
./.venv/Scripts/python.exe -m pytest -q tests/target_planning
./.venv/Scripts/python.exe -m pytest -q tests/local_api
./.venv/Scripts/python.exe -m pytest -q tests/academic_intake
./.venv/Scripts/python.exe -m pytest -q tests/academic_editor
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
