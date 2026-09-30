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
