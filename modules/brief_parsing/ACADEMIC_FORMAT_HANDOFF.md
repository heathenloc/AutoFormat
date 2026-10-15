# Academic formatting handoff

`BriefParserService.parse_academic` returns `AcademicParseBundle/1.6`. Its
`format_ruleset` field is an `AcademicFormatRuleSet/1.5` for the downstream
format editor, alongside `AcademicSourceReview/1.2` in `source_review` and
`TemplateLayoutReport/1.1` in `template_layout`.
The parser never edits the paper DOCX. The 1.0 through 1.5
contracts remain readable for stored history.

The deterministic pass reads the generic `Requirement IR` evidence index. It
only emits a `verified` rule when a known target, a single literal value, and
an exact source quote can be established. The current projector also validates
model Requirements against independently proven target, property, value, unit,
constraint and full scope. Accepted candidates retain the original Requirement
ID; duplicates share one rule. `candidate_reviews` records accepted, covered,
pending and rejected proposals without authorizing edits on its own.
The Bundle validator recomputes the deterministic handoff from its IR, so a
changed value or evidence link cannot be accepted as a valid saved Bundle.
Source decisions and review items are also recomputed from the IR evidence.

## Scope and source review

See [expression and candidate conversion](../../docs/brief-parsing-expression-candidates.md)
for the new bounded Chinese/English expressions, typed proof requirements,
history guarantees and deferred real-Brief accuracy evaluation.

`academic_paper@1.1.0` excludes word counts, word/page length limits, keyword
and reference counts, research/content requirements, signatures and deadlines.
Those fragments never become requirements, missing-value warnings, omissions,
or questions. Original input evidence remains available without extracting
content/count targets. Mixed clauses are split with exact source spans before
model calls; format fragments remain eligible. Models receive trusted scope
instructions and their output is filtered again. This policy is specific to
`academic_paper`; the generic parser's other domains keep their existing scope.

The deterministic source classes are `explicit_requirement`, `example`,
`background`, `template_observation`, `out_of_scope`, and `uncertain`. Example
paragraph/section boundaries and ambiguous example tables are handled
conservatively. Visual template styles are never promoted into requirements.

The independent review compares each detected format property against typed
rules and explicit issues. It distinguishes `suspected_omission`,
`unsupported_format`, `recognized_pending`, `source_uncertain`, and
`unread_source`. A sentence with one recognized font can still expose an
uncovered paragraph-spacing property. Each item links to the source quote and
paragraph/table/page location. DOCX media, embedded objects, textboxes and
unaudited template headers/footers produce reading diagnostics. Review items
are rendered in parse Markdown and propagated into the initial V1 report;
they do not require user classification before publication.

Cue counts are not measured recall or editor completion. Real Brief gold
annotations remain unconfirmed. Run `scripts/review_brief_sources.py` to
exercise local deterministic source diagnostics with a fake provider, not a
cloud-model or accuracy evaluation. Outputs must stay under project `runtime/`.

## Common properties

| Brief expression | Target and property | Normalized value |
| --- | --- | --- |
| Heading alignment, font, size, bold | `heading_1`–`heading_9`, `paragraph.alignment` / `font.family` / `font.size` / `font.bold` | alignment code, font name, pt, boolean |
| Abstract, table of contents entry, body, figure text, bibliography | Semantic paragraph role, font and basic paragraph properties | same value types |
| Bibliography heading and list location | `bibliography_heading` or `bibliography`, font/alignment or `document.position` | heading values or `after_body` / `document_end` / `before_body` |
| Latin letters or letters and digits | `latin_text` or `latin_digits`, font properties with `character_scope` | font name and pt |
| Horizontal text and full width columns | `body`, `section.text_direction` / `section.column_count` | `horizontal`, `1` |
| Table border, header and body text | `table`, `table_header`, `table_body` | border code, font name and pt |
| Figure caption placement and text | `figure_caption`, `caption.position` and font properties | above/below, font name and pt |
| Page margins | `page`, `page.margin.*` | cm |
| Paper size and page-number style | `page.paper_size`, `page_number.number_format` | `A3` / `A4` / `A5` / `Letter`, `arabic` / `lower_roman` / `upper_roman` |
| Line spacing, paragraph spacing and indents | paragraph role, `paragraph.line_spacing`, `spacing_before` / `spacing_after`, indent properties | multiplier, exact/atLeast mode with pt, or explicit pt/cm/characters |
| TOC depth | `toc`, `toc.max_depth` | integer |

## Template observations

The DOCX reader consumes the same secured, immutable Brief bytes as text
ingestion. It reads declared logical page, paragraph, run, style/theme, border,
header/footer and note properties. Each observation has its source hash, part,
XPath, object indices, raw property provenance and fixed pending-confirmation
status. It never infers a school requirement from the paper's existing format.

Groups compare role/property/script/unit against verified explicit rules and
pending issues. They distinguish source mismatch, pending explicit items,
inconsistent observations, unresolved values, unmentioned attributes and
matching explicit rules. Missing or cyclic styles, conditional tables and
unresolved themes remain unknown. Simple complete grids can be classified as
all borders or no borders; three-line and merged-cell visual edges need further
resolution. PAGE fields are observed without refreshing or fully interpreting
all switches. Header variants are logical definitions, not predicted page use.

