# DOCX engine development

`EasyFormat.DocxIndex` is the first read-only prototype for the selection anchor
boundary. It reads `word/document.xml`, builds version-local paragraph IDs, and
requires an exact text and context match. It never edits the source DOCX.

Run from the EasyFormat root:

```powershell
dotnet run --project services/docx_engine/EasyFormat.DocxIndex -- index TestDocuments/材料学院毕业论文模板2026.docx
dotnet run --project services/docx_engine/EasyFormat.DocxIndex -- inspect TestDocuments/材料学院毕业论文模板2026.docx
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

`EasyFormat.DocxEditor` now implements the first isolated edit primitive:
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
