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
primitive; it does not yet generate a full rule report, run the DOCX editor,
authorize API downloads, or implement task UI. Report validation currently
checks identity, UTF-8 JSON and Markdown, size, and file hashes; a full report
schema is still needed before workflow publication.

Run the storage checks with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\version_store
```
