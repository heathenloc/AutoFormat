"""Compute actual Word units from trusted indexes, never from client target IDs."""
from __future__ import annotations

from brief_parser.compilers.academic_scope import CHARACTERS, base_scope, intersection

from .feedback_contracts import FeedbackRuleCandidate, ScopeReview, property_minimum_unit, seal_contract
from .feedback_parser import Interpretation
from .selection_indexes import AcademicScopeIndex, DocxSelectionIndex


def character_kind(character: str) -> str:
    """Same Unicode ranges as AcademicPackage.Script; no locale guessing."""
    code = ord(character)
    if any(low <= code <= high for low, high in [(0x2E80, 0xA4CF), (0xAC00, 0xD7AF), (0xF900, 0xFAFF), (0xFF00, 0xFFEF), (0x20000, 0x323AF)]): return "chinese"
    if 0x30 <= code <= 0x39: return "digits"
    if any(low <= code <= high for low, high in [(0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F), (0x1E00, 0x1EFF)]): return "latin"
    if any(low <= code <= high for low, high in [(0x590, 0x1CFF), (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF)]): return "complex_script"
    return "other"


def build_scopes(facts: Interpretation, text: DocxSelectionIndex, semantic: AcademicScopeIndex,
                 selected_ids: list[str] | None, selected_texts: dict[str, str] | None = None) -> list[ScopeReview]:
    paragraphs = {p.object_id: p for p in text.paragraphs}
    objects = {o.object_id: o for o in semantic.objects}
    reviews = []
    candidates = []
    for candidate in facts.candidates:
        scope, prop = candidate.requested_scope, candidate.property_id
        minimum = property_minimum_unit(prop)
        if minimum == "field_or_object" or minimum == "region":
            facts.missing_fields.append("unsupported_property")
            candidates.append(candidate); continue
        if selected_ids is None and scope in {"selection", "paragraph", "same_kind"}:
            facts.missing_fields.append("selection_target")
            candidates.append(candidate); continue
        selected = [objects[key] for key in selected_ids or [] if key in objects]
        if scope == "same_kind" and candidate.semantic_role is None:
            roles = {o.semantic_role for o in selected}
            if len(roles) != 1 or "unclassified" in roles:
                facts.missing_fields.append("semantic_role")
                candidates.append(candidate); continue
            role = next(iter(roles))
            applicability = intersection(base_scope(role, prop, candidate.character_scope), candidate.applicability_scope) if candidate.applicability_scope else None
            candidate = FeedbackRuleCandidate(**{**candidate.model_dump(mode="json"), "semantic_role": role,
                "applicability_scope": applicability.model_dump(mode="json") if applicability else None})
        candidates.append(candidate)
        character_axis = candidate.applicability_scope.axes.get("characters") if candidate.applicability_scope else None
        filtered_characters = character_axis is not None and (character_axis.exclude or character_axis.include is not None and set(character_axis.include) != set(CHARACTERS))
        if (candidate.character_scope != "all" or filtered_characters) and not prop.startswith("font."):
            facts.missing_fields.append("character_scope"); continue
        if minimum == "section" and scope != "document":
            facts.missing_fields.append("requested_scope"); continue
        role_scope = candidate.applicability_scope or base_scope(candidate.semantic_role or "document_text", prop, candidate.character_scope)
        def role_matches(obj):
            values = {"roles": obj.semantic_role, "object_language": obj.object_language, "regions": obj.region,
                "region_zone": obj.region_zone, "chapter": obj.chapter, "object_ordinal": obj.object_ordinal}
            for key, axis in role_scope.axes.items():
                if key in {"characters", "property_component"}: continue
                if key not in values: return False
                value = values[key]
                if value in axis.exclude or axis.include is not None and value not in axis.include: return False
            return True
        if minimum == "section":
            targets = [o for o in semantic.objects if o.kind == "section"]
            effective = "document"
        elif minimum == "table":
            if scope in {"selection", "paragraph"}:
                table_keys = {(o.section, o.object_ordinal) for o in selected if o.semantic_role.startswith("table_") and o.object_ordinal}
                targets = [o for o in semantic.objects if o.kind == "table" and (o.section, o.object_ordinal) in table_keys]
            else:
                targets = [o for o in semantic.objects if o.kind == "table"]
            effective = "same_kind" if scope in {"selection", "paragraph"} else scope
        else:
            targets = selected if scope in {"selection", "paragraph"} else [o for o in semantic.objects if o.kind == "paragraph"]
            targets = [o for o in targets if role_matches(o)]
            # A local explicit role must match every selected object. Character
            # filters may then legitimately exclude objects with no such text.
            if scope in {"selection", "paragraph"} and {o.object_id for o in targets} != set(selected_ids or []):
                facts.missing_fields.append("semantic_role"); continue
            if prop.startswith("font."):
                scripts = set(CHARACTERS if candidate.character_scope == "all" else [candidate.character_scope])
                if character_axis:
                    if character_axis.include is not None: scripts.intersection_update(character_axis.include)
                    scripts.difference_update(character_axis.exclude)
                def eligible(obj):
                    if obj.object_id not in paragraphs: return False
                    content = selected_texts.get(obj.object_id, "") if scope == "selection" and selected_texts is not None else paragraphs[obj.object_id].text
                    return any(character_kind(character) in scripts for character in content)
                targets = [o for o in targets if eligible(o)]
            effective = "paragraph" if scope == "selection" and minimum == "paragraph" else scope
        if not targets:
            facts.missing_fields.append("selection_target" if scope in {"selection", "paragraph"} else "semantic_role"); continue
        if len(targets) > 5000:
            facts.missing_fields.append("too_many_targets"); continue
        if any(o.requires_manual_targeting or o.kind == "paragraph" and (o.object_id not in paragraphs or not paragraphs[o.object_id].editable) for o in targets):
            facts.missing_fields.append("unsafe_targets"); continue
        if minimum == "table":
            members = {(o.section, o.object_ordinal) for o in targets}
            if any(not p.editable and (objects[p.object_id].section, objects[p.object_id].object_ordinal) in members
                   for p in text.paragraphs if p.object_id in objects):
                facts.missing_fields.append("unsafe_targets"); continue
        unit_label = "分节" if minimum == "section" else "表格" if minimum == "table" else "文字范围" if effective == "selection" else "段落"
        requires = effective != scope or scope in {"same_kind", "document"}
        reason = f"实际影响 {len(targets)} 个{unit_label}。" + (
            "该属性作用于所在整段，包含选区以外的文字；执行前需确认。" if scope == "selection" and minimum == "paragraph" else
            "此范围超出所选文字，执行前需确认列出的实际范围。" if requires else
            "只作用于选中的文字；尚未执行修改。" if effective == "selection" else "作用于所选段落的全部文字；尚未执行修改。")
        if candidate.character_scope != "all" or filtered_characters:
            reason += " 仅作用于范围内符合所示字符条件的文字；数量按含匹配字符的对象计算。"
        reviews.append(seal_contract(ScopeReview, dict(candidate_id=candidate.candidate_id, requested_scope=scope,
            effective_scope=effective, minimum_unit=minimum, target_ids=[o.object_id for o in targets],
            estimated_affected_count=len(targets), requires_confirmation=requires, reason=reason), "review_id"))
    facts.candidates = candidates
    if facts.missing_fields:
        facts.missing_fields = list(dict.fromkeys(facts.missing_fields))
        facts.kind = "clarification_needed"
        facts.reason = "已识别部分格式信息，但目标、值或实际作用范围仍需核对；尚未执行修改。"
    return reviews
