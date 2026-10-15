"""Deterministic academic scope gate shared by the pipeline and handoff.

This policy interprets document text as evidence, never as agent instructions.
Property cues are intentionally broader than the safe value compiler, so a
partially recognized sentence can still appear in the omission review.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from brief_parser.domain.academic_source_review import AcademicSourceDecision, SourceClass
from brief_parser.domain.requirement_ir import EvidenceReference


OUT_OF_SCOPE = re.compile(
    r"字数|词数|篇幅|页数|字符数|文本长度|word[ _-]?count|word[ _-]?limit|page[ _-]?limit|"
    r"\d\s*(?:万字|千字|个字|字(?!符)|words?\b|pages?\b)|"
    r"(?:不少于|不超过|最多|至少|约|为|建议)\s*[\d一二三四五六七八九十百千～~—\-至到]+\s*(?:字|词|页|个关键词|篇文献)|"
    r"关键词.{0,8}(?:\d+[～~—\-至到]?\d*|[三四五六])\s*个|"
    r"(?:文献|参考文献).{0,12}(?:不少于|至少|不低于|近\s*\d+\s*年|\d+\s*篇)|"
    r"研究(?:内容|方法|目的|意义|结论)|选题|创新(?:点|性)|论证|实验(?:结果|数据)|"
    r"(?:摘要|正文|引言|结论).{0,8}(?:应包括|应包含|内容包括|阐述|概括)|"
    r"不得抄袭|查重|重复率|学术不端|签字|签名|答辩|截止日期",
    re.IGNORECASE,
)
PROPERTY_CUES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE)) for name, pattern in (
        ("font.family", r"字体|宋体|黑体|楷体|仿宋|隶书|微软雅黑|华文中宋|Times\s+New\s+Roman|Arial|Calibri|Cambria|Microsoft\s+YaHei"),
        ("font.size", r"字号|小初|初号|小[一二三四五六]|[一二三四五六七八]号|小?[1-8]号|\d+(?:\.\d+)?\s*(?:pt\b|磅)"),
        ("font.bold", r"加粗|粗体"),
        ("paragraph.alignment", r"对齐|居中|居左|居右"),
        ("paragraph.line_spacing", r"行距|line\s+spacing|double.spac|single.spac"),
        ("paragraph.first_line_indent", r"首行缩进"),
        ("paragraph.spacing_before", r"段前"),
        ("paragraph.spacing_after", r"段后"),
        ("paragraph.indent", r"悬挂缩进|左缩进|右缩进"),
        ("page.margin", r"页边距|边距|margins?"),
        ("page.paper_size", r"纸张|A[345]\b|paper\s+size"),
        ("section.text_direction", r"横排|竖排"),
        ("section.column_count", r"通栏|单栏|双栏|两栏|三栏|分栏"),
        ("table.border_style", r"三线表|全框线|边框|框线"),
        ("page_number.number_format", r"页码.*(?:阿拉伯|罗马)|(?:阿拉伯|罗马).*页码"),
        ("page_number.position", r"页码.*(?:页脚|底端|顶端|左侧|右侧|下方)"),
        ("toc.max_depth", r"目录.{0,14}(?:不超过|不能超过|最多).{0,3}级"),
        ("caption.position", r"(?:图题|图注|表题|表注|图示).*(?:上方|下方|在上|在下)"),
        ("document.position", r"参考文献.*(?:正文(?:之)?后|正文(?:之)?前|文末|论文末尾)"),
        ("reference.style", r"GB\s*/?T\s*7714|APA\b|MLA\b|Chicago\b|引用格式|著录格式"),
        ("numbering.format", r"编号|序号|章节号"),
        ("header.content", r"页眉"),
        ("footer.content", r"页脚"),
        ("formula.layout", r"公式.{0,12}(?:对齐|居中|编号|排版)"),
    )
)
FORMAT_GENERIC = re.compile(r"格式|版式|排版|装订线|分页|分页符|分节|题注|上下标")
DIRECTIVE = re.compile(r"必须|应当|应|须|要求|统一|一律|采用|使用|设置|设为|位于|置于|为|用|不得|不能|不超过|最多|shall\b|must\b|required\b", re.IGNORECASE)
TARGET_LABEL = re.compile(r"^(?:(?:本?论文|学位论文)的?)?(?:目录|[一二三四]级标题|正文段落|正文|摘要|关键词|图示|图题|图注|表格|表头文字|表内文字|参考文献|英文字母和数字|英文及数字|字母与数字|英文字母|英文字符|英数字|字母数字|页面|纸张|页码)")
EXAMPLE = re.compile(r"示例|样例|例文|样本文字|仅供参考|参考样式|example\b|sample\b", re.IGNORECASE)
EXAMPLE_HEADING = re.compile(r"^(?:\d+[、.．\s]*)?(?:.*(?:示例|样例|例文|样本文字|参考样式)|example|sample)\s*[：:]?\s*$", re.IGNORECASE)
FORMAT_HEADING = re.compile(r"^(?:\d+[、.．\s]*)?(?:.{0,20})?(?:格式要求|排版要求|版式要求|格式规范|书写规范)\s*[：:]?$")
OBSERVATION = re.compile(r"(?:模板|样张).{0,12}(?:观察|显示|看起来|默认|样式)|观察(?:到|值)|所见样式")
FOLLOWUP = re.compile(r"^(?:字体|字号|加粗|不加粗|位置|对齐|边框|行距|首行缩进|段前|段后|表头|表内文字|表格内容|宋体|黑体|小四|小五|Times\s+New\s+Roman)", re.IGNORECASE)


def scope_match(text: str) -> re.Match[str] | None:
    """A character-sized indent is formatting, not a document word limit."""
    for match in OUT_OF_SCOPE.finditer(text):
        before = text[max(0, match.start() - 20):match.start()]
        if (re.search(r"首行缩进\s*(?:为|是|:|：)?\s*\d*(?:\.\d*)?\s*$", before)
                and re.fullmatch(r"(?:为|是)?\s*[\d.]+\s*字", match.group())):
            continue
        return match
    return None


def format_properties(text: str) -> list[str]:
    properties = []
    for name, pattern in PROPERTY_CUES:
        tokens = re.split(r"[，,；;]", text) if name == "font.size" else [text]
        if any(pattern.search(token) and not (name == "font.size"
                and re.search(r"段前|段后|行距|边距|缩进|线宽", token)
                and not re.search(r"字号|小初|初号|小[一二三四五六]|[一二三四五六七八]号|小?[1-8]号", token)) for token in tokens):
            properties.append(name)
    return properties or (["unclassified.format_property"] if FORMAT_GENERIC.search(text) else [])


def ordered_evidence(evidence: Iterable[EvidenceReference]) -> list[EvidenceReference]:
    # Paragraph numbers are stable after JSON object key reordering. Table cells
    # use section-path context, not inferred proximity to body paragraphs.
    return sorted(evidence, key=lambda item: (
        item.source_id, 1 if item.locator.table is not None else 0,
        item.locator.page or 0, item.locator.paragraph or item.locator.table or 0,
        item.block_id, item.start,
    ))


def classify_evidence(evidence: Iterable[EvidenceReference]) -> list[AcademicSourceDecision]:
    decisions = []
    # Materialize iterables once so generator callers receive the same result.
    refs = ordered_evidence(evidence)
    example_tables = {(ref.source_id, ref.locator.table) for ref in refs
                      if ref.locator.table is not None and EXAMPLE.search(ref.quote)}
    example_regions: dict[str, tuple[str, ...]] = {}
    target_blocks: set[tuple[str, str]] = set()
    for ref in refs:
        text = ref.quote.strip()
        path = tuple(ref.locator.section_path)
        key = (ref.source_id, ref.block_id)
        properties = format_properties(text)
        kind: SourceClass
        if TARGET_LABEL.match(text):
            target_blocks.add(key)
        if FORMAT_HEADING.match(text):
            example_regions.pop(ref.source_id, None)
        region = example_regions.get(ref.source_id)
        in_region = (ref.locator.table is None and region is not None
                     and (not region or path[:len(region)] == region))
        if region and path and path[:len(region)] != region:
            example_regions.pop(ref.source_id, None)
        example = bool(EXAMPLE.search(text) or any(EXAMPLE.search(part) for part in path) or in_region)
        if EXAMPLE_HEADING.match(text) and ref.locator.table is None:
            example_regions[ref.source_id] = path
        # Excluded content does not acquire review obligations even when a
        # paragraph also describes a sample or background section.
        if FORMAT_HEADING.match(text):
            kind, reason, properties = "background", "format_section_heading", []
        elif scope_match(text) and not properties:
            kind, reason = "out_of_scope", "outside_academic_format_scope"
        elif example:
            kind, reason = "example", "illustration_not_authority"
        elif path[:1] in (("header",), ("footer",)) or OBSERVATION.search(text):
            kind, reason = "template_observation", "observed_style_not_authority"
        elif not properties:
            kind, reason = "background", "no_format_property_cue"
        elif (ref.source_id, ref.locator.table) in example_tables:
            kind, reason = "uncertain", "table_example_boundary_unclear"
        elif DIRECTIVE.search(text) or ":" in text or "：" in text or (
            key in target_blocks and (FOLLOWUP.match(text) or TARGET_LABEL.match(text))
        ) or ("（" in text and "）" in text):
            kind, reason = "explicit_requirement", "literal_format_instruction"
        else:
            kind, reason = "uncertain", "format_authority_unclear"
        decisions.append(AcademicSourceDecision(
            evidence_id=ref.evidence_id, source_class=kind, reason_code=reason,
            format_properties=properties if kind != "out_of_scope" else [],
        ))
    return decisions


def is_excluded_candidate(text: str) -> bool:
    """Reject semantic/count output even when its evidence points at format text."""
    return bool(scope_match(text) or re.search(
        r"(?:word|page|character|keyword|reference)[._ -]?(?:count|limit|length)|"
        r"(?:text|paper|abstract)[._ -](?:length|content)|(?:content|research)[._-](?:requirement|quality|method)|"
        r"(?:minimum|maximum)[._-](?:words|pages)|keyword[._-]?count", text, re.IGNORECASE,
    ))
