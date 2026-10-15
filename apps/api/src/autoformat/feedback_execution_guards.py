"""Cheap source identities checked while the publication transaction is held."""
from .feedback_contracts import content_hash, FeedbackRecord
import json


def check_feedback_inputs(connection, snapshot):
    for analysis in snapshot.inputs:
        parsed = analysis.interpretation
        record = connection.execute("SELECT * FROM feedback_submissions WHERE feedback_id=?", (parsed.feedback_id,)).fetchone()
        if (record is None or record["task_id"] != snapshot.task_id or record["base_version_id"] != snapshot.base_version_id or
                record["version_context_id"] != snapshot.version_context_id or
                content_hash(json.loads(record["payload_json"])) != record["payload_sha256"]):
            raise ValueError("Feedback source changed.")
        source = FeedbackRecord.model_validate_json(record["payload_json"])
        if (source.feedback_id != parsed.feedback_id or source.source_submission_sha256 != parsed.source_submission_sha256 or
                source.submission.task_id != snapshot.task_id or source.submission.base_version_id != snapshot.base_version_id):
            raise ValueError("Feedback source binding changed.")
        count = connection.execute("SELECT COUNT(*) FROM feedback_processing_decisions WHERE feedback_id=?", (parsed.feedback_id,)).fetchone()[0]
        choice = connection.execute("SELECT result_resolution_id FROM selection_target_decisions WHERE feedback_id=?", (parsed.feedback_id,)).fetchone()
        if count != analysis.decision_count or choice and (analysis.selection is None or analysis.selection.resolution_id != choice[0]):
            raise ValueError("Feedback choice changed.")
