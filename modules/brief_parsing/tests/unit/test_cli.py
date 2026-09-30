import json

from brief_parser.cli.main import main


def test_version_json(capsys: object) -> None:
    assert main(["version", "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["package"] == "0.9.0"
    assert payload["golden_dataset"] == "golden-dataset/1.0"
    assert payload["evaluation_report"] == "evaluation-report/1.0"
    assert payload["parse_bundle"] == "parse-bundle/1.0"
    assert payload["parse_manifest"] == "parse-manifest/1.0"
    assert payload["requirement_ir"] == "requirement-ir/1.0"
    assert captured.err == ""
