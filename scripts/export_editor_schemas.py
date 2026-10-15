"""Export the .NET editor boundary without changing parser/historical contracts."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
snapshot = json.loads((ROOT / "contracts/academic-decision-snapshot/academic-decision-snapshot-1.0.schema.json").read_text(encoding="utf-8"))
definitions = snapshot["$defs"]
string = {"type": "string", "minLength": 1}
hash_schema = {"type": "string", "pattern": "^[a-f0-9]{64}$"}


def record(properties):
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


manifest = record({
    "schema_version": {"const": "academic-edit-manifest/1.0"}, "base_version_id": string,
    "base_docx_sha256": hash_schema, "rules_snapshot_id": hash_schema,
    "input_file": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.docx$"},
    "output_file": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.docx$"},
    "rules": {"type": "array", "maxItems": 512, "items": {"$ref": "#/$defs/AcademicEffectiveRule"}},
    "fragments": {"type": "array", "maxItems": 20000, "items": {"$ref": "#/$defs/AcademicRuleFragment"}},
})
manifest["$defs"] = definitions
operation = record({
    "operation_id": string, "rule_id": string, "fragment_id": string, "object_id": string,
    "part": string, "xml_path": string, "property_id": string,
    "component": {"type": ["string", "null"]}, "character_type": {"type": ["string", "null"]},
    "before": {}, "after": {}, "effective_scope": {"enum": ["run", "paragraph", "section", "table"]},
    "status": {"enum": ["planned", "already_satisfied", "modified_verified", "pending_manual_check"]}, "changed": {"type": "boolean"}, "reason": string,
})
result = record({
    "schema_version": {"const": "academic-edit-result/1.0"},
    "status": {"enum": ["planned", "ready", "already_satisfied", "validation_failed", "stale_base_version", "output_exists"]},
    "base_docx_sha256": hash_schema, "rules_snapshot_id": hash_schema,
    "output_docx_sha256": {"anyOf": [hash_schema, {"type": "null"}]},
    "operations": {"type": "array", "maxItems": 200000, "items": operation},
    "rules": {"type": "array", "maxItems": 512, "items": record({
        "rule_id": string, "status": {"enum": ["planned", "modified_verified", "already_satisfied", "pending_manual_check", "no_target", "ambiguous_target", "pending_condition", "pending_conflict", "check_only", "unsupported", "needs_user_input"]},
        "target_count": {"type": "integer", "minimum": 0}, "reason": string,
    })},
    "content_preserved": {"type": "boolean"}, "package_validated": {"type": "boolean"},
    "field_refresh_status": {"enum": ["not_run", "not_required", "pending_manual_check"]}, "reason": string,
})
for name, schema in (("academic-edit-manifest", manifest), ("academic-edit-result", result)):
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://easyformat.local/contracts/{name}/1.0"
    encoded = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    for directory in (ROOT / "contracts" / name, ROOT / "apps/api/src/autoformat/schemas"):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}-1.0.schema.json").write_text(encoded, encoding="utf-8")
