"""Export local home/task metadata contracts without changing older schemas."""
import json
from pathlib import Path

from autoformat.feedback_contracts import contract_schema
from autoformat.task_catalog import TASK_CONTRACTS


ROOT = Path(__file__).resolve().parents[1]


def export():
    for version, model in TASK_CONTRACTS.items():
        kind, number = version.split("/")
        encoded = json.dumps(contract_schema(model), ensure_ascii=False, indent=2) + "\n"
        for directory in (ROOT / "contracts" / kind, ROOT / "apps/api/src/autoformat/schemas"):
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / f"{kind}-{number}.schema.json").open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)


if __name__ == "__main__": export()
