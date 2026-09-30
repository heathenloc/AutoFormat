# Task intake response versions

`task-intake/1.0` is the historical parse-only response. It stopped before an
initial DOCX was published and is retained only to interpret older responses.

`task-intake/1.1` is the current response. A successful upload has already
published V1 and includes its version ID, DOCX hash, actual format status and
pending count. The initial request does not contain a preview selection or
free-text formatting instruction.
