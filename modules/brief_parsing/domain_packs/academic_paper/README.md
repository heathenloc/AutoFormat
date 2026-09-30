# academic_paper

Formal academic-paper vocabulary for Brief Parsing. Categories cover the P0
editable objects and requirements that must only be checked or reported.

The generic `ExecutionBrief` compiler list is intentionally empty. EasyFormat
projects validated Requirement IR through the separate
`BriefParserService.parse_academic` returns a parse-only Bundle, then
`AcademicFormatCompiler` projects it. That path requires an explicit source
classification and does not turn template observations or model output into
DOCX commands.
The current compiler recognizes only unambiguous body-paragraph alignment.
Other categories are retained for later domain normalization and reporting.
