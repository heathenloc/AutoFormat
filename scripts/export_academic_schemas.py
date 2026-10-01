"""Export the current academic handoff schemas without rewriting historical snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from brief_parser.domain.academic_bundle import AcademicParseBundle
from brief_parser.domain.academic_format import AcademicFormatRuleSet


ROOT = Path(__file__).resolve().parents[1]


def write_schema(model: type[BaseModel], kind: str, version_field: str, version: str) -> None:
    schema = model.model_json_schema()
    schema["$id"] = f"https://easyformat.local/contracts/{kind}/{version}"
    property_schema = schema["properties"][version_field]
    property_schema.pop("enum")
    property_schema["const"] = f"{kind}/{version}"
    if kind == "academic-parse-bundle":
        nested = schema["$defs"]["AcademicFormatRuleSet"]["properties"]["schema_version"]
        nested.pop("enum")
        nested["const"] = "academic-format-rule-set/1.2"
    destination = ROOT / "contracts" / kind / f"{kind}-{version}.schema.json"
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    write_schema(AcademicFormatRuleSet, "academic-format-rule-set", "schema_version", "1.2")
    write_schema(AcademicParseBundle, "academic-parse-bundle", "bundle_version", "1.2")
