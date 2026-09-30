"""Deterministic human-readable rendering for compiled parsing results."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from brief_parser.domain.execution_brief import (
    ExecutionBrief,
    ExecutionConstraint,
    ExecutionItem,
    ExecutionUnresolved,
)
from brief_parser.domain.requirement_ir import RequirementIR


class MarkdownResultRenderer:
    def render(
        self,
        requirement_ir: RequirementIR,
        execution_briefs: Mapping[str, ExecutionBrief],
    ) -> str:
        lines = [
            "# Brief Parsing Result",
            "",
            f"- Artifact: `{_inline(requirement_ir.artifact_id)}` "
            f"v{requirement_ir.artifact_version}",
            f"- Readiness: `{requirement_ir.readiness.value}`",
            f"- Domain Pack: `{_inline(requirement_ir.domain_pack.id)}` "
            f"v{requirement_ir.domain_pack.version}",
            f"- Locale: `{_inline(requirement_ir.locale)}`",
            "",
            "## Quality",
            "",
            f"- Clause coverage: {requirement_ir.quality.classified_clause_count}/"
            f"{requirement_ir.quality.clause_count} "
            f"({requirement_ir.quality.coverage_ratio:.1%})",
            f"- Evidence validity: {requirement_ir.quality.evidence_validity_ratio:.1%}",
            f"- Numeric validation: {requirement_ir.quality.numeric_validation_ratio:.1%}",
            f"- Conflicts: {requirement_ir.quality.conflict_count}",
            f"- Unresolved: {requirement_ir.quality.unresolved_count}",
            f"- Blockers: {requirement_ir.quality.blocker_count}",
        ]
        if requirement_ir.quality.readiness_reason_codes:
            lines.extend(
                [
                    "- Readiness reasons: "
                    + ", ".join(
                        f"`{_inline(item)}`"
                        for item in requirement_ir.quality.readiness_reason_codes
                    )
                ]
            )

        lines.extend(self._ir_summary(requirement_ir))
        for task_type, brief in sorted(execution_briefs.items()):
            lines.extend(self._execution_brief(task_type, brief))
        lines.extend(self._evidence(requirement_ir))
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _ir_summary(requirement_ir: RequirementIR) -> list[str]:
        lines = ["", "## Canonical Requirement IR", ""]
        if requirement_ir.objectives:
            lines.extend(["### Objectives", ""])
            for objective in requirement_ir.objectives:
                lines.append(
                    f"- **{_inline(objective.label)}:** {_value(objective.value)}"
                )
        if requirement_ir.requirements:
            lines.extend(["", "### Requirements", ""])
            for requirement in requirement_ir.requirements:
                lines.append(
                    f"- `{requirement.modality.value}` **{_inline(requirement.label)}** "
                    f"({_inline(requirement.category)}, "
                    f"{_inline(requirement.priority.value)}): "
                    f"{_value(requirement.value.model_dump(mode='json'))}"
                )
        if requirement_ir.conflicts:
            lines.extend(["", "### Conflicts", ""])
            for conflict in requirement_ir.conflicts:
                status = "resolved" if conflict.resolution is not None else "unresolved"
                lines.append(
                    f"- **{_inline(conflict.topic)}** "
                    f"[{conflict.severity.value}, {status}] "
                    f"`{_inline(conflict.reason_code)}`"
                )
        if requirement_ir.unresolved_items:
            lines.extend(["", "### Unresolved", ""])
            for unresolved in requirement_ir.unresolved_items:
                lines.append(
                    f"- **{_inline(unresolved.topic)}:** "
                    f"{_inline(unresolved.description)} "
                    f"(`{unresolved.downstream_policy}`)"
                )
        if requirement_ir.unclassified_content:
            lines.extend(["", "### Unclassified Content", ""])
            for unclassified in requirement_ir.unclassified_content:
                lines.append(
                    f"- {_inline(unclassified.description)} "
                    f"(`{_inline(unclassified.reason_code)}`)"
                )
        return lines

    @staticmethod
    def _execution_brief(task_type: str, brief: ExecutionBrief) -> list[str]:
        lines = [
            "",
            f"## Execution Brief: {_inline(task_type)}",
            "",
            f"- Readiness: `{brief.readiness.value}`",
        ]
        sections: tuple[
            tuple[str, Sequence[ExecutionConstraint | ExecutionItem]], ...
        ] = (
            ("Objectives", brief.objective),
            ("Deliverables", brief.deliverables),
            ("Hard Constraints", brief.hard_constraints),
            ("Prohibitions", brief.prohibitions),
            ("Preferences", brief.preferences),
            ("References", brief.references),
            ("Additional Constraints", brief.additional_constraints),
        )
        for title, items in sections:
            if not items:
                continue
            lines.extend(["", f"### {title}", ""])
            lines.extend(
                f"- **{_inline(item.label)}:** {_value(item.value)}" for item in items
            )
        if brief.facts:
            lines.extend(["", "### Facts", ""])
            lines.extend(
                f"- **{_inline(key)}:** {_value(value)}"
                for key, value in brief.facts.items()
            )
        if brief.unresolved:
            lines.extend(["", "### Execution Warnings / Blockers", ""])
            lines.extend(_render_unresolved(item) for item in brief.unresolved)
        return lines

    @staticmethod
    def _evidence(requirement_ir: RequirementIR) -> list[str]:
        if not requirement_ir.evidence_index:
            return []
        lines = ["", "## Evidence Index", ""]
        for evidence_id, evidence in sorted(requirement_ir.evidence_index.items()):
            location = []
            if evidence.locator.page is not None:
                location.append(f"page {evidence.locator.page}")
            if evidence.locator.paragraph is not None:
                location.append(f"paragraph {evidence.locator.paragraph}")
            suffix = f" ({', '.join(location)})" if location else ""
            lines.append(
                f"### `{_inline(evidence_id)}` · `{_inline(evidence.source_id)}`{suffix}"
            )
            lines.append("")
            quote = evidence.quote.replace("<", "&lt;").replace(">", "&gt;")
            lines.extend(f"> {line}" for line in quote.splitlines() or [quote])
            lines.append("")
        return lines


def _render_unresolved(item: ExecutionUnresolved) -> str:
    return (
        f"- **{_inline(item.topic)}:** {_inline(item.description)} "
        f"(`{item.downstream_policy}`)"
    )


def _value(value: object) -> str:
    return _inline(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _inline(value: str) -> str:
    escaped = " ".join(value.splitlines())
    for character in ("\\", "`", "*", "_", "[", "]", "#", "|", "<", ">"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped
