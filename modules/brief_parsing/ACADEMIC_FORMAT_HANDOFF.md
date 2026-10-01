# Academic formatting handoff

`BriefParserService.parse_academic` returns `AcademicParseBundle/1.2`. Its
`format_ruleset` field is an `AcademicFormatRuleSet/1.2` for the downstream
format editor. The parser never edits the paper DOCX. The 1.0 and 1.1
contracts remain readable for stored history.

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
| Bibliography heading and list location | `bibliography_heading` or `bibliography`, font/alignment or `document.position` | heading values or `after_body` / `document_end` / `before_body` |
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
version bump when their meaning changes. The 1.1 extractor is retained in
`academic_common_v1_1.py` to validate stored 1.1 Bundles; 1.2 output uses the
expanded implementation. Existing rules and evidence links remain
readable. The domain pack's category list can grow independently
from the DOCX editor's capability table.

Current limitations: this literal pass covers tested explicit sentence patterns;
it does not infer missing values, resolve semantic conditions, or turn template
visual formatting into a school rule. Unrecognized wording requires further
grammar coverage and review. Source-region classification and template structure
observation remain future work. The DOCX editor currently implements only
paragraph alignment, so these additional parser rules are handoff data for
later editor development.
