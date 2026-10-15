"""Program-validated model Requirement -> academic formatting projection.

Model values, subjects and scopes are proposals. The literal proof compiler
must independently reproduce every accepted property, value and full scope.
Unsupported language remains visible in the source review; no fuzzy match or
default value is allowed at this boundary.
"""

from __future__ import annotations

import html
import re

from brief_parser.academic_source_policy import classify_evidence, is_excluded_candidate
from brief_parser.compilers.academic_expressions import canonical_font, normalize_expression
from brief_parser.compilers.academic_scope import analyze_rules, stable_id
from brief_parser.compilers.academic_semantic_extractor import AcademicCommonFormatExtractor as ProofExtractor
from brief_parser.domain.academic_format import AcademicCandidateReview, AcademicFormatRuleSet
from brief_parser.domain.enums import EvidenceMatchStatus, VerificationStatus, Modality, DownstreamPolicy
from brief_parser.validators.academic_decisions import ROLES, ENUMS, BOOLEANS, LENGTHS, INTEGERS, typed_property, validate_format_value
from brief_parser.errors import BriefParserError, ErrorCode


# Stable, bounded aliases for generic RequirementValue.type. New types require
# a registered typed validator and literal proof, even when listed here.
PROPERTY_ALIASES = {
    "font_family": "font.family", "font_name": "font.family", "typeface": "font.family",
    "font_size": "font.size", "font_bold": "font.bold", "bold": "font.bold",
    "font_italic": "font.italic", "italic": "font.italic",
    "paragraph_alignment": "paragraph.alignment", "alignment": "paragraph.alignment",
    "line_spacing": "paragraph.line_spacing", "first_line_indent": "paragraph.first_line_indent",
    "hanging_indent": "paragraph.hanging_indent", "left_indent": "paragraph.left_indent", "right_indent": "paragraph.right_indent",
    "spacing_before": "paragraph.spacing_before", "spacing_after": "paragraph.spacing_after",
    "paper_size": "page.paper_size", "page_orientation": "page.orientation",
    "page_margin": "page.margin.all", "page_margins": "page.margin.all",
    "toc_max_depth": "toc.max_depth", "column_count": "section.column_count",
    "table_border_style": "table.border_style", "caption_position": "caption.position",
    "page_number_format": "page_number.number_format", "page_number_start": "page_number.start",
}
REGISTERED_PROPERTIES = frozenset(ENUMS) | BOOLEANS | LENGTHS | INTEGERS | {"font.family", "font.size", "paragraph.line_spacing", "page.dimensions"}


def _property(requirement):
    declared = PROPERTY_ALIASES.get(requirement.value.type, requirement.value.type)
    declared = declared if typed_property(declared) else None
    key = requirement.semantic_key
    matches = [prop for prop in REGISTERED_PROPERTIES if key == prop or key.endswith("." + prop)]
    if len(matches) == 1:
        if declared and declared != matches[0]:
            return None
        return matches[0]
    return declared


