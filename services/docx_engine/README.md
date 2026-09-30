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

The production editor will use Open XML SDK, a separate file copy, a typed edit
plan, and post-edit validation. This prototype is deliberately read-only.
