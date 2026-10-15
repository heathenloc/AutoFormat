"""Export only the new feedback contracts; preserve all older schema versions."""

from pathlib import Path
import json

from autoformat.feedback_contracts import (
    CONTRACTS, FeedbackSubmission, FeedbackVersionContext, contract_schema, seal_contract,
)
from autoformat.feedback_rules_contracts import RULE_CONTRACTS
from autoformat.feedback_execution_contracts import EXECUTION_CONTRACTS
from autoformat.workspace_contracts import WORKSPACE_CONTRACTS


ROOT = Path(__file__).resolve().parents[1]


def export() -> None:
    for version, model in (CONTRACTS | RULE_CONTRACTS | EXECUTION_CONTRACTS | WORKSPACE_CONTRACTS).items():
        kind, number = version.split("/")
        encoded = json.dumps(contract_schema(model), ensure_ascii=False, indent=2) + "\n"
        for directory in (ROOT / "contracts" / kind, ROOT / "apps/api/src/autoformat/schemas"):
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / f"{kind}-{number}.schema.json").open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
    result = json.loads((ROOT / "contracts/academic-edit-result/academic-edit-result-1.0.schema.json").read_text(encoding="utf-8"))
    result["$id"] = "https://easyformat.local/contracts/feedback-edit-result/1.0"
    result["properties"]["schema_version"]["const"] = "feedback-edit-result/1.0"
    result["properties"]["status"]["enum"] += ["needs_user_input", "pending_conflict", "ambiguous_target", "unsupported"]
    for directory in (ROOT / "contracts/feedback-edit-result", ROOT / "apps/api/src/autoformat/schemas"):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "feedback-edit-result-1.0.schema.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Only feedback-published outputs use 1.1. Keep version-node/1.0 and its
    # strict references shape unchanged for all historical/legacy outputs.
    node = json.loads((ROOT / "contracts/version-node/version-node-1.0.schema.json").read_text(encoding="utf-8"))
    node["$id"] = "https://easyformat.local/contracts/version-node/1.1"
    node["properties"]["schema_version"]["const"] = "version-node/1.1"
    node["properties"]["kind"] = {"const": "output"}
    node["$defs"]["references"]["required"].append("feedback_rules_snapshot_id")
    node["$defs"]["references"]["properties"]["feedback_rules_snapshot_id"] = {"$ref": "#/$defs/hash"}
    encoded = json.dumps(node, ensure_ascii=False, indent=2) + "\n"
    for directory in (ROOT / "contracts/version-node", ROOT / "apps/api/src/autoformat/schemas"):
        with (directory / "version-node-1.1.schema.json").open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    context = seal_contract(FeedbackVersionContext, {
        "schema_version": "feedback-version-context/1.0", "task_id": "1" * 32,
        "base_version_id": "2" * 32, "base_docx_sha256": "3" * 64,
        "preview_artifact_id": "example-preview", "preview_pdf_sha256": "4" * 64,
        "preview_metadata_sha256": "5" * 64, "renderer_id": "libreoffice",
        "renderer_version": "LibreOffice 26.8.0.3", "page_count": 1,
        "rules_snapshot_id": "6" * 64, "brief_version_id": "example-brief:v1",
    }, "context_id")
    request = FeedbackSubmission(
        schema_version="feedback-submission/1.0", request_id="7" * 32,
        task_id=context.task_id, base_version_id=context.base_version_id,
        expected_base_docx_sha256=context.base_docx_sha256, expected_context_id=context.context_id,
        preview_artifact_id=context.preview_artifact_id, expected_preview_pdf_sha256=context.preview_pdf_sha256,
        raw_text="这一段改为居中", requested_scope="selection", selection={
            "selected_text": "论文正文示例", "context_before": "", "context_after": "",
            "spans": [{"page": 1, "start_item": 0, "start_offset_utf16": 0,
                       "end_item": 0, "end_offset_utf16": 6}]},
    )
    for relative, model in (("feedback-version-context/example.json", context),
                            ("feedback-submission/example-selection.json", request)):
        with (ROOT / "contracts" / relative).open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    export()
