"""Append-only rule reviews, conflict choices and source-replayed snapshots."""
from __future__ import annotations

import json
import threading

from .feedback_contracts import (FeedbackAnalysis, FeedbackConflict, FeedbackParseResult,
    canonical_bytes, content_hash, seal_contract)
from .feedback_rule_compiler import compile_rules
from .feedback_rules_contracts import (FeedbackRuleBasis, FeedbackRulesDecision,
    FeedbackRulesReview, FeedbackRulesReviewV2, FeedbackRulesSnapshot, FeedbackRulesSnapshotV2)
from .feedback_rebase import rebase_mapping
from .feedback_store import FeedbackError
from .feedback_validation import validate_conflict_decision
from .version_store import new_id, _utc_now
from .workspace_contracts import VersionContinuationRequest, VersionContinuation


class FeedbackRulesStore:
    def __init__(self, processor, *, basis_loader):
        self.processor, self.feedback = processor, processor.feedback
        self.versions, self.basis_loader = processor.versions, basis_loader
        self.legacy_fingerprint = content_hash({"compiler": "feedback-rules/1.1", "processing": processor.fingerprint})
        self.fingerprint = content_hash({"compiler": "feedback-rules/1.2", "processing": processor.fingerprint})
        self._lock = threading.RLock()
        with self.versions._transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_rules_snapshots (
                snapshot_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, base_version_id TEXT NOT NULL,
                revision INTEGER NOT NULL, previous_snapshot_id TEXT, payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(task_id, base_version_id, revision))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_rules_heads (
                task_id TEXT NOT NULL, base_version_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                PRIMARY KEY(task_id, base_version_id))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_rules_events (
                task_id TEXT NOT NULL, base_version_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                kind TEXT NOT NULL, decision_id TEXT, request_id TEXT, payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(task_id, base_version_id, sequence), UNIQUE(task_id, request_id))""")

    def _head(self, task_id, version_id):
        with self.versions._transaction() as connection:
            row = connection.execute("SELECT snapshot_id FROM feedback_rules_heads WHERE task_id=? AND base_version_id=?", (task_id, version_id)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _payload(row):
        try:
            value = json.loads(row["payload_json"])
            if content_hash(value) != row["payload_sha256"]: raise ValueError()
            return value
        except (ValueError, TypeError, KeyError) as error:
            raise FeedbackError("validation_failed", "反馈规则历史内容无法通过校验。") from error

    def _sources(self, task_id, version_id):
        context = self.feedback.context(task_id, version_id)
        basis = self.basis_loader(context)
        if basis is not None:
            basis = FeedbackRuleBasis.model_validate_json(basis.model_dump_json())
            if basis.academic_rules_snapshot_id != context.rules_snapshot_id:
                raise FeedbackError("validation_failed", "学术依据快照与所选版本不符。")
        text, semantic = self.processor._indexes(context)
        return context, basis, text, semantic

    def _parent(self, context):
        if not context.feedback_rules_snapshot_id: return None
        version = self.versions.get_version(context.task_id, context.base_version_id)
        with self.versions._transaction() as connection:
            parent = connection.execute("SELECT base_version_id FROM feedback_rules_snapshots WHERE task_id=? AND snapshot_id=?", (context.task_id, context.feedback_rules_snapshot_id)).fetchone()
        if parent is None or parent[0] != version.parent_version_id:
            raise FeedbackError("validation_failed", "反馈继承快照不属于所选父版本。")
        return self.load(context.task_id, parent[0], context.feedback_rules_snapshot_id)

    def _mapping(self, context, inherited):
        if inherited is None: return None
        if (inherited.academic_rules_snapshot_id != context.rules_snapshot_id or
                inherited.brief_version_id != context.brief_version_id): return None
        if self.processor.indexes is None: return None
        return rebase_mapping(self.versions, self.processor.indexes, context.task_id,
                              inherited.base_version_id, context.base_version_id)

    @staticmethod
    def _review(snapshot, feedback_id):
        analysis = next((i for i in snapshot.inputs if i.interpretation.feedback_id == feedback_id), None)
        if analysis is None: raise FeedbackError("needs_user_input", "请先核对此反馈的规则范围。")
        conflicts = [FeedbackConflict(conflict_id=c.conflict_id, candidate_id=c.candidate_id,
            existing_rule_ids=[c.existing_rule_id], property_id=next(r.property_id for r in analysis.interpretation.candidates if r.candidate_id == c.candidate_id),
            affected_target_ids=list(dict.fromkeys(s.object_id for s in c.spans)), reason=c.reason)
            for c in snapshot.conflicts if c.feedback_id == feedback_id]
        parsed = seal_contract(FeedbackParseResult, {**analysis.interpretation.model_dump(mode="json", exclude={"result_id"}),
            "conflicts": [c.model_dump(mode="json") for c in conflicts]}, "result_id")
        modern = snapshot.schema_version == "feedback-rule-snapshot/1.2"
        return seal_contract(FeedbackRulesReviewV2 if modern else FeedbackRulesReview, dict(schema_version="feedback-rules-review/1.1" if modern else "feedback-rules-review/1.0",
            parse_result=parsed, snapshot=snapshot), "review_id")

    @staticmethod
    def _replace_input(inputs, analysis):
        feedback_id = analysis.interpretation.feedback_id
        if any(i.interpretation.feedback_id == feedback_id for i in inputs):
            return [analysis if i.interpretation.feedback_id == feedback_id else i for i in inputs]
        return [*inputs, analysis]

    def _validate_choice(self, record, context, snapshot, answer):
        review = self._review(snapshot, answer.feedback_id)
        validate_conflict_decision(record, context, review.parse_result, answer,
            known_rule_ids={r.rule_id for r in snapshot.rules} | set(review.parse_result.existing_rule_ids))
        conflict = next(c for c in snapshot.conflicts if c.conflict_id == answer.conflict_id)
        if answer.expected_snapshot_id != snapshot.snapshot_id:
            raise FeedbackError("blocked_conflict", "规则快照已更新，请重新核对冲突。")
        if conflict.resolution is not None:
            raise FeedbackError("blocked_conflict", "此冲突已有决定；修改需求请保存新的反馈。")
        if answer.action not in conflict.allowed_actions:
            raise FeedbackError("needs_user_input", "此决定超出了已经确认的范围。")
        if not answer.raw_answer.strip(): raise FeedbackError("needs_user_input", "需要明确的冲突选择。")

    def load(self, task_id, version_id, snapshot_id=None):
        try:
            return self._load(task_id, version_id, snapshot_id)
        except (ValueError, TypeError, KeyError) as error:
            raise FeedbackError("validation_failed", "反馈规则快照无法通过来源重放校验。") from error

    def _load(self, task_id, version_id, snapshot_id=None):
        """Rebuild the entire immutable prefix, including historical answers."""
        snapshot_id = snapshot_id or self._head(task_id, version_id)
        if snapshot_id is None: return None
        context, basis, text, semantic = self._sources(task_id, version_id)
        with self.versions._transaction() as connection:
            target = connection.execute("SELECT * FROM feedback_rules_snapshots WHERE task_id=? AND base_version_id=? AND snapshot_id=?", (task_id, version_id, snapshot_id)).fetchone()
            if target is None: raise FeedbackError("validation_failed", "反馈规则快照不存在或属于另一版本。")
            rows = connection.execute("SELECT * FROM feedback_rules_snapshots WHERE task_id=? AND base_version_id=? AND revision<=? ORDER BY revision", (task_id, version_id, target["revision"])).fetchall()
            events = connection.execute("SELECT * FROM feedback_rules_events WHERE task_id=? AND base_version_id=? AND sequence<=? ORDER BY sequence", (task_id, version_id, target["revision"])).fetchall()
        if len(rows) != target["revision"] + 1 or len(events) != target["revision"]:
            raise FeedbackError("validation_failed", "反馈规则历史不连续。")
        inputs, decisions, raw_texts, cache, previous = [], {}, {}, {}, None
        inherited = self._parent(context)
        mapping = self._mapping(context, inherited)
        for revision, row in enumerate(rows):
            if row["revision"] != revision: raise FeedbackError("validation_failed", "规则修订序列不连续。")
            if revision:
                event = events[revision-1]
                if event["sequence"] != revision: raise FeedbackError("validation_failed", "规则事件序列不连续。")
                payload = self._payload(event)
                if event["kind"] == "review":
                    captured = FeedbackAnalysis.model_validate_json(json.dumps(payload))
                    parsed = captured.interpretation
                    if captured.analysis_id not in cache:
                        source = self.processor._fresh(task_id, version_id, parsed.feedback_id,
                            decision_limit=captured.decision_count,
                            selection_id=captured.selection.resolution_id if captured.selection else None)
                        cache[captured.analysis_id] = source
                    source = cache[captured.analysis_id]
                    if source[-1] != captured: raise FeedbackError("validation_failed", "规则输入与反馈来源重放不一致。")
                    if event["decision_id"] is not None or event["request_id"] is not None:
                        raise FeedbackError("validation_failed", "范围核对事件混入决定身份。")
                    inputs = self._replace_input(inputs, captured)
                    raw_texts[parsed.feedback_id] = source[0].submission.raw_text
                elif event["kind"] == "decision":
                    answer = FeedbackRulesDecision.model_validate_json(json.dumps(payload))
                    if (event["request_id"] != answer.request_id or not event["decision_id"] or previous is None):
                        raise FeedbackError("validation_failed", "决定事件身份与请求不一致。")
                    record = self.feedback.get(task_id, version_id, answer.feedback_id)
                    self._validate_choice(record, context, previous, answer)
                    decisions[answer.conflict_id] = (answer, event["decision_id"])
                elif event["kind"] == "restart":
                    request = VersionContinuationRequest.model_validate_json(json.dumps(payload))
                    with self.versions._transaction() as connection:
                        receipt = connection.execute("SELECT * FROM version_continuations WHERE task_id=? AND request_id=?", (task_id, request.request_id)).fetchone()
                    if receipt is None or receipt["request_json"] != canonical_bytes(payload).decode():
                        raise FeedbackError("validation_failed", "分支起点缺少对应的继续编辑回执。")
                    result = VersionContinuation.model_validate_json(receipt["result_json"])
                    if (content_hash(result.model_dump(mode="json")) != receipt["result_sha256"] or
                            (request.task_id, request.version_id, request.expected_docx_sha256) != (task_id, version_id, context.base_docx_sha256) or
                            event["request_id"] != request.request_id or event["decision_id"] is not None or
                            (result.task_id, result.request_id, result.continued_version_id, result.working_version_id,
                             result.previous_working_version_id, result.replayed) !=
                            (task_id, request.request_id, version_id, version_id, request.expected_working_version_id, False)):
                        raise FeedbackError("validation_failed", "分支继续请求与规则重置记录不一致。")
                    inputs, decisions, raw_texts = [], {}, {}
                else: raise FeedbackError("validation_failed", "未知的反馈规则事件。")
            payload = self._payload(row)
            modern = payload.get("schema_version") == "feedback-rule-snapshot/1.2"
            model = FeedbackRulesSnapshotV2 if modern else FeedbackRulesSnapshot
            stored = model.model_validate_json(json.dumps(payload))
            rebuilt = compile_rules(context, inputs, basis, text, semantic, decisions, revision=revision,
                # An engine update may change the component fingerprint while
                # reproducing every source-derived fact exactly. Preserve the
                # historical tag; equality below still verifies the full replay.
                previous_snapshot_id=previous.snapshot_id if previous else None, fingerprint=stored.engine_fingerprint,
                parent_snapshot_id=context.feedback_rules_snapshot_id, raw_texts=raw_texts, inherited=inherited,
                compiler_version="feedback-rules/1.2" if modern else "feedback-rules/1.1", inherited_mapping=mapping)
            if (stored != rebuilt or row["snapshot_id"] != rebuilt.snapshot_id or
                    row["previous_snapshot_id"] != rebuilt.previous_snapshot_id):
                raise FeedbackError("validation_failed", "规则快照与原文件、原话或决定重放不一致。")
            previous = rebuilt
        if self.feedback.context(task_id, version_id) != context:
            raise FeedbackError("stale_preview", "规则重放期间版本依据发生变化。")
        return previous

    @staticmethod
    def _save(connection, snapshot):
        payload = snapshot.model_dump(mode="json")
        encoded = canonical_bytes(payload)
        if len(encoded) > 16 * 1024 * 1024: raise FeedbackError("needs_user_input", "反馈快照超过存储上限，请拆分需求。")
        connection.execute("INSERT INTO feedback_rules_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (snapshot.snapshot_id, snapshot.task_id, snapshot.base_version_id, snapshot.revision,
             snapshot.previous_snapshot_id, encoded.decode(), content_hash(payload), _utc_now()))
        connection.execute("INSERT INTO feedback_rules_heads VALUES (?, ?, ?) ON CONFLICT(task_id,base_version_id) DO UPDATE SET snapshot_id=excluded.snapshot_id",
            (snapshot.task_id, snapshot.base_version_id, snapshot.snapshot_id))

    def _append(self, record, context, previous, snapshot, kind, payload, *, decision_id=None, request_id=None, baseline=None):
        with self.versions._transaction() as connection:
            self.processor.selections._check_transaction(connection, record, context, active=False)
            if request_id is not None:
                prior = connection.execute("SELECT * FROM feedback_rules_events WHERE task_id=? AND request_id=?", (context.task_id, request_id)).fetchone()
                if prior:
                    if self._payload(prior) != payload:
                        raise FeedbackError("blocked_conflict", "请求 ID 已用于另一个冲突决定。")
                    return False
            self.processor.selections._check_transaction(connection, record, context, active=kind == "decision")
            head = connection.execute("SELECT snapshot_id FROM feedback_rules_heads WHERE task_id=? AND base_version_id=?", (context.task_id, context.base_version_id)).fetchone()
            expected = previous.snapshot_id if baseline is None else None
            if (head[0] if head else None) != expected:
                raise FeedbackError("blocked_conflict", "其他反馈已更新规则快照，请重新加载。")
            # No answer made after the displayed analysis may be silently lost.
            analysis = next(i for i in snapshot.inputs if i.interpretation.feedback_id == record.feedback_id)
            count = connection.execute("SELECT COUNT(*) FROM feedback_processing_decisions WHERE feedback_id=?", (record.feedback_id,)).fetchone()[0]
            choice = connection.execute("SELECT result_resolution_id FROM selection_target_decisions WHERE feedback_id=?", (record.feedback_id,)).fetchone()
            if count != analysis.decision_count or choice and (analysis.selection is None or analysis.selection.resolution_id != choice[0]):
                raise FeedbackError("blocked_conflict", "反馈目标或范围已收到其他确认，请重新加载。")
            if baseline: self._save(connection, baseline)
            connection.execute("INSERT INTO feedback_rules_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (context.task_id, context.base_version_id, snapshot.revision, kind, decision_id, request_id,
                 canonical_bytes(payload).decode(), content_hash(payload), _utc_now()))
            self._save(connection, snapshot)
        return True

    def review(self, task_id, version_id, feedback_id):
        with self._lock:
            record, context, _, text, semantic, _, _, analysis = self.processor._fresh(task_id, version_id, feedback_id)
            previous = self.load(task_id, version_id)
            if previous and any(i == analysis for i in previous.inputs): return self._review(previous, feedback_id)
            if previous and previous.revision >= 256: raise FeedbackError("needs_user_input", "反馈规则修订过多，请另建任务。")
            basis = self.basis_loader(context)
            if basis and basis.academic_rules_snapshot_id != context.rules_snapshot_id: raise FeedbackError("validation_failed", "学术依据不匹配。")
            inherited = self._parent(context)
            mapping = self._mapping(context, inherited)
            baseline = None
            if previous is None:
                previous = baseline = compile_rules(context, [], basis, text, semantic, {}, revision=0,
                    previous_snapshot_id=None, fingerprint=self.fingerprint,
                    parent_snapshot_id=context.feedback_rules_snapshot_id, inherited=inherited,
                    compiler_version="feedback-rules/1.2", inherited_mapping=mapping)
            inputs = self._replace_input(previous.inputs, analysis)
            if len(inputs) > 64: raise FeedbackError("needs_user_input", "当前版本核对反馈超过 64 条，请拆分。")
            decisions = self._decisions(task_id, version_id)
            raw = {i.interpretation.feedback_id: self.feedback.get(task_id, version_id, i.interpretation.feedback_id).submission.raw_text for i in inputs}
            updated = compile_rules(context, inputs, basis, text, semantic, decisions, revision=previous.revision+1,
                previous_snapshot_id=previous.snapshot_id, fingerprint=self.fingerprint,
                parent_snapshot_id=context.feedback_rules_snapshot_id, raw_texts=raw, inherited=inherited,
                compiler_version="feedback-rules/1.2", inherited_mapping=mapping)
            self._append(record, context, previous, updated, "review", analysis.model_dump(mode="json"), baseline=baseline)
            return self._review(updated, feedback_id)

    def _decisions(self, task_id, version_id):
        with self.versions._transaction() as connection:
            rows = connection.execute("SELECT * FROM feedback_rules_events WHERE task_id=? AND base_version_id=? AND kind='decision' AND sequence>COALESCE((SELECT MAX(sequence) FROM feedback_rules_events WHERE task_id=? AND base_version_id=? AND kind='restart'),0) ORDER BY sequence", (task_id, version_id, task_id, version_id)).fetchall()
        return {answer.conflict_id: (answer, row["decision_id"]) for row in rows
            if (answer := FeedbackRulesDecision.model_validate_json(json.dumps(self._payload(row))))}

    def prepare_restart(self, task_id, version_id):
        previous = self.load(task_id, version_id)
        if previous is None: return None, None
        if previous.revision >= 256:
            raise FeedbackError("needs_user_input", "该版本规则修订已达上限，无法创建新的工作分支。")
        context, basis, text, semantic = self._sources(task_id, version_id)
        inherited = self._parent(context)
        updated = compile_rules(context, [], basis, text, semantic, {}, revision=previous.revision+1,
            previous_snapshot_id=previous.snapshot_id, fingerprint=self.fingerprint,
            parent_snapshot_id=context.feedback_rules_snapshot_id, inherited=inherited,
            compiler_version="feedback-rules/1.2", inherited_mapping=self._mapping(context, inherited))
        return previous, updated

    def commit_restart(self, connection, request, previous, snapshot):
        head = connection.execute("SELECT snapshot_id FROM feedback_rules_heads WHERE task_id=? AND base_version_id=?", (request.task_id, request.version_id)).fetchone()
        if (head[0] if head else None) != (previous.snapshot_id if previous else None):
            raise FeedbackError("blocked_conflict", "选择工作起点期间规则核对头发生变化，请刷新。")
        if snapshot is None: return
        if connection.execute("SELECT 1 FROM feedback_rules_events WHERE task_id=? AND request_id=?", (request.task_id, request.request_id)).fetchone():
            raise FeedbackError("blocked_conflict", "继续请求 ID 已用于其他规则事件。")
        payload = request.model_dump(mode="json")
        connection.execute("INSERT INTO feedback_rules_events VALUES (?,?,?,?,?,?,?,?,?)", (
            request.task_id, request.version_id, snapshot.revision, "restart", None, request.request_id,
            canonical_bytes(payload).decode(), content_hash(payload), _utc_now()))
        self._save(connection, snapshot)

    def decide(self, task_id, version_id, feedback_id, answer):
        answer = FeedbackRulesDecision.model_validate_json(answer.model_dump_json())
        if (task_id, version_id, feedback_id) != (answer.task_id, answer.base_version_id, answer.feedback_id):
            raise FeedbackError("stale_base_version", "冲突决定路径与反馈不一致。")
        with self._lock:
            snapshot = self.load(task_id, version_id)
            if snapshot is None: raise FeedbackError("needs_user_input", "请先核对当前规则快照。")
            with self.versions._transaction() as connection:
                prior = connection.execute("SELECT * FROM feedback_rules_events WHERE task_id=? AND request_id=?", (task_id, answer.request_id)).fetchone()
            if prior:
                if self._payload(prior) != answer.model_dump(mode="json"):
                    raise FeedbackError("blocked_conflict", "请求 ID 已用于另一个冲突决定。")
                return self._review(snapshot, feedback_id)
            record, context, _, text, semantic, _, _, analysis = self.processor._fresh(task_id, version_id, feedback_id)
            if analysis not in snapshot.inputs: raise FeedbackError("blocked_conflict", "反馈范围已变化，请重新核对规则。")
            self._validate_choice(record, context, snapshot, answer)
            if snapshot.revision >= 256: raise FeedbackError("needs_user_input", "反馈规则修订已达上限。")
            decisions = self._decisions(task_id, version_id)
            decisions[answer.conflict_id] = (answer, new_id())
            raw = {i.interpretation.feedback_id: self.feedback.get(task_id, version_id, i.interpretation.feedback_id).submission.raw_text for i in snapshot.inputs}
            inherited = self._parent(context)
            mapping = self._mapping(context, inherited)
            updated = compile_rules(context, snapshot.inputs, self.basis_loader(context), text, semantic, decisions,
                revision=snapshot.revision+1, previous_snapshot_id=snapshot.snapshot_id, fingerprint=self.fingerprint,
                parent_snapshot_id=context.feedback_rules_snapshot_id, raw_texts=raw, inherited=inherited,
                compiler_version="feedback-rules/1.2", inherited_mapping=mapping)
            appended = self._append(record, context, snapshot, updated, "decision", answer.model_dump(mode="json"),
                decision_id=decisions[answer.conflict_id][1], request_id=answer.request_id)
            if not appended: return self._review(self.load(task_id, version_id), feedback_id)
            return self._review(updated, feedback_id)
