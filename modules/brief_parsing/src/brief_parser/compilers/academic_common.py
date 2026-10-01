"""Evidence-bound, deterministic extraction of common academic format rules.

This pass recognizes values that are literally present in a Brief. A named
property without a value becomes an issue, never an executable rule. New
properties can be added through the parsers below without changing the public
AcademicFormatRuleSet shape.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any

from brief_parser.domain.academic_format import (
    AcademicFormatIssue, AcademicFormatRule, AcademicFormatRuleSet,
    AcademicTarget, AcademicValue,
)
from brief_parser.domain.enums import EvidenceMatchStatus
from brief_parser.domain.requirement_ir import EvidenceReference, RequirementIR


_VERSION = "academic-common-format/1.0"
_TARGET = re.compile(
    r"^(目录|一级标题|二级标题|三级标题|四级标题|正文段落|正文|摘要|关键词|"
    r"图示|图题|图注|表格|参考文献|英文字母|英文字符|英数字|字母数字|页面|纸张|页码)"
)
_LEVEL = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_HEADING = re.compile(r"([一二三四1-4])级标题")
_FONT = re.compile(
    r"Times\s+New\s+Roman|Microsoft\s+YaHei|Arial|Calibri|Cambria|"
    r"微软雅黑|宋体|黑体|楷体|仿宋|隶书|华文中宋",
    re.IGNORECASE,
)
_SIZES = {
    "初号": 42, "小初": 36, "一号": 26, "小一": 24,
    "二号": 22, "小二": 18, "三号": 16, "小三": 15,
    "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
    "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5,
}
_SIZE = re.compile(r"小初|初号|小[一二三四五六]|[一二三四五六七八]号|"
                   r"小?[1-8]号|(?<!\d)(\d{1,2}(?:\.\d+)?)\s*(?:pt|磅)",
                   re.IGNORECASE)
_ALIGNMENT = {
    "两端对齐": "both", "居中": "center", "居左": "left",
    "左对齐": "left", "居右": "right", "右对齐": "right",
}
_ALIGN_RE = re.compile("|".join(map(re.escape, _ALIGNMENT)))
_MARGIN = re.compile(r"(?:(上|下|左|右)\s*)?页边距\s*(?:为|是|:|：)?\s*"
                     r"(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)", re.IGNORECASE)
_LINE_SPACING = re.compile(r"(?:行距\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)\s*倍|"
                           r"(\d+(?:\.\d+)?)\s*倍行距)")
_INDENT = re.compile(r"首行缩进\s*(\d+(?:\.\d+)?)\s*(字符|字|厘米|cm)", re.IGNORECASE)
_EXAMPLE = re.compile(r"示例|样例|仅供参考|参考样式|例文|样本文字")
_NEGATIVE = re.compile(r"不得|不要|不应|禁止|避免")
_MODAL = re.compile(r"必须|应当|应|须|要求|统一|一律|采用|使用")
_FORMAT_CUE = re.compile(r"字体|字号|对齐|位置|边框|行距|缩进|页码|目录|加粗|格式|版式|分栏")
_BODY_SHORTHAND = re.compile(r"^一律横排[，,]通栏")
_LATIN_SHORTHAND = re.compile(r"字母[、和与,，]?数字全部使用", re.IGNORECASE)
_TOC_DEPTH = re.compile(r"目录(?:中的标题)?(?:不能超过|最多|不超过)([一二三四1-4])级")
_TABLE_SHORTHAND = re.compile(r"表格使用三线表")
_FIGURE_CAPTION = re.compile(r"^图\s*\d+(?:\.\d+)?[^（(]*[（(]([^）)]*)[）)]")
_CONDITIONAL = re.compile(r"如果|若|仅在|纸质版|电子版|系统上传|打印版")
_ALTERNATIVE = re.compile(r"或者|或|[／/～~]")


@dataclass(frozen=True, slots=True)
class _Item:
    evidence: EvidenceReference
    role: str
    property_id: str
    original: str
    value: Any | None
    unit: str | None = None
    character_scope: str = "all"
    problem: str | None = None
    issue_status: str | None = None


class AcademicCommonFormatExtractor:
    """Project literal, source-backed academic properties from Requirement IR evidence."""

    def extract(self, ir: RequirementIR) -> AcademicFormatRuleSet:
        if ir.domain_pack.id != "academic_paper":
            raise ValueError("Common academic extraction requires academic_paper IR.")
        sources = {source.source_id: source for source in ir.source_manifest}
        items: list[_Item] = []
        for evidence in ir.evidence_index.values():
            source = sources[evidence.source_id]
            if (evidence.match_status != EvidenceMatchStatus.EXACT
                    or source.extraction_status != "complete"
                    or evidence.locator.section_path[:1] in (["header"], ["footer"])):
                continue
            extracted = self._parse_evidence(evidence)
            if _CONDITIONAL.search(evidence.quote):
                extracted = [replace(
                    item, value=None, issue_status="pending_condition",
                    problem="格式取值依赖提交场景，尚未判断当前论文适用条件。",
                ) for item in extracted]
            items.extend(extracted)

        rules: list[AcademicFormatRule] = []
        issues: list[AcademicFormatIssue] = []
        for index, item in enumerate(items):
            source_requirement_id = self._id(
                "reqfmt", ir.artifact_id, item.evidence.evidence_id,
                item.role, item.property_id, str(index),
            )
            if item.problem is not None or item.value is None:
                reason = item.problem or f"{item.role} 的 {item.property_id} 未给出具体值。"
                issues.append(AcademicFormatIssue(
                    source_requirement_id=source_requirement_id,
                    status=(item.issue_status or (
                        "ambiguous_target" if item.property_id == "target.classification"
                        else "unsupported" if item.property_id == "unclassified.format_property"
                        else "needs_value"
                    )),
                    reason=reason,
                    next_action="核对 Brief 原文并补充明确取值或对象范围。",
                    evidence_ids=[item.evidence.evidence_id],
                    target=AcademicTarget(
                        object_kind=self._object_kind(item.role, item.property_id),
                        semantic_role=item.role, selector="semantic_role",
                    ),
                    property_id=item.property_id,
                    original_text=item.original,
                ))
                continue
            target = AcademicTarget(
                object_kind=self._object_kind(item.role, item.property_id),
                semantic_role=item.role, selector="semantic_role",
            )
            scope = "document" if item.role == "page" else "same_kind"
            rules.append(AcademicFormatRule(
                rule_id=self._id("fmt", source_requirement_id),
                source_requirement_id=source_requirement_id,
                source_kind="brief_explicit",
                source_artifact_id=ir.artifact_id,
                source_version=f"{ir.artifact_id}:v{ir.artifact_version}",
                evidence_refs=[item.evidence], target=target,
                property_id=item.property_id,
                value=AcademicValue(
                    original_text=item.original, normalized=item.value,
                    unit=item.unit, dictionary_version=_VERSION,
                ),
                character_scope=item.character_scope,
                requested_scope=scope, effective_scope=scope,
                status="verified",
                reason="字面格式值及其原文证据已通过确定性校验。",
            ))

        deduplicated: dict[tuple[str, str, str, str], AcademicFormatRule] = {}
        for rule in rules:
            key = (rule.target.semantic_role, rule.property_id,
                   rule.character_scope,
                   json.dumps(rule.value.normalized, sort_keys=True))
            previous = deduplicated.get(key)
            if previous is None:
                deduplicated[key] = rule
            else:
                refs = {ref.evidence_id: ref for ref in previous.evidence_refs}
                refs.update({ref.evidence_id: ref for ref in rule.evidence_refs})
                deduplicated[key] = previous.model_copy(update={
                    "evidence_refs": list(refs.values()),
                })
        rules = list(deduplicated.values())

        # Equal requirements may be repeated; incompatible values for the same
        # target/property are retained but never passed as verified operations.
        by_property: dict[tuple[str, str, str], list[int]] = {}
        for index, rule in enumerate(rules):
            key = (rule.target.semantic_role, rule.property_id, rule.character_scope)
            by_property.setdefault(key, []).append(index)
        for indexes in by_property.values():
            values = {json.dumps(rules[i].value.normalized, sort_keys=True) for i in indexes}
            if len(values) > 1:
                for index in indexes:
                    rules[index] = rules[index].model_copy(update={
                        "status": "pending_conflict",
                        "reason": "同一目标和属性存在不兼容的 Brief 明文取值。",
                    })
        return AcademicFormatRuleSet(
            source_artifact_id=ir.artifact_id,
            source_artifact_version=ir.artifact_version,
            domain_pack=ir.domain_pack,
            rules=rules, issues=issues,
        )

    @staticmethod
    def _id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
        return f"{prefix}_{digest}"

    @staticmethod
    def _object_kind(role: str, property_id: str) -> str:
        if (role == "page" or property_id.startswith(("page.", "section."))):
            return "section"
        if property_id.startswith("page_number."):
            return "field"
        if role == "table":
            return "table"
        if role in {"table_header", "table_body"}:
            return "table_cell"
        if role in {"latin_text", "latin_digits"}:
            return "run"
        if role == "toc":
            return "field"
        return "paragraph"

    def _parse_evidence(self, evidence: EvidenceReference) -> list[_Item]:
        text = evidence.quote.strip()
        match = _TARGET.match(text)
        if _EXAMPLE.search(text):
            return []
        depth = _TOC_DEPTH.search(text)
        if depth is not None:
            return [_Item(evidence, "toc", "toc.max_depth", depth.group(),
                          _LEVEL[depth.group(1)])]
        if match is not None:
            label = match.group(1)
            role = self._role(label)
            if (role.startswith("heading_") and evidence.locator.section_path
                    and re.sub(r"\s+", "", evidence.locator.section_path[-1]) == "目录"):
                role = "toc_" + role
            rest = text[match.end():].lstrip("：: ，,\t")
            directive = bool(text[match.end():].startswith(("：", ":"))
                             or _MODAL.search(text)
                             or text[match.end():].lstrip().startswith("用"))
        elif _BODY_SHORTHAND.match(text):
            role, rest, directive = "body", text, True
        elif _LATIN_SHORTHAND.search(text):
            role, rest, directive = "latin_digits", text, True
        elif _TABLE_SHORTHAND.search(text):
            role, rest, directive = "table", text[_TABLE_SHORTHAND.search(text).start():], True
        elif (figure := _FIGURE_CAPTION.match(text)) is not None:
            role, rest, directive = "figure_caption", figure.group(1), True
        elif ("（" in text and "）" in text
              and evidence.locator.section_path
              and evidence.locator.section_path[-1] == text
              and 1 <= len(evidence.locator.section_path) <= 4):
            compact = re.sub(r"\s+", "", text.split("（", 1)[0])
            role = ("bibliography" if compact == "参考文献"
                    else "acknowledgements" if compact == "致谢"
                    else f"heading_{len(evidence.locator.section_path)}")
            rest = text.split("（", 1)[1].rsplit("）", 1)[0]
            directive = True
        else:
            return []
        if not rest:
            return []
        items: list[_Item] = []
        for token in re.split(r"[，,；;、]", rest):
            token = token.strip(" 。.\t")
            if not token:
                continue
            token_role, token = self._token_role(role, token)
            if token_role is None:
                items.append(_Item(evidence, role, "target.classification", token,
                                   None, problem="标题级别或作用对象表述不明确。"))
                continue
            items.extend(self._parse_token(evidence, token_role, token, directive))
        return items

    @staticmethod
    def _role(label: str) -> str:
        headings = {"一级标题": "heading_1", "二级标题": "heading_2",
                    "三级标题": "heading_3", "四级标题": "heading_4"}
        if label in headings:
            return headings[label]
        return {
            "目录": "toc", "正文段落": "body", "正文": "body",
            "摘要": "abstract", "关键词": "keywords", "图示": "figure_text",
            "图题": "figure_caption", "图注": "figure_caption", "表格": "table",
            "参考文献": "bibliography", "英文字母": "latin_text",
            "英文字符": "latin_text", "英数字": "latin_text",
            "字母数字": "latin_text", "页面": "page", "纸张": "page",
            "页码": "page_number",
        }[label]

    @staticmethod
    def _token_role(role: str, token: str) -> tuple[str | None, str]:
        if role == "toc":
            heading = _HEADING.search(token)
            if heading:
                return f"toc_heading_{_LEVEL[heading.group(1)]}", token[heading.end():]
            if "号标题" in token:
                return None, token
        if role == "table":
            if token.startswith("表头"):
                return "table_header", token[2:]
            if token.startswith("内容"):
                return "table_body", token[2:]
        return role, token

    def _parse_token(self, evidence: EvidenceReference, role: str,
                     token: str, directive: bool) -> list[_Item]:
        result: list[_Item] = []
        char_scope = ("latin_digits" if role == "latin_digits" else
                      "latin" if role == "latin_text" else "all")

        def add(prop: str, original: str, value: Any | None,
                unit: str | None = None, problem: str | None = None) -> None:
            result.append(_Item(evidence, role, prop, original, value,
                                unit, char_scope, problem))

        alignments = {_ALIGNMENT[m.group()] for m in _ALIGN_RE.finditer(token)}
        if alignments or "位置" in token or "对齐" in token:
            property_id = ("document.position" if role == "bibliography"
                           and not alignments else "paragraph.alignment")
            if (len(alignments) == 1 and directive
                    and not _NEGATIVE.search(token)
                    and not _ALTERNATIVE.search(token)):
                match = _ALIGN_RE.search(token)
                assert match is not None
                add(property_id, match.group(), next(iter(alignments)))
            else:
                add(property_id, token, None,
                    problem="位置或对齐要求缺少唯一、肯定的取值。")

        fonts = {m.group().casefold(): m.group() for m in _FONT.finditer(token)}
        if fonts or "字体" in token:
            if (len(fonts) == 1 and directive
                    and not _NEGATIVE.search(token)
                    and not _ALTERNATIVE.search(token)):
                value = next(iter(fonts.values()))
                add("font.family", value, value)
            else:
                add("font.family", token, None,
                    problem="字体要求未给出唯一且明确的字体名称。")

        sizes = list(_SIZE.finditer(token))
        if sizes or "字号" in token:
            parsed = []
            for match in sizes:
                raw = match.group()
                number = match.group(1)
                if number:
                    size = float(number)
                elif re.fullmatch(r"小?[1-8]号", raw):
                    chinese = "一二三四五六七八"[int(raw[-2]) - 1]
                    size = _SIZES[("小" if raw.startswith("小") else "") + chinese
                                  + ("" if raw.startswith("小") else "号")]
                else:
                    size = _SIZES[raw]
                parsed.append((raw, size))
            unique = {value for _, value in parsed}
            if (len(unique) == 1 and directive and not _NEGATIVE.search(token)
                    and not re.search(r"[～~—]|\bto\b|至|到", token)
                    and not _ALTERNATIVE.search(token)):
                add("font.size", parsed[0][0], next(iter(unique)), "pt")
            else:
                add("font.size", token, None,
                    problem="字号要求未给出唯一且明确的字号。")

        if "是否加粗" in token:
            answer = re.search(r"是否加粗\s*(?:为|是|:|：)?\s*([是否])\s*$", token)
            if answer and directive and not _ALTERNATIVE.search(token):
                add("font.bold", token, answer.group(1) == "是")
            else:
                add("font.bold", token, None, problem="是否加粗尚未给出是或否。")
        elif "加粗" in token or "粗体" in token:
            if directive and not _ALTERNATIVE.search(token):
                add("font.bold", token, not bool(re.search(r"不加粗|非粗体|取消加粗", token)))
            else:
                add("font.bold", token, None, problem="加粗表述缺少明确要求语境。")

        directions = {name for name in ("横排", "竖排") if name in token}
        if directions:
            if len(directions) == 1 and directive and not _ALTERNATIVE.search(token):
                add("section.text_direction", next(iter(directions)),
                    "horizontal" if "横排" in directions else "vertical")
            else:
                add("section.text_direction", token, None,
                    problem="文字方向存在多个取值或缺少明确要求语境。")
        columns = {name for name in ("通栏", "单栏", "双栏", "两栏", "三栏") if name in token}
        if columns:
            if len(columns) == 1 and directive and not _ALTERNATIVE.search(token):
                value = 1 if columns & {"通栏", "单栏"} else 3 if "三栏" in columns else 2
                add("section.column_count", next(iter(columns)), value)
            else:
                add("section.column_count", token, None,
                    problem="分栏要求存在多个取值或缺少明确要求语境。")

        borders = {name for name in ("三线表", "全框线", "无边框") if name in token}
        if borders or "边框样式" in token:
            if len(borders) == 1 and directive and not _ALTERNATIVE.search(token):
                name = next(iter(borders))
                add("table.border_style", name,
                    {"三线表": "three_line", "全框线": "all_borders",
                     "无边框": "none"}[name])
            else:
                add("table.border_style", token, None,
                    problem="表格边框样式未给出唯一明确的取值。")

        if role == "page" and re.search(r"A4(?:纸)?", token, re.IGNORECASE):
            if directive and not _ALTERNATIVE.search(token):
                add("page.paper_size", "A4", "A4")
            else:
                add("page.paper_size", token, None,
                    problem="纸张尺寸缺少明确要求语境。")

        if role == "page_number":
            if "阿拉伯数字" in token and "小写罗马数字" in token:
                add("page_number.number_format", token, None,
                    problem="页码格式包含多个取值，需明确对应的章节或提交条件。")
            elif "阿拉伯数字" in token:
                add("page_number.number_format", "阿拉伯数字",
                    "arabic" if directive else None,
                    problem=None if directive else "页码格式缺少明确要求语境。")
            elif "小写罗马数字" in token:
                add("page_number.number_format", "小写罗马数字",
                    "lower_roman" if directive else None,
                    problem=None if directive else "页码格式缺少明确要求语境。")

        if "图示在下" in token or "图示在上" in token:
            add("caption.position", token,
                None if _ALTERNATIVE.search(token) else
                "below" if "图示在下" in token else "above",
                problem=("图题位置包含多个取值。" if _ALTERNATIVE.search(token)
                         else None))

        margin = _MARGIN.search(token)
        if margin:
            side, amount, unit = margin.groups()
            normalized = float(amount) / 10 if unit.lower() in {"mm", "毫米"} else float(amount)
            if directive and 0 < normalized <= 10 and not _ALTERNATIVE.search(token):
                side_name = {"上": "top", "下": "bottom", "左": "left",
                             "右": "right"}.get(side, "all")
                add(f"page.margin.{side_name}", margin.group(), normalized, "cm")
            else:
                add("page.margin", token, None, problem="页边距值或范围不明确。")
        elif "页边距" in token:
            add("page.margin", token, None, problem="页边距尚未给出数值。")

        spacing = _LINE_SPACING.search(token)
        if spacing:
            value = float(spacing.group(1) or spacing.group(2))
            if directive and 0.5 <= value <= 5 and not _ALTERNATIVE.search(token):
                add("paragraph.line_spacing", spacing.group(), value, "multiple")
            else:
                add("paragraph.line_spacing", token, None, problem="行距值不明确。")
        elif "行距" in token:
            add("paragraph.line_spacing", token, None, problem="行距尚未给出数值。")

        indent = _INDENT.search(token)
        if indent:
            value = float(indent.group(1))
            unit = "characters" if indent.group(2) in {"字符", "字"} else "cm"
            if directive and 0 <= value <= 20 and not _ALTERNATIVE.search(token):
                add("paragraph.first_line_indent", indent.group(), value, unit)
            else:
                add("paragraph.first_line_indent", token, None,
                    problem="首行缩进值不明确。")
        elif "首行缩进" in token:
            add("paragraph.first_line_indent", token, None,
                problem="首行缩进尚未给出数值。")

        if not result and _FORMAT_CUE.search(token):
            add("unclassified.format_property", token, None,
                problem="当前论文格式词典尚不能安全解释这一条目。")
        return result