def _value(prop, amount, unit, operator="eq"):
    if isinstance(amount, str):
        raw = amount.strip()
        if prop == "font.family":
            amount = canonical_font(raw)
        elif prop == "font.size":
            point = ProofExtractor.point_value(raw)
            if point is not None:
                amount, unit = point, "pt"
        elif prop == "paragraph.alignment":
            values = {"居中": "center", "centred": "center", "centered": "center", "两端对齐": "both", "justified": "both",
                      "左对齐": "left", "居左": "left", "右对齐": "right", "居右": "right"}
            amount = values.get(raw.casefold(), raw.casefold())
        elif prop in ENUMS:
            values = {
                "page.orientation": {"横向": "landscape", "纵向": "portrait"},
                "page.paper_size": {"a3": "A3", "a4": "A4", "a5": "A5", "letter": "Letter"},
                "page_number.number_format": {"阿拉伯数字": "arabic", "小写罗马数字": "lower_roman", "大写罗马数字": "upper_roman"},
                "section.text_direction": {"横排": "horizontal", "竖排": "vertical"},
                "table.border_style": {"三线表": "three_line", "全框线": "all_borders", "无边框": "none"},
                "caption.position": {"上方": "above", "下方": "below"},
                "document.position": {"正文后": "after_body", "正文之后": "after_body", "正文前": "before_body", "正文之前": "before_body", "文末": "document_end", "论文末尾": "document_end"},
            }
            amount = values.get(prop, {}).get(raw.casefold(), raw)
        elif prop in BOOLEANS:
            choices = {"true": True, "false": False, "是": True, "否": False}
            if prop == "font.bold":
                choices.update({"加粗": True, "粗体": True, "不加粗": False, "非粗体": False})
            if prop == "font.italic":
                choices.update({"斜体": True, "不使用斜体": False, "不斜体": False})
            amount = choices.get(raw.casefold(), raw)
        elif prop in INTEGERS and re.fullmatch(r"[0-9]+", raw):
            amount = int(raw)
        elif prop in LENGTHS:
            match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(pt|磅|cm|厘米|mm|毫米|字符|字|行)", raw, re.I)
            if match:
                amount, unit = float(match.group(1)), match.group(2).casefold()
        elif prop == "paragraph.line_spacing":
            multiple = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(?:倍(?:行距)?|multiple)", raw, re.I)
            mode = re.fullmatch(r"(?:行距)?\s*(固定值|exact|fixed|最小值|atLeast)\s*([0-9]+(?:\.[0-9]+)?)\s*(pt|磅)", raw, re.I)
            if multiple:
                amount, unit = float(multiple.group(1)), "multiple"
            elif mode:
                amount, unit = {"mode": "atLeast" if mode.group(1).casefold() in {"最小值", "atleast"} else "exact", "amount": float(mode.group(2))}, "pt"
    if prop in INTEGERS and isinstance(amount, float) and amount.is_integer():
        amount = int(amount)
    if operator == "between" and isinstance(amount, list) and len(amount) == 2:
        amount = {"min": amount[0], "max": amount[1]}
    if prop == "font.size" and operator == "between" and isinstance(amount, str):
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*[-～~至]\s*([0-9]+(?:\.[0-9]+)?)\s*(pt|磅)", amount, re.I)
        if match:
            amount, unit = {"min": float(match.group(1)), "max": float(match.group(2))}, "pt"
    if operator in {"gte", "lte"} and isinstance(amount, (int, float)) and not isinstance(amount, bool):
        amount = {"min" if operator == "gte" else "max": amount}
    unit = {"磅": "pt", "points": "pt", "point": "pt", "厘米": "cm", "毫米": "mm", "倍": "multiple", "行": "lines", "字符": "characters", "字": "characters"}.get(unit, unit)
    if isinstance(amount, (int, float)) and not isinstance(amount, bool) and unit == "mm":
        amount, unit = amount / 10, "cm"
    return amount, unit


