"""UTF-8 JSONL inputs and atomic JSON report persistence."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from brief_parser.evaluation.models import EvaluationReport, PredictionRecord, PricingTable


class EvaluationInputError(ValueError):
    """Evaluation data cannot be parsed or validated."""


def load_predictions(path: Path) -> list[PredictionRecord]:
    records: list[PredictionRecord] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload: Any = json.loads(line)
                try:
                    records.append(PredictionRecord.model_validate(payload))
                except ValidationError as exc:
                    raise EvaluationInputError(
                        f"invalid prediction at line {line_number}"
                    ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationInputError(f"cannot load predictions: {path}") from exc
    return records


def load_pricing(path: Path) -> PricingTable:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PricingTable.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise EvaluationInputError(f"cannot load pricing: {path}") from exc


def write_report(report: EvaluationReport, path: Path) -> None:
    write_json_model(report, path)


def write_json_model(model: BaseModel, path: Path) -> None:
    _atomic_write_text(model.model_dump_json(indent=2) + "\n", path)


def write_predictions(records: list[PredictionRecord], path: Path) -> None:
    content = "".join(record.model_dump_json() + "\n" for record in records)
    _atomic_write_text(content, path)


def _atomic_write_text(content: str, path: Path) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.tmp-",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
