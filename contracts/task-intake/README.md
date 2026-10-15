# Task intake response versions

`task-intake/1.0` is the historical parse-only response. It stopped before an
initial DOCX was published and is retained only to interpret older responses.

`task-intake/1.1` is the historical auto-publish response. A successful upload has already
published V1 and includes its version ID, DOCX hash, actual format status and
pending count. The initial request does not contain a preview selection or
free-text formatting instruction.

`task-intake/1.2` is current. Pending questions return `reviewing_requirements` with null initial-output fields; the editor is not invoked. Choose an answer or explicitly skip each question, then POST `/initial-draft` with V0/hash and the current decision snapshot. With no pending questions, upload directly publishes V1. Historical schemas are unchanged.
