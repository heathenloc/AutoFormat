"""Export the host review contracts without changing historical schemas."""
from pathlib import Path
import json

from autoformat.initial_review import InitialDraftRequest, InitialReview

ROOT = Path(__file__).resolve().parents[1]
for name, model in (("initial-draft-request", InitialDraftRequest), ("initial-review", InitialReview)):
    directory = ROOT / "contracts" / name
    directory.mkdir(exist_ok=True)
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://easyformat.local/contracts/{name}/1.0"
    (directory / f"{name}-1.0.schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
