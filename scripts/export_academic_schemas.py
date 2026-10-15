"""Export the current academic handoff schemas without rewriting historical snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.academic_format import AcademicFormatRuleSet
from brief_parser.domain.academic_source_review import AcademicSourceReview
from brief_parser.domain.template_layout import TemplateLayoutReport
from brief_parser.domain.academic_decisions import (
    AcademicDecisionRequest, AcademicDecisionEvent, AcademicDecisionSnapshot, AcademicQuestionQueue, AcademicEffectiveRule,
)


ROOT = Path(__file__).resolve().parents[1]


def build_schema(model: type[BaseModel], kind: str, version_field: str, version: str) -> dict:
    schema = model.model_json_schema()
    schema["$id"] = f"https://easyformat.local/contracts/{kind}/{version}"
    property_schema = schema["properties"][version_field]
    property_schema.pop("enum", None)
    property_schema["const"] = f"{kind}/{version}"
    property_schema["default"] = f"{kind}/{version}"
    if version_field not in schema["required"]:
        schema["required"].append(version_field)
    if kind == "academic-parse-bundle":
        nested = schema["$defs"]["AcademicFormatRuleSet"]["properties"]["schema_version"]
        nested.pop("enum")
        nested["const"] = "academic-format-rule-set/1.5"
        nested["default"] = "academic-format-rule-set/1.5"
        schema["required"] += ["format_ruleset", "source_review", "template_layout"]
        for field in ("format_ruleset", "source_review", "template_layout"):
            ref = next(item for item in schema["properties"][field]["anyOf"] if "$ref" in item)
            schema["properties"][field] = ref
    if "AcademicFormatRule" in schema.get("$defs", {}):
        rule = schema["$defs"]["AcademicFormatRule"]
        rule["properties"]["schema_version"] = {"const": "academic-format-rule/1.1", "type": "string"}
        rule["required"].append("semantics")
        rule["required"].append("schema_version")
        rule["properties"]["semantics"] = {"$ref": "#/$defs/AcademicRuleSemantics"}
    ruleset = schema if kind == "academic-format-rule-set" else schema.get("$defs", {}).get("AcademicFormatRuleSet")
    if ruleset:
        ruleset["required"] += ["relations", "conflicts", "fragments", "candidate_reviews"]
        if "schema_version" not in ruleset["required"]:
            ruleset["required"].append("schema_version")
    for name, field, constant in (
        ("AcademicSourceReview", "schema_version", "academic-source-review/1.2"),
        ("AcademicSourceReview", "policy_version", "academic-format-scope/1.2"),
        ("TemplateLayoutReport", "schema_version", "academic-template-layout/1.1"),
        ("TemplateLayoutReport", "reader_version", "docx-template-layout/1.1"),
        ("AcademicFormatRuleSet", "compiler_version", "1.5.0"),
    ):
        target = schema if model.__name__ == name else schema.get("$defs", {}).get(name)
        if target:
            target["properties"][field] = {"type": "string", "const": constant}
    return schema


def write_schema(model: type[BaseModel], kind: str, version_field: str, version: str) -> None:
    schema = build_schema(model, kind, version_field, version)
    destination = ROOT / "contracts" / kind / f"{kind}-{version}.schema.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    write_schema(AcademicFormatRuleSet, "academic-format-rule-set", "schema_version", "1.5")
    write_schema(AcademicSourceReview, "academic-source-review", "schema_version", "1.2")
    write_schema(AcademicParseBundle, "academic-parse-bundle", "bundle_version", "1.6")
