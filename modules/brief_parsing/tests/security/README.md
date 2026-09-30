# Security tests

Synthetic malicious fixtures cover MIME mismatch, invalid UTF-8, DOCX path
traversal, unsafe XML, compression bombs, encrypted PDF, page limits, and
prompt injection isolation. Source instructions remain inside the untrusted
user-data envelope and never enter the system message.
