# DOCX engine development

`EasyFormat.DocxIndex` is the first read-only prototype for the selection anchor
boundary. It reads `word/document.xml`, builds version-local paragraph IDs, and
requires an exact text and context match. It never edits the source DOCX.

Run from the EasyFormat root:

```powershell
dotnet run --project services/docx_engine/EasyFormat.DocxIndex -- index TestDocuments/材料学院毕业论文模板2026.docx
dotnet run --project tests/DocxIndex.Checks -- TestDocuments/材料学院毕业论文模板2026.docx
```

The index omits headers, footers, footnotes, endnotes, and layout coordinates.
It cannot prove that PDF.js text layer offsets refer to the selected DOCX text.
The caller must bind a hint to a real preview artifact and use a renderer-aware
mapping check before enabling edits. Repeated or missing text and cross-paragraph
selections return a state requiring user action. PDF page and text layer fields
are retained as hints only and never choose a DOCX object by themselves.

The index prototype is deliberately read-only. Editing is a separate project.

`EasyFormat.DocxEditor` now implements the first isolated edit primitive:
`paragraph.alignment` for one version-local paragraph. Its JSON manifest
requires a base DOCX hash, target paragraph ID and text hash, explicit
`paragraph` effective scope, and distinct input/output filenames inside a
task directory. It copies V0, edits the copy through Open XML SDK, validates
the package and target property, compares main-document text and every other
DOCX part, then publishes the new file. A failed candidate is removed; a
published output is never overwritten. This is an engine primitive, not yet
the complete rule planner or product workflow.

```powershell
dotnet run --project tests/DocxEditor.Checks
```

The editor currently handles only direct paragraph alignment. It does not
resolve inherited styles, process a full rule set, refresh fields, or produce
the versioned Markdown report and preview. Those are later increments.
