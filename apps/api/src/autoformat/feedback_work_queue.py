"""Rebuild actionable feedback states from immutable sources and execution receipts."""
from .feedback_contracts import seal_contract
from .feedback_store import FeedbackError
from .version_store import VersionStoreError
from .workspace_contracts import FeedbackWorkItem, FeedbackWorkQueue


class FeedbackWorkQueues:
    def __init__(self, rules, executor):
        self.rules, self.executor = rules, executor
        self.feedback, self.versions = rules.feedback, rules.versions

    def get(self, task_id, version_id, *, before=None):
        context = self.feedback.context(task_id, version_id)
        with self.versions._transaction() as connection:
            rows = connection.execute("SELECT rowid AS cursor_id,* FROM feedback_submissions WHERE task_id=? AND base_version_id=? AND (? IS NULL OR rowid<?) ORDER BY rowid DESC LIMIT 51",
                (task_id, version_id, before, before)).fetchall()
            jobs = connection.execute("SELECT request_id,snapshot_id FROM feedback_executions WHERE task_id=? AND base_version_id=? ORDER BY rowid DESC", (task_id, version_id)).fetchall()
            restart = connection.execute("SELECT COALESCE(MAX(sequence),0) FROM feedback_rules_events WHERE task_id=? AND base_version_id=? AND kind='restart'", (task_id, version_id)).fetchone()[0]
        head = self.rules.load(task_id, version_id)
        cache = {head.snapshot_id: head} if head else {}
        executions = []
        for job in jobs:
            result = self.executor.get(task_id, job["request_id"])
            if job["snapshot_id"] not in cache:
                cache[job["snapshot_id"]] = self.rules.load(task_id, version_id, job["snapshot_id"])
            executions.append((result, cache[job["snapshot_id"]]))
        items = []
        for row in rows[:50]:
            record = self.feedback._record(row)
            self.feedback._check_binding(record.submission, context)
            status, reason, request_id, output = "blocked", "请查看反馈并核对实际范围。", None, None
            try:
                analysis = self.rules.processor._fresh(task_id, version_id, record.feedback_id)[-1]
                matched = next((job for job, snapshot in executions if analysis in snapshot.inputs and
                    (not head or analysis not in head.inputs or snapshot.revision >= restart)), None)
                if matched:
                    status = {"ready": "completed", "failed": "failed", "no_document_change": "no_document_change"}.get(matched.phase, "executing")
                    reason, request_id, output = matched.reason, matched.request_id, matched.version_id
                else:
                    parsed = analysis.interpretation
                    if parsed.kind in {"question", "out_of_scope"}:
                        status, reason = parsed.kind, parsed.reason
                    elif parsed.kind == "execution_defect":
                        status, reason = "blocked", "已关联原规则的执行问题，请查看依据并核对实际格式。"
                    elif analysis.selection is not None and analysis.selection.status != "ready":
                        status, reason = "needs_target", analysis.selection.reason
                    elif parsed.kind != "new_rule":
                        status, reason = ("needs_value" if set(parsed.missing_fields) <= {"value", "property_id"} else "blocked"), parsed.reason
                    elif any(r.requires_confirmation and r.review_id not in analysis.confirmed_review_ids for r in parsed.scope_reviews):
                        status, reason = "needs_scope", "请确认已展示的实际修改范围。"
                    elif head and analysis in head.inputs:
                        if any(c.feedback_id == record.feedback_id and c.resolution is None for c in head.conflicts):
                            status, reason = "needs_conflict", "请在相交规则之间明确选择，或设置本处例外。"
                        elif any(c.feedback_id == record.feedback_id and c.resolution == "keep_rule" for c in head.conflicts) and not any(
                                f.status != "superseded" and any(r.rule_id == f.rule_id and r.feedback_id == record.feedback_id for r in head.rules) for f in head.fragments):
                            status, reason = "rule_kept", "已按明确选择保留原规则，该反馈不再要求修改。"
                        elif head.status == "ready":
                            status, reason = "ready", "规则已核对，可以生成新版本。"
                        elif head.status == "no_rule_change":
                            status, reason = "blocked", "该反馈未形成新的有效规则，原规则保留。"
                        else:
                            status, reason = "blocked", head.reason
                    else:
                        status, reason = "ready", "需求已完整解析，继续核对规则后可生成新版本。"
            except (FeedbackError, VersionStoreError) as error:
                status, reason = "invalid", "反馈来源或确认记录无法校验，请重新查看该版本。"
            items.append(FeedbackWorkItem(feedback_id=record.feedback_id, created_at=record.created_at,
                raw_text=record.submission.raw_text, requested_scope=record.submission.requested_scope,
                selected_text=record.submission.selection.selected_text if record.submission.selection else None,
                status=status, reason=reason, execution_request_id=request_id, output_version_id=output))
        if self.feedback.context(task_id, version_id) != context or self.rules._head(task_id, version_id) != (head.snapshot_id if head else None):
            raise FeedbackError("stale_preview", "读取问题期间版本依据或规则核对头发生变化，请刷新。")
        return seal_contract(FeedbackWorkQueue, dict(schema_version="feedback-work-queue/1.0", task_id=task_id,
            base_version_id=version_id, base_docx_sha256=context.base_docx_sha256, version_context_id=context.context_id,
            working_version_id=self.versions.working_version_id(task_id), rules_snapshot_id=head.snapshot_id if head else None,
            items=items, next_before=rows[49]["cursor_id"] if len(rows) > 50 else None), "queue_id")
