"""Review source authority and property-level gaps independently of model recall."""

from __future__ import annotations

import hashlib
import html
from collections import Counter

from brief_parser.academic_source_policy import classify_evidence, format_properties
from brief_parser.domain.academic_format import AcademicFormatIssue, AcademicFormatRule, AcademicFormatRuleSet
from brief_parser.domain.academic_source_review import AcademicReviewItem, AcademicSourceReview, ReviewKind
from brief_parser.domain.requirement_ir import RequirementIR


_READ_WARNINGS = {
    "DOCX_MEDIA_NOT_READ": "文档图片内容未读取，无法检查其中是否还有格式说明。",
    "DOCX_EMBEDDED_OBJECTS_NOT_READ": "嵌入对象内容未读取，无法检查其中是否还有格式说明。",
    "DOCX_TEXTBOX_NOT_READ": "文本框内容未完整读取，无法检查其中是否还有格式说明。",
    "DOCX_HEADERS_FOOTERS_NOT_AUDITED": "模板页眉或页脚的实际样式未作为明文要求审计。",
    "PDF_IMAGES_NOT_READ": "PDF 图片内容未读取，无法检查其中是否还有格式说明。",
    "PDF_EMPTY_PAGES_NOT_READ": "PDF 部分页无可用文本层，无法检查其中是否还有格式说明。",
}
# Cues may describe a property family while the typed projection names a side.
_ALIASES = {"paragraph.alignment": {"paragraph.alignment", "document.position"}}


def build_source_review(ir: RequirementIR, ruleset: AcademicFormatRuleSet) -> AcademicSourceReview:
    decisions = classify_evidence(ir.evidence_index.values())
    source_by_id = {source.source_id: source for source in ir.source_manifest}
    rules_by_evidence: dict[str, list[AcademicFormatRule]] = {}
    issues_by_evidence: dict[str, list[AcademicFormatIssue]] = {}
    for rule in ruleset.rules:
        for evidence in rule.evidence_refs:
            rules_by_evidence.setdefault(evidence.evidence_id, []).append(rule)
    for issue in ruleset.issues:
        for evidence_id in issue.evidence_ids:
            issues_by_evidence.setdefault(evidence_id, []).append(issue)
    items: list[AcademicReviewItem] = []
    detected = represented = 0

    def add(kind: ReviewKind, source_id: str, ids: list[str], prop: str | None, reason: str, action: str) -> None:
        identity = "\0".join([kind, source_id, *ids, prop or "", reason])
        items.append(AcademicReviewItem(
            review_id="review_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
            kind=kind, source_id=source_id, evidence_ids=ids,
            property_id=prop, reason=reason, next_action=action,
        ))

    for decision in decisions:
        ref = ir.evidence_index[decision.evidence_id]
        if decision.source_class in {"example", "background", "out_of_scope"}:
            continue
        if decision.source_class in {"uncertain", "template_observation"}:
            if decision.format_properties:
                add("source_uncertain", ref.source_id, [ref.evidence_id], None,
                    "该片段的格式线索尚不能认定为学校明文要求。",
                    "初稿生成后核对该片段是否是适用的格式要求；模板观察值需要明确确认。")
            continue
        source = source_by_id[ref.source_id]
        if source.extraction_status != "complete" or ref.match_status.value != "exact":
            add("unread_source", ref.source_id, [ref.evidence_id], None,
                "片段来源不完整或证据未精确匹配，不能安全执行。", "补充可读取的原始格式说明。")
            continue
        for prop in decision.format_properties:
            detected += 1
            aliases = _ALIASES.get(prop, {prop})

            def matches(candidate: str | None) -> bool:
                return bool(candidate and any(candidate == alias or candidate.startswith(alias + ".") for alias in aliases))

            rules = [rule for rule in rules_by_evidence.get(ref.evidence_id, []) if matches(rule.property_id)]
            issues = [issue for issue in issues_by_evidence.get(ref.evidence_id, []) if (
                matches(issue.property_id) or (
                    issue.property_id in {"unclassified.format_property", "target.classification"}
                    and prop in format_properties(issue.original_text or "")
                )
            )]
            if rules or issues:
                represented += 1
                if any(rule.status != "verified" for rule in rules) or issues:
                    unsupported = bool(issues) and all(issue.status == "unsupported" for issue in issues)
                    add("unsupported_format" if unsupported else "recognized_pending",
                        ref.source_id, [ref.evidence_id], prop,
                        "；".join(dict.fromkeys([rule.reason for rule in rules if rule.status != "verified"] + [issue.reason for issue in issues])),
                        "初稿生成后核对具体取值、适用条件或冲突；仅确认后才允许编辑。")
            else:
                add("suspected_omission", ref.source_id, [ref.evidence_id], prop,
                    f"原文包含 {prop} 格式线索，但尚无对应的类型化规则或明确待处理项。",
                    "核对原文，并补充该格式属性的解析能力；本轮不自动执行。")
    for source in ir.source_manifest:
        if source.extraction_status != "complete":
            add("unread_source", source.source_id, [], None, "来源未完整读取。", "补充可读取的原始格式说明。")
        for warning in sorted(set(source.warnings) & set(_READ_WARNINGS)):
            add("unread_source", source.source_id, [], None, _READ_WARNINGS[warning],
                "核对该来源中是否还有格式说明；必要时提供文字版说明。")
    return AcademicSourceReview(
        schema_version="academic-source-review/1.2", policy_version="academic-format-scope/1.2",
        source_artifact_id=ir.artifact_id, source_artifact_version=ir.artifact_version,
        decisions=decisions, items=items,
        classification_counts=dict(Counter(decision.source_class for decision in decisions)),
        detected_format_property_count=detected,
        represented_format_property_count=represented,
    )


def render_source_review(review: AcademicSourceReview, ir: RequirementIR) -> str:
    def escape(text: str) -> str:
        text = html.escape(text, quote=True).replace("\n", " ").replace("\r", " ")
        for token in ("\\", "`", "*", "_", "[", "]", "|", "#"):
            text = text.replace(token, "\\" + token)
        return text

    lines = ["## 来源识别与格式漏提检查", "", review.scope_note, "", review.coverage_note, "",
             "来源分类：" + "，".join(f"{key}={value}" for key, value in sorted(review.classification_counts.items())), "",
             f"已识别格式线索 {review.detected_format_property_count} 项，其中 {review.represented_format_property_count} 项已有规则或待处理项。", ""]
    for item in review.items:
        lines.append(f"- **{item.kind}**：{escape(item.reason)}")
        for evidence_id in item.evidence_ids:
            ref = ir.evidence_index[evidence_id]
            location = ref.locator.model_dump(exclude_none=True)
            lines.append(f"  - 来源 {escape(ref.source_id)}，位置 {escape(str(location))}，原文：{escape(ref.quote)}")
        lines.append("  - 后续动作：" + escape(item.next_action))
    return "\n".join(lines) + "\n"
