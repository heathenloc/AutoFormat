"""Read real Briefs locally and write reproducible source/gap diagnostics.

Uses the fake provider, so this exercises ingestion, deterministic rules and
source review only. It is not an AI extraction accuracy or gold evaluation.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path

from brief_parser.application.service import ParseServiceRequest
from brief_parser.bootstrap import build_service
from brief_parser.config import Settings
from brief_parser.errors import BriefParserError


ROOT = Path(__file__).resolve().parents[1]


async def review_directory(source_dir: Path, output_dir: Path) -> list[dict]:
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to((ROOT / "runtime").resolve()):
        raise ValueError("Diagnostic outputs must stay in the project's ignored runtime directory.")
    output_dir.mkdir(parents=True, exist_ok=True)
    service = build_service(Settings(environment="test", provider="fake", parser_isolation_mode="in_process"))
    rows = []
    for index, path in enumerate(sorted(source_dir.iterdir()), start=1):
        if not path.is_file() or path.suffix.lower() not in {".docx", ".doc", ".pdf", ".txt"}:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        sample_id = f"B{index:02d}"
        row = {"sample_id": sample_id, "filename": path.name, "sha256": digest,
               "mode": "fake_provider_deterministic_diagnostics"}
        try:
            bundle = await service.parse_academic(ParseServiceRequest(
                request_id=f"req_source_review_{digest[:24]}", domain_pack_id="academic_paper",
                requested_task_types=("format_academic_paper",), source_paths=(path,),
            ))
        except BriefParserError as exc:
            row.update(status="input_rejected", error_code=exc.code.value)
        else:
            review = bundle.source_review
            ruleset = bundle.format_ruleset
            layout = bundle.template_layout
            row.update(
                status="diagnostics_written", domain_pack=bundle.requirement_ir.domain_pack.model_dump(),
                rule_status_counts=dict(Counter(rule.status for rule in ruleset.rules)),
                candidate_status_counts=dict(Counter(item.status for item in ruleset.candidate_reviews)),
                bundle_version=bundle.bundle_version, ruleset_version=ruleset.schema_version,
                relation_kind_counts=dict(Counter(item.kind for item in ruleset.relations)),
                conflict_certainty_counts=dict(Counter(item.certainty for item in ruleset.conflicts)),
                fragment_status_counts=dict(Counter(item.status for item in ruleset.fragments)),
                constraint_operator_counts=dict(Counter(item.semantics.constraint.operator for item in ruleset.rules)),
                classification_counts=review.classification_counts,
                review_kind_counts=dict(Counter(item.kind for item in review.items)),
                detected_format_property_count=review.detected_format_property_count,
                represented_format_property_count=review.represented_format_property_count,
                reading_warning_codes=sorted({warning for source in bundle.requirement_ir.source_manifest for warning in source.warnings}),
                template_source_profiles=[item.model_dump(mode="json") for item in layout.source_profiles],
                template_observation_count=len(layout.observations),
                template_resolution_counts=dict(Counter(item.resolution for item in layout.observations)),
                template_group_status_counts=dict(Counter(item.status for item in layout.groups)),
                template_diagnostic_codes=sorted({item.code for item in layout.diagnostics}),
                bundle_byte_size=len(bundle.model_dump_json().encode("utf-8")),
            )
            (output_dir / f"{sample_id}.bundle.json").write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
            (output_dir / f"{sample_id}.review.md").write_text(bundle.renderings.markdown, encoding="utf-8")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Source changed during read: {path.name}")
        rows.append(row)
    (output_dir / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Brief 来源与漏提诊断", "", "仅检查读取、确定性规则和格式线索；使用 fake provider，无云端调用。样本尚无人工确认标注，以下结果不是准确率或召回率。", "",
             "| 样本 | 状态 | 类型化规则 | 范围外片段 | 复核项目 | 模板观察 |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append(f"| {row['sample_id']} | {row['status']} | {sum(row.get('rule_status_counts', {}).values())} | {row.get('classification_counts', {}).get('out_of_scope', 0)} | {sum(row.get('review_kind_counts', {}).values())} | {row.get('template_observation_count', 0)} |")
    lines += ["", "`.doc` 仍是产品不支持的输入；本轮不转换、不修改原 Brief，也不覆盖既有标注草稿。"]
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runtime" / "brief_source_review")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(review_directory(args.source_dir, args.output_dir)), ensure_ascii=False, indent=2))
