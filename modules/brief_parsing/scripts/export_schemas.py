"""Export deterministic JSON Schema snapshots from Pydantic source models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brief_parser.domain.bundle import ParseBundle, ParseDiagnostics  # noqa: E402
from brief_parser.domain.domain_pack import DomainPack  # noqa: E402
from brief_parser.domain.execution_brief import ExecutionBrief  # noqa: E402
from brief_parser.domain.pipeline import ParseManifest  # noqa: E402
from brief_parser.domain.requirement_ir import RequirementIR  # noqa: E402
from brief_parser.evaluation.dataset import GoldenDatasetSource  # noqa: E402
from brief_parser.evaluation.models import EvaluationReport  # noqa: E402

SCHEMAS = {
    Path("contracts/evaluation-report/evaluation-report-1.0.schema.json"): (
        EvaluationReport,
        "https://schemas.briefparser.local/evaluation-report/1.0/schema.json",
    ),
    Path("contracts/golden-dataset/golden-dataset-1.0.schema.json"): (
        GoldenDatasetSource,
        "https://schemas.briefparser.local/golden-dataset/1.0/schema.json",
    ),
    Path("contracts/parse-bundle/parse-bundle-1.0.schema.json"): (
        ParseBundle,
        "https://schemas.briefparser.local/parse-bundle/1.0/schema.json",
    ),
    Path("contracts/parse-diagnostics/parse-diagnostics-1.0.schema.json"): (
        ParseDiagnostics,
        "https://schemas.briefparser.local/parse-diagnostics/1.0/schema.json",
    ),
    Path("contracts/parse-manifest/parse-manifest-1.0.schema.json"): (
        ParseManifest,
        "https://schemas.creatorsvoice.local/parse-manifest/1.0/schema.json",
    ),
    Path("contracts/requirement-ir/requirement-ir-1.0.schema.json"): (
        RequirementIR,
        "https://schemas.creatorsvoice.local/requirement-ir/1.0/schema.json",
    ),
    Path("contracts/execution-brief/execution-brief-1.0.schema.json"): (
        ExecutionBrief,
        "https://schemas.creatorsvoice.local/execution-brief/1.0/schema.json",
    ),
    Path("contracts/domain-pack/domain-pack-1.0.schema.json"): (
        DomainPack,
        "https://schemas.creatorsvoice.local/domain-pack/1.0/schema.json",
    ),
}


def render_schema(model: type[object], schema_id: str) -> str:
    schema = model.model_json_schema(mode="validation")  # type: ignore[attr-defined]
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = schema_id
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_schemas(*, check: bool) -> list[Path]:
    stale: list[Path] = []
    for relative_path, (model, schema_id) in SCHEMAS.items():
        destination = PROJECT_ROOT / relative_path
        expected = render_schema(model, schema_id)
        current = destination.read_text(encoding="utf-8") if destination.exists() else None
        if current == expected:
            continue
        stale.append(relative_path)
        if not check:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(expected, encoding="utf-8", newline="\n")
    return stale


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when committed snapshots differ from Pydantic models.",
    )
    args = parser.parse_args()
    stale = export_schemas(check=args.check)
    if args.check and stale:
        for path in stale:
            print(f"stale schema: {path}", file=sys.stderr)
        return 1
    if not args.check:
        for path in stale:
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