Parse Markdown and initial V1 reports expose these groups after upload. No
template observation becomes an executable rule and no template answer is
required before V1. Confirmed-observation compilation and decision APIs are now
implemented in a separate immutable decision snapshot; product question UI
remains later work. Intake and reopening recompute observations from the actual
Brief, beyond Bundle validation's source binding and group checks.

Non-DOCX inputs continue literal parsing with a layout-unavailable diagnostic.
Full visual regions, OCR, textboxes, content controls and complex table edges
remain outside this increment. See [the template development record](../../docs/brief-parsing-template-layout.md).

## Parser-side user decisions (1.0)

`AcademicDecisionEngine` consumes the unchanged current Bundle plus typed,
append-only events. It emits `AcademicDecisionSnapshot/1.0`, with
`AcademicEffectiveRule/1.0`, provenance, complete scope axes, conflicts/fragments,
remaining questions and decision effects (`applied`, `superseded`, `invalidated`).
Conditions and source conflicts precede category confirmation. Unresolved
observations cannot be promoted. Confirmed unsupported properties remain
`report_only / check_only`. Conflict winners replace only the intersection;
clarified values retain scope and must satisfy the original constraint.

The API persists answers and snapshots atomically and verifies source replay,
hashes and history. It opens questions only after V1. Revision explicitly
supersedes an existing answer; changed candidates invalidate dependent answers.
Requests bind current paper version and expected snapshot, with idempotent IDs.
History does not modify the source Bundle or any paper artifact. `raw_answer`
is audit text only. Historical Bundle versions remain readable, but decision
compilation accepts 1.5 and 1.6 and never reuses answers across Brief hashes.

The downstream editor must consume the full effective-rule snapshot and verify
scope, provenance, operation support and paper targets. It must not flatten
scoped rules into the legacy alignment demo contract. Its existing planner
still uses that separate legacy snapshot; broader execution is the next module.
API examples and acceptance boundaries are in
[the fifth increment](../../docs/brief-parsing-decision-loop.md).

The parser recognizes Chinese sizes such as `小三号` and `小4号`, common font
names, point sizes, and explicit alignment words. A DOCX heading's structural
path supplies its heading level for parenthesized shorthand such as
`绪论（居中、小三号、黑体加粗）`. The `目录` section path keeps its heading-level
requirements separate from paper headings. Explicit table border and figure
caption placement instructions are reported, while figure image editing remains
outside the current editor. Adjacent format clauses in one source paragraph
inherit the stated target and retain both target and value evidence. Repeated identical lines are
collapsed into one rule with all source evidence references.

The supplied `论文常见格式要求.docx` is a checklist of requirement categories that
may appear in a real Brief. It is not itself the school's formatting Brief.
The regression matrix uses concrete, varied Brief sentences for every listed
category: abstract font and size; three TOC heading levels; first and second
paper headings; body direction, columns, font and size; figure text; table
border, header and body text; bibliography heading or position; and Latin
letters. A separate safety test checks that category labels with missing values
do not produce invented font, size, border or bold rules. An ambiguous `一号标题`
is not silently interpreted as `一级标题`.

## Editor trust boundary and extensions

The editor should consider rules or explicit scope fragments with `status=verified`, then independently
check that it supports the target and property, can locate the object in the
selected paper version, and can verify its edit. A parser rule is not an edit
manifest. Typed `semantics` carries object/script/chapter/ordinal/region/submission
scope, interval or bound constraints, and conditions. `relations`, `conflicts`
and `fragments` preserve the exact intersection and unaffected remainder.
A partially conflicting parent rule stays pending; only separately verified
fragments can be considered, without dropping any scope filters. The current
alignment planner rejects scoped selectors it cannot interpret. Intervals and
bounds stay `check_only`; conditions stay pending until a task scenario or
decision is established. No more-specific or later-rule priority is assumed.
An item with a missing value, an ambiguous role or an
unsupported phrase remains an issue; template layout observations are never
promoted into Brief text requirements.

The target and property identifiers are open strings in the versioned
contract; normalized values are JSON values with an explicit unit and
dictionary version. New syntax and complex object handlers belong in
`brief_parser.compilers.academic_semantic_extractor` and `academic_scope`, with regression fixtures and a
version bump when their meaning changes. The 1.1, 1.2 and 1.3 extractors are retained
in their versioned modules, alongside frozen source and template 1.0 helpers, to validate stored
Bundles with their original meanings. Existing rules and evidence links remain
readable. The domain pack's category list can grow independently
from the DOCX editor's capability table.

Current limitations: this literal pass covers tested explicit sentence patterns;
it does not infer missing values, resolve semantic conditions, or turn template
visual formatting into a school rule. Unrecognized wording requires further
grammar coverage and review. Full visual-region classification, conditional table
context, field-switch interpretation and OCR remain future work. The DOCX editor currently implements only
paragraph alignment, so these additional parser rules are handoff data for
later editor development.

See [the fourth increment's semantic examples and limitations](../../docs/brief-parsing-rule-semantics.md).
