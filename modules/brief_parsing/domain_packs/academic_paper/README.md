# academic_paper

Formal academic-paper vocabulary for Brief Parsing. Categories cover the P0
editable objects and requirements that must only be checked or reported.

The generic `ExecutionBrief` compiler list is intentionally empty. EasyFormat
projects validated Requirement IR through the separate
`BriefParserService.parse_academic` returns a parse-only Bundle, then
`AcademicFormatCompiler` projects it. That path requires an explicit source
classification and does not turn template observations or model output into
DOCX commands.
The automatic evidence pass in `brief_parser.compilers.academic_common` now
extracts literal, common academic format values from the validated IR evidence
index. Its typed `AcademicFormatRuleSet/1.1` is included in
`AcademicParseBundle/1.1` as `format_ruleset`. Missing values, ambiguous target
levels and unsupported expressions are retained as structured issues. The
older `AcademicFormatCompiler` still handles separately classified model IR
candidates and remains conservative. See
[`ACADEMIC_FORMAT_HANDOFF.md`](../../ACADEMIC_FORMAT_HANDOFF.md) for supported
properties, trust boundaries and extension rules.
