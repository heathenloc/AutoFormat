# DOCX engine development

The academic editor increment (2026-10-04) now implements semantic planning and
editing for all 35 currently registered typed properties. Use `capabilities`,
`inspect-academic`, `plan-academic`, and `apply-academic`; old commands remain
compatible. Source replay belongs to the Python `AcademicEditor` boundary, so
raw client or model manifests must never call this internal CLI directly.
See [coverage, contracts, verification and remaining boundaries](../../docs/docx-engine-core-v1.md)
and run `dotnet run --project tests/AcademicEditor.Checks`.

Step 3 adds `inspect-selection <docx>` to the academic editor CLI. It reads
paragraph text and UTF-16 positions using the same opaque `o:` object IDs as
`inspect-academic`, without editing the package. Separate story IDs prevent
joining main text with headers, footers or different notes. Fields, hidden or
revised text and unreliable inline structures are marked unsupported. Python
rechecks the saved PDF's text layer, resolves candidates and handles target
confirmation. See [selection step 3](../../docs/preview-selection-step3.md).

Step 6 adds `plan-feedback` and `apply-feedback` with a strict typed
`feedback-edit-manifest/1.0`. Python replays source decisions and sends exact
objects and UTF-16 character fragments; the editor splits safe text runs, checks
physical property conflicts, preserves content, and reads back effective values
after saving. It never executes raw feedback. Any unsupported target rejects the
whole candidate. Historical input stays immutable, including already-satisfied
edits. See [feedback editing step 6](../../docs/preview-feedback-editing-step6.md).

The following notes describe the earlier selection/alignment prototypes.

`AutoFormat.DocxIndex` is the first read-only prototype for the selection anchor
boundary. It reads `word/document.xml`, builds version-local paragraph IDs, and
requires an exact text and context match. It never edits the source DOCX.

Run from the AutoFormat root:

```powershell
dotnet run --project services/docx_engine/AutoFormat.DocxIndex -- index TestDocuments/材料学院毕业论文模板2026.docx
dotnet run --project services/docx_engine/AutoFormat.DocxIndex -- inspect TestDocuments/材料学院毕业论文模板2026.docx
dotnet run --project tests/DocxIndex.Checks -- TestDocuments/材料学院毕业论文模板2026.docx
```

The index omits headers, footers, footnotes, endnotes, and layout coordinates.
`inspect` returns a `docx-target-index/1.0` with text hashes, paragraph paths,
direct alignment and structural role signals. A `Normal` paragraph is only a body candidate;
heading styles, tables, numbering, hidden content, and custom styles are
reported separately. It does not decide the complete academic body scope.
It cannot prove that PDF.js text layer offsets refer to the selected DOCX text.
Before calling `locate`, the caller must run the API package's
`verify_pdf_selection` check against saved artifact metadata. It checks the
PDF hash, page count, source DOCX hash, and that the selected text occurs once
on the claimed PDF page.
`locate` also requires a `PreviewBinding` loaded from trusted version metadata;
the client must never supply this binding. Its version, DOCX hash, preview ID,
renderer, and page count must match the selection hint. Repeated or missing
DOCX text, mismatched context, tracked or hidden content, and cross-paragraph
selections require user action. PDF page and text layer fields are retained as
hints only and never choose a DOCX object by themselves.

`SelectionAnchor/1.0` is emitted only for a unique safe match. It preserves the
version, preview renderer, selected text, PDF hint and version-local DOCX span.
An anchor is location evidence, not an executable formatting rule. It still
needs feedback interpretation, a confirmed typed rule and an edit plan before
an edit can run. The PDF.js text-layer offsets cannot yet be independently
verified, so this boundary is not the complete feedback workflow.

The index prototype is deliberately read-only. Editing is a separate project.

`AutoFormat.DocxEditor` now implements the first isolated edit primitive:
`paragraph.alignment` for one version-local paragraph. Its JSON manifest
requires a base DOCX hash, target paragraph ID and text hash, explicit
`paragraph` effective scope, and distinct input/output filenames inside a
task directory. It copies V0, edits the copy through Open XML SDK, validates
the package and target property, compares main-document text and every other
DOCX part, then publishes the new file. A failed candidate is removed; a
published output is never overwritten. This is an engine primitive, not yet
the complete product workflow.

The `apply-batch` command accepts a typed `edit-batch-manifest/1.0` with
multiple confirmed paragraph targets. It checks the base hash, target IDs,
paths, text hashes, current direct alignments and structural safety before
editing. All changes are made to one staging copy; the result is exposed only
after Open XML, text, alignment and non-target package checks pass. It returns
one `edit-batch-result/1.0` with a result for every operation.

```powershell
dotnet run --project tests/DocxEditor.Checks
```

The editor currently handles only direct paragraph alignment. It does not
resolve inherited styles or refresh fields. The Python workflow produces the
versioned Markdown report and preview for a confirmed body-alignment batch.
