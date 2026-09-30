from __future__ import annotations

from pathlib import Path

import pytest

from brief_parser.evaluation import golden_cli
from brief_parser.evaluation.dataset import default_golden_dataset_path, load_golden_dataset
from brief_parser.evaluation.io import load_predictions


def test_plan_lists_only_selected_cases_without_loading_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("plan must not load provider configuration")

    monkeypatch.setattr(golden_cli.Settings, "from_env", forbidden)
    monkeypatch.setattr(golden_cli, "build_service", forbidden)

    exit_code = golden_cli.main(
        ["--case-id", "ad-duration-02", "--case-id", "ad-duration-01", "--plan"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines() == [
        "selected_cases=2; provider_calls=0",
        "ad-duration-01",
        "ad-duration-02",
    ]


def test_selection_rejects_unknown_or_duplicate_case_ids() -> None:
    dataset = load_golden_dataset(default_golden_dataset_path())

    with pytest.raises(ValueError, match="unknown Golden case IDs"):
        golden_cli.select_cases(dataset, case_ids=["not-a-case"], all_cases=False)
    with pytest.raises(ValueError, match="duplicate"):
        golden_cli.select_cases(
            dataset,
            case_ids=["ad-duration-01", "ad-duration-01"],
            all_cases=False,
        )


def test_full_run_requires_explicit_all_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        golden_cli.main(["--plan"])

    assert error.value.code == 2
    assert "required" in capsys.readouterr().err


def test_targeted_fake_run_writes_only_selected_predictions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BRIEF_PARSER_PROVIDER", "fake")
    monkeypatch.setenv("BRIEF_PARSER_ENV", "test")
    output = tmp_path / "selected.jsonl"

    golden_cli.main(
        [
            "--case-id",
            "ad-duration-01",
            "--case-id",
            "ad-cta-01",
            "--allow-fake",
            "--output",
            str(output),
        ]
    )

    predictions = load_predictions(output)
    assert [prediction.case_id for prediction in predictions] == [
        "ad-duration-01",
        "ad-cta-01",
    ]


def test_full_plan_counts_all_cases_without_model_calls(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert golden_cli.main(["--all", "--plan"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "selected_cases=100; provider_calls=0"
    assert len(lines) == 101
