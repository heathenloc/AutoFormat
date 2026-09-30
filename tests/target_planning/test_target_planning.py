"""Semantic same-kind rules stop at a review boundary until body scope is known."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest
from brief_parser.domain.academic_format import (
    AcademicFormatIssue, AcademicFormatRule, AcademicFormatRuleSet,
    AcademicTarget, AcademicValue,
)
from jsonschema import Draft202012Validator

from easyformat.target_planning import (
    DotnetTargetIndexer, TargetPlanningError, build_body_alignment_review,
    validate_target_index,
)


ROOT = Path(__file__).resolve().parents[2]
INDEX_PROJECT = ROOT / "services" / "docx_engine" / "EasyFormat.DocxIndex"


@pytest.fixture(scope="module")
def indexer() -> DotnetTargetIndexer:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET 10 SDK is required for the target index integration test.")
    completed = subprocess.run(
        [dotnet, "build", str(INDEX_PROJECT), "--no-restore", "-c", "Debug"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
        encoding="utf-8", errors="replace",
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    dll = INDEX_PROJECT / "bin" / "Debug" / "net10.0" / "EasyFormat.DocxIndex.dll"
    return DotnetTargetIndexer(
        dotnet_path=Path(dotnet), index_dll=dll,
        expected_index_sha256=hashlib.sha256(dll.read_bytes()).hexdigest(),
    )


def _fixture_docx(path: Path) -> str:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr><w:r><w:t>正文候选</w:t></w:r></w:p>
      <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格内容</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      <w:p><w:pPr><w:pStyle w:val="CustomBody"/></w:pPr><w:r><w:t>自定义正文样式</w:t></w:r></w:p>
      <w:p><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>编号段落</w:t></w:r></w:p>
      <w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>隐藏文字</w:t></w:r></w:p>
    </w:body></w:document>"""
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ruleset(*, property_id: str = "paragraph.alignment") -> AcademicFormatRuleSet:
    rule = AcademicFormatRule.model_construct(
        rule_id="fmt_req_body", source_requirement_id="req_body",
        source_kind="brief_explicit", source_artifact_id="brief",
        source_version="brief:v1", evidence_refs=[],
        target=AcademicTarget(
            object_kind="paragraph", semantic_role="body", selector="semantic_role"),
        property_id=property_id,
        value=AcademicValue(
            original_text="居中", normalized="center",
            dictionary_version="academic-alignment/1.0"),
        character_scope="all", condition=None, requested_scope="same_kind",
        effective_scope="same_kind", status="verified", reason="Fixture rule.",
    )
    return AcademicFormatRuleSet.model_construct(rules=[rule], issues=[])


def test_mixed_docx_produces_review_without_executable_edits(
    tmp_path: Path, indexer: DotnetTargetIndexer,
) -> None:
    source = tmp_path / "paper.docx"
    source_hash = _fixture_docx(source)
    index = indexer.inspect(source, expected_docx_sha256=source_hash)
    schema = json.loads((ROOT / "contracts" / "docx-target-index" /
        "docx-target-index-1.0.schema.json").read_text(encoding="utf-8"))
    packaged_schema = json.loads((ROOT / "apps" / "api" / "src" / "easyformat" /
        "schemas" / "docx-target-index-1.0.schema.json").read_text(encoding="utf-8"))
    assert schema == packaged_schema
    Draft202012Validator(schema).validate(index)
    assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert [item["role_candidate"] for item in index["paragraphs"]] == [
        "body_candidate", "heading_candidate", "table_cell",
        "unclassified", "unclassified", "unclassified",
    ]
    plan = build_body_alignment_review(
        ruleset=_ruleset(), index=index,
        base_version_id="v0", expected_base_docx_sha256=source_hash,
        rules_snapshot_id="rules-v0",
    )
    plan_schema = json.loads((ROOT / "contracts" / "target-review-plan" /
        "target-review-plan-1.0.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(plan_schema).validate(plan)
    assert plan["status"] == "needs_user_input"
    assert plan["executable_operations"] == []
    review = plan["rule_reviews"][0]
    assert review["requested_scope"] == "same_kind"
    assert review["estimated_affected_count"] is None
    assert [item["disposition"] for item in review["targets"]] == [
        "needs_body_confirmation", "excluded_candidate", "excluded_candidate",
        "needs_classification", "needs_classification", "blocked_complex_content",
    ]


def test_stale_or_inconsistent_index_never_becomes_plan(
    tmp_path: Path, indexer: DotnetTargetIndexer,
) -> None:
    source = tmp_path / "paper.docx"
    source_hash = _fixture_docx(source)
    with pytest.raises(TargetPlanningError) as stale:
        indexer.inspect(source, expected_docx_sha256="0" * 64)
    assert stale.value.status == "stale_base_version"
    index = indexer.inspect(source, expected_docx_sha256=source_hash)
    with pytest.raises(TargetPlanningError) as plan_stale:
        build_body_alignment_review(
            ruleset=_ruleset(), index=index, base_version_id="v0",
            expected_base_docx_sha256="0" * 64, rules_snapshot_id="rules-v0",
        )
    assert plan_stale.value.status == "stale_base_version"
    index["paragraphs"][0]["role_evidence"] = "built_in_heading_style"
    with pytest.raises(TargetPlanningError) as invalid:
        validate_target_index(index, expected_docx_sha256=source_hash)
    assert invalid.value.status == "validation_failed"


def test_unknown_property_keeps_all_targets_unplanned(
    tmp_path: Path, indexer: DotnetTargetIndexer,
) -> None:
    source = tmp_path / "paper.docx"
    source_hash = _fixture_docx(source)
    index = indexer.inspect(source, expected_docx_sha256=source_hash)
    ruleset = _ruleset(property_id="paragraph.font")
    ruleset.issues.append(AcademicFormatIssue(
        source_requirement_id="req_uncertain", status="needs_source_classification",
        reason="Source type is unknown.", next_action="Classify source.", evidence_ids=[],
    ))
    plan = build_body_alignment_review(
        ruleset=ruleset, index=index,
        base_version_id="v0", expected_base_docx_sha256=source_hash,
        rules_snapshot_id="rules-v0",
    )
    assert plan["executable_operations"] == []
    assert plan["rule_reviews"][0]["status"] == "unsupported_property"
    assert plan["rule_reviews"][0]["targets"] == []
    assert plan["source_issues"][0]["status"] == "needs_source_classification"
