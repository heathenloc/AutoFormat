# Academic formatting handoff

`BriefParserService.parse_academic` returns `AcademicParseBundle/1.1`. Its
`format_ruleset` field is an `AcademicFormatRuleSet/1.1` for the downstream
format editor. The parser never edits the paper DOCX. The old 1.0 contracts
remain readable for stored history.

The deterministic pass reads the generic `Requirement IR` evidence index. It
only emits a `verified` rule when a known target, a single literal value, and
an exact source quote can be established. Model-only candidates still need a
trusted source classification through the separate conservative compiler.
The Bundle validator recomputes the deterministic handoff from its IR, so a
changed value or evidence link cannot be accepted as a valid saved Bundle.

## Common properties

| Brief expression | Target and property | Normalized value |
| --- | --- | --- |
| Heading alignment, font, size, bold | `heading_1`–`heading_4`, `paragraph.alignment` / `font.family` / `font.size` / `font.bold` | alignment code, font name, pt, boolean |
| Abstract, table of contents entry, body, figure text, bibliography | Semantic paragraph role, font and basic paragraph properties | same value types |
| Latin letters or letters and digits | `latin_text` or `latin_digits`, font properties with `character_scope` | font name and pt |
| Horizontal text and full width columns | `body`, `section.text_direction` / `section.column_count` | `horizontal`, `1` |
| Table border, header and body text | `table`, `table_header`, `table_body` | border code, font name and pt |
| Figure caption placement and text | `figure_caption`, `caption.position` and font properties | above/below, font name and pt |
| Page margins | `page`, `page.margin.*` | cm |
| Paper size and page-number style | `page.paper_size`, `page_number.number_format` | `A4`, `arabic` or `lower_roman` |
| Line spacing and first line indent | paragraph role, `paragraph.line_spacing` / `paragraph.first_line_indent` | multiplier or characters/cm |
| TOC depth | `toc`, `toc.max_depth` | integer |

The parser recognizes Chinese sizes such as `小三号` and `小4号`, common font
names, point sizes, and explicit alignment words. A DOCX heading's structural
path supplies its heading level for parenthesized shorthand such as
`绪论（居中、小三号、黑体加粗）`. The `目录` section path keeps its heading-level
requirements separate from paper headings. A literal `表格使用三线表` or
`图示在下` instruction is reported, while figure image editing remains outside
the current editor. Repeated identical lines are
collapsed into one rule with all source evidence references.

The supplied `论文常见格式要求.docx` contains four literal values: first-level
heading centered, second-level heading left aligned, body horizontal text,
and one column. It also contains 26 properties without values or with an
ambiguous target, including `一号标题字体` (which is not silently interpreted as
`一级标题字体`). Those are typed `needs_value` or `ambiguous_target` issues with
the original text, semantic target, property ID and evidence ID. No font name,
size, border style or bold answer is invented.

## Editor trust boundary and extensions

The editor should consider only rules with `status=verified`, then independently
check that it supports the target and property, can locate the object in the
selected paper version, and can verify its edit. A parser rule is not an edit
manifest. An item with a missing value, a range, an ambiguous role or an
unsupported phrase remains an issue; template layout observations are never
promoted into Brief text requirements.

The target and property identifiers are open strings in the versioned
contract; normalized values are JSON values with an explicit unit and
dictionary version. New syntax and complex object handlers belong in
`brief_parser.compilers.academic_common`, with regression fixtures and a
version bump when their meaning changes. The 1.1 extractor's behavior must be
kept available to validate stored 1.1 Bundles; a later version should use a
separate implementation. Existing rules and evidence links must remain
readable. The domain pack's category list can grow independently
from the DOCX editor's capability table.

Current limitations: this literal pass does not infer missing values or
resolve semantic conditions, and it does not turn template visual formatting
into a school rule. Broader Brief phrasing, source-region classification and
template structure observation can be added while retaining the same handoff
boundary. The DOCX editor currently implements only paragraph alignment, so
these additional parser rules are handoff data for later editor development.