class AcademicRequirementProjector:
    def extract(self, ir):
        if len(ir.requirements) > 1024:
            raise BriefParserError(ErrorCode.SOURCE_PARSER_RESOURCE_LIMIT, "模型格式候选超出当前验证上限；本次没有发布部分结果。")
        literal = ProofExtractor().extract(ir)
        decisions = {item.evidence_id: item for item in classify_evidence(ir.evidence_index.values())}
        sources = {item.source_id: item for item in ir.source_manifest}
        rules = list(literal.rules)
        reviews = []
        replaced = {}
        for requirement in sorted(ir.requirements, key=lambda item: item.id):
            proposal_fields = (requirement.semantic_key, requirement.value.type, requirement.label, requirement.subject)
            if any(is_excluded_candidate(field) for field in proposal_fields):
                continue
            prop = _property(requirement)
            refs = [ir.evidence_index[key] for key in requirement.evidence_refs]
            matches = []
            reason_code, reason, status = self._problem(requirement, refs, sources, decisions, prop)
            if reason_code is None:
                value, unit = _value(prop, requirement.value.amount, requirement.value.unit, requirement.operator.value)
                try:
                    # Non-equality values use the proof compiler's constraint
                    # representation, and are never promoted to executable eq.
                    if requirement.operator.value in {"eq", "neq"}:
                        validate_format_value(prop, value, unit)
                    else:
                        keys = {"gte": {"min"}, "lte": {"max"}, "between": {"min", "max"}}[requirement.operator.value]
                        if not isinstance(value, dict) or set(value) != keys:
                            raise ValueError("约束必须有明确的类型化边界。")
                        for boundary in value.values():
                            validate_format_value(prop, boundary, unit)
                except ValueError:
                    reason_code, reason, status = "invalid_typed_value", "候选值或单位不符合该属性的类型。", "rejected"
                else:
                    operator = "ne" if requirement.operator.value == "neq" else requirement.operator.value
                    for proof in literal.rules:
                        if proof.property_id != prop or proof.target.semantic_role != requirement.subject:
                            continue
                        if not set(requirement.evidence_refs) & {ref.evidence_id for ref in proof.evidence_refs}:
                            continue
                        if proof.semantics.constraint.operator != operator or proof.value.unit != unit:
                            continue
                        proven = proof.value.normalized
                        if prop == "font.family":
                            proven = canonical_font(proven)
                        # Python's numeric equality must not allow True == 1.
                        if isinstance(value, bool) != isinstance(proven, bool) or value != proven:
                            continue
                        if requirement.condition is not None:
                            condition = proof.semantics.condition
                            if not condition or normalize_expression(requirement.condition.expression) != normalize_expression(condition.original_text):
                                continue
                        matches.append(proof)
                    if len(matches) != 1:
                        reason_code, reason, status = (
                            "ambiguous_proof" if matches else "value_scope_evidence_mismatch",
                            "未能由同一条原文唯一证明候选的对象、属性、值、单位和条件；不使用模型推断补值。", "pending",
                        )
                    else:
                        proof = matches[0]
                        # The full proven scope wins over an incomplete model
                        # proposal, preserving chapter/script/condition filters.
                        if proof.rule_id in replaced:
                            linked_id, status = replaced[proof.rule_id], "covered"
                        else:
                            linked_id, status = stable_id("fmtmodel", ir.artifact_id, requirement.id), "accepted"
                            linked = proof.model_copy(update={
                                "rule_id": linked_id, "source_requirement_id": requirement.id,
                                "reason": "模型候选已通过原文属性、值、单位与完整作用范围的独立程序校验。",
                            })
                            rules[rules.index(proof)] = linked
                            replaced[proof.rule_id] = linked_id
                        reason_code, reason = "exact_program_proof", "候选与程序从原文取得的类型化规则一致；完整范围与证据已保留。"
            reviews.append(AcademicCandidateReview(
                source_requirement_id=requirement.id, status=status, reason_code=reason_code, reason=reason,
                evidence_ids=list(requirement.evidence_refs), property_id=prop,
                rule_ids=[replaced[matches[0].rule_id]] if status in {"accepted", "covered"} else [],
            ))
        relations, conflicts, fragments = analyze_rules(rules)
        return AcademicFormatRuleSet(
            schema_version="academic-format-rule-set/1.5", compiler_version="1.5.0",
            source_artifact_id=ir.artifact_id, source_artifact_version=ir.artifact_version, domain_pack=ir.domain_pack,
            rules=rules, issues=literal.issues, relations=relations, conflicts=conflicts, fragments=fragments,
            candidate_reviews=reviews,
        )

    @staticmethod
    def _problem(requirement, refs, sources, decisions, prop):
        if requirement.origin != "source" or any(decisions[ref.evidence_id].source_class != "explicit_requirement" for ref in refs):
            return "source_not_explicit", "候选证据属于示例、观察、背景、范围外或来源不明，不能提升为明文规则。", "rejected"
        if (requirement.verification_status != VerificationStatus.VERIFIED
                or any(ref.match_status != EvidenceMatchStatus.EXACT or sources[ref.source_id].extraction_status != "complete" for ref in refs)):
            return "evidence_not_verified", "候选或原文证据未通过验证，或来源未完整读取。", "pending"
        if prop is None:
            return "unsupported_property", "模型候选没有唯一且已注册的格式属性映射。", "rejected"
        if requirement.subject not in ROLES or requirement.scope.applies_to not in ([], [requirement.subject]) or requirement.scope.excludes:
            return "unsupported_model_scope", "模型对象或范围不明确；不能丢弃额外对象或排除条件。", "pending"
        if requirement.modality != Modality.MUST or requirement.downstream_policy != DownstreamPolicy.ENFORCE:
            return "non_mandatory_candidate", "候选不是明确的强制要求；建议不作为自动执行依据。", "pending"
        if requirement.operator.value not in {"eq", "neq", "gte", "lte", "between"}:
            return "unsupported_operator", "候选比较方式尚未得到类型化语义支持。", "pending"
        return None, None, None


def render_candidate_review(ruleset):
    lines = ["## 模型候选转换检查", "", "仅原文可独立证明的候选进入类型化规则；此处状态不代表论文已经修改。", ""]
    for item in ruleset.candidate_reviews:
        label = html.escape(item.source_requirement_id).replace("_", "\\_")
        lines.append(f"- {label}：{item.status} / {item.reason_code}。{item.reason}")
    return "\n".join(lines) + "\n"
