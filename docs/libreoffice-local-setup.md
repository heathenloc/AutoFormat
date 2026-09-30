# Local LibreOffice setup for preview development

The user supplied `E:\LibreOffice\LibreOffice_26.8.0_Win_x86-64.msi`.
Before execution on 2026-09-30, its Windows Authenticode status was `Valid`,
the signer was `The Document Foundation`, the size was 374,906,880 bytes,
and SHA-256 was
`4aa6c6e1895f4055104effcb556bd3362d20c6ad707c149543304f395ef9db95`.
The size and SHA-256 match the
[official 26.8.0 mirror information](https://download.documentfoundation.org/libreoffice/stable/26.8.0/win/x86_64/LibreOffice_26.8.0_Win_x86-64.msi.mirrorlist).

The MSI was extracted with administrative mode (`msiexec /a`) into
`E:\LibreOffice\26.8.0-admin`. The normal install mode (`/i`) was not used.
The extracted `program\soffice.com` is also Authenticode-valid and has SHA-256
`95016b59e08da1e6cbb02fc8f027593c076bf47df795092578afdd995306ac85`.
The console launcher reports `LibreOffice 26.8.0.3`.

All test conversions use `--headless`, `-env:UserInstallation=file:///...`
pointing to a fresh project-local profile, and output directories under
`E:\EasyFormat\runtime` (ignored by Git). The renderer never searches `PATH`
for LibreOffice, rechecks the executable hash, copies a validated DOCX into the
per-conversion work directory, and passes arguments without
a shell. It limits runtime, output size and page count, checks the PDF text
layer, and refuses embedded objects and external relationships before launch.

The first synthetic DOCX converted to a one-page PDF with selectable Chinese
and English text. A provided school template has an embedded object and was
rejected by preflight; no conversion of that template was attempted.
On Windows, LibreOffice's isolated profile can create paths longer than the
legacy 260-character limit. The adapter verifies the profile path remains
inside its work root before using an extended-length path for recursive cleanup.
