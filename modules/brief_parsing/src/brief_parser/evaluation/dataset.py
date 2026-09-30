"""Load compact, versioned Golden Dataset templates into concrete cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, ValidationError, model_validator

from brief_parser.domain.base import Identifier, StrictModel
from brief_parser.evaluation.models import GoldenAnnotations, GoldenCase, GoldenDataset


class GoldenDatasetTemplate(StrictModel):
    template_id: Identifier
    category: Literal["advertising", "edge", "general"]
    repeat: int = Field(gt=0)
    locale: str = "zh-CN"
    domain_pack_id: Identifier
    domain_pack_version: str
    requested_task_types: list[Identifier] = Field(min_length=1)
    source_template: str = Field(min_length=1)
    annotations: GoldenAnnotations


class GoldenDatasetSource(StrictModel):
    dataset_version: Literal["golden-dataset/1.0"]
    provenance: Literal["synthetic", "public_license", "deidentified"]
    expected_counts: dict[Literal["advertising", "edge", "general"], int]
    templates: list[GoldenDatasetTemplate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_templates(self) -> Self:
        ids = [template.template_id for template in self.templates]
        if len(ids) != len(set(ids)):
            raise ValueError("golden template ids must be unique")
        if any(count < 0 for count in self.expected_counts.values()):
            raise ValueError("expected category counts cannot be negative")
        return self


class GoldenDatasetError(ValueError):
    """The checked-in Golden Dataset is malformed or incomplete."""


def default_golden_dataset_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    project_dataset = project_root / "evals" / "golden" / "v1" / "dataset.json"
    if project_dataset.is_file():
        return project_dataset
    installed_dataset = (
        Path(__file__).resolve().parents[1]
        / "evaluation_data"
        / "golden"
        / "v1"
        / "dataset.json"
    )
    if installed_dataset.is_file():
        return installed_dataset
    raise GoldenDatasetError("packaged Golden Dataset is unavailable")


def load_golden_dataset(
    path: Path,
    *,
    expected_total: int | None = 100,
) -> GoldenDataset:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = GoldenDatasetSource.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise GoldenDatasetError(f"cannot load Golden Dataset: {path}") from exc

    cases: list[GoldenCase] = []
    counts = {"advertising": 0, "edge": 0, "general": 0}
    for template in source.templates:
        for ordinal in range(1, template.repeat + 1):
            token = f"{ordinal:02d}"
            annotations = GoldenAnnotations.model_validate(
                _format_value(template.annotations.model_dump(mode="json"), token)
            )
            cases.append(
                GoldenCase(
                    case_id=f"{template.template_id}-{token}",
                    category=template.category,
                    locale=template.locale,
                    domain_pack_id=template.domain_pack_id,
                    domain_pack_version=template.domain_pack_version,
                    requested_task_types=template.requested_task_types,
                    source_text=template.source_template.format(index=token),
                    annotations=annotations,
                )
            )
            counts[template.category] += 1

    if expected_total is not None and len(cases) != expected_total:
        raise GoldenDatasetError(
            f"Golden Dataset must contain {expected_total} cases; found {len(cases)}"
        )
    expected_counts = {
        "advertising": source.expected_counts.get("advertising", 0),
        "edge": source.expected_counts.get("edge", 0),
        "general": source.expected_counts.get("general", 0),
    }
    if counts != expected_counts:
        raise GoldenDatasetError(
            f"Golden Dataset category counts differ: expected {expected_counts}, found {counts}"
        )
    return GoldenDataset(
        dataset_version=source.dataset_version,
        provenance=source.provenance,
        cases=cases,
    )


def _format_value(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.format(index=token)
    if isinstance(value, list):
        return [_format_value(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _format_value(item, token) for key, item in value.items()}
    return value
