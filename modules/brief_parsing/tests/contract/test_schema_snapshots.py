import json
from pathlib import Path

from jsonschema.validators import Draft202012Validator
from scripts.export_schemas import PROJECT_ROOT, SCHEMAS, export_schemas, render_schema


def test_schema_snapshots_are_current() -> None:
    assert export_schemas(check=True) == []


def test_schema_snapshots_are_valid_draft_2020_12() -> None:
    for relative_path, (model, schema_id) in SCHEMAS.items():
        committed = json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
        expected = json.loads(render_schema(model, schema_id))
        assert committed == expected
        Draft202012Validator.check_schema(committed)


def test_all_snapshot_paths_live_under_contracts() -> None:
    contracts_root = (PROJECT_ROOT / "contracts").resolve()
    for relative_path in SCHEMAS:
        assert (PROJECT_ROOT / Path(relative_path)).resolve().is_relative_to(contracts_root)
