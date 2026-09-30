import io
import json
from pathlib import Path

from brief_parser.cli.main import main


def test_cli_parses_stdin_and_writes_five_artifact_types(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    output = tmp_path / "parsed"
    monkeypatch.setenv("BRIEF_PARSER_PROVIDER", "fake")
    monkeypatch.setenv("BRIEF_PARSER_ENV", "test")
    monkeypatch.setattr("sys.stdin", io.StringIO("成片时长不得超过60秒。"))

    exit_code = main(
        [
            "parse",
            "--stdin",
            "--domain",
            "advertising_brief",
            "--task",
            "write_ad_script",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["readiness"] == "incomplete"
    assert {path.name for path in output.iterdir()} == {
        "manifest.json",
        "requirement-ir.json",
        "execution-brief.write_ad_script.json",
        "result.md",
        "diagnostics.json",
    }
    assert main(["validate-result", str(output)]) == 0

    rendered = tmp_path / "rendered.md"
    assert main(["render", str(output), "--output", str(rendered)]) == 0
    assert rendered.read_text(encoding="utf-8").startswith("# Brief Parsing Result")
