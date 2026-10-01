# academic_paper

Formal academic-paper vocabulary for Brief Parsing. Categories cover the P0
editable objects and requirements that must only be checked or reported.

The generic `ExecutionBrief` compiler list is intentionally empty.
`BriefParserService.parse_academic` returns a parse-only Bundle. The separate
`AcademicFormatCompiler` handles explicitly classified model IR candidates;
it does not turn template observations or model output into DOCX commands.
The automatic evidence pass in `brief_parser.compilers.academic_common` now
extracts literal, common academic format values from the validated IR evidence
index. Its typed `AcademicFormatRuleSet/1.2` is included in
`AcademicParseBundle/1.2` as `format_ruleset`. Missing values, ambiguous target
levels and unsupported expressions are retained as structured issues. The
older `AcademicFormatCompiler` still handles separately classified model IR
candidates and remains conservative. See
[`ACADEMIC_FORMAT_HANDOFF.md`](../../ACADEMIC_FORMAT_HANDOFF.md) for supported
properties, trust boundaries and extension rules.
