"""Atomic, append-only persistence for the parser's user-decision loop."""

from __future__ import annotations

import hashlib
import json

from brief_parser.application.academic_decisions import AcademicDecisionEngine, AcademicDecisionError
from brief_parser.domain.academic_decisions import AcademicDecisionSnapshot, AcademicDecisionRequest, AcademicQuestionQueue, canonical_bytes

from .version_store import VersionStore, new_id, _utc_now


class AcademicDecisionStore:
    def __init__(self, versions: VersionStore, intake):
        self.versions, self.intake = versions, intake
        with versions._transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS academic_decision_snapshots (
                snapshot_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                parent_snapshot_id TEXT REFERENCES academic_decision_snapshots(snapshot_id),
                revision INTEGER NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(task_id, revision))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS academic_decision_heads (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                snapshot_id TEXT NOT NULL REFERENCES academic_decision_snapshots(snapshot_id))""")

    def _engine(self, task_id):
        bundle = self.intake.load_bundle(task_id)
        versions = self.versions.list_versions(task_id)
        # A new task starts its decision history at V0. Existing V1-bound
        # histories retain their original anchor after the workflow change.
        with self.versions._transaction() as connection:
            baseline = connection.execute(
                "SELECT payload_json FROM academic_decision_snapshots WHERE task_id=? AND revision=0",
                (task_id,),
            ).fetchone()
        if baseline is not None:
            try:
                anchor = json.loads(baseline[0])["initial_version_id"]
            except (ValueError, KeyError, TypeError) as error:
                raise AcademicDecisionError("validation_failed", "解析决定的基础版本无法校验。") from error
            initial = next((version for version in versions if version.version_id == anchor), None)
        else:
            initial = next((version for version in versions if version.kind == "output"), versions[0] if versions else None)
        if initial is None or initial.status != "ready" or initial.sequence not in {0, 1}:
            raise AcademicDecisionError("validation_failed", "解析决定的基础版本不可用。")
        return AcademicDecisionEngine(bundle, task_id=task_id, initial_version_id=initial.version_id)

    @staticmethod
    def _encoded(snapshot):
        encoded = canonical_bytes(snapshot.model_dump(mode="json"))
        if len(encoded) > 16 * 1024 * 1024:
            raise AcademicDecisionError("needs_user_input", "决策快照超出当前存储上限。")
        return encoded.decode("utf-8"), hashlib.sha256(encoded).hexdigest()

    def _row(self, row, engine):
        try:
            if row is None or hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest() != row["payload_sha256"]:
                raise ValueError("Stored snapshot hash differs.")
            snapshot = AcademicDecisionSnapshot.model_validate_json(row["payload_json"])
            if (snapshot.task_id != engine.task_id or snapshot.snapshot_id != row["snapshot_id"]
                    or snapshot.revision != row["revision"] or snapshot.parent_snapshot_id != row["parent_snapshot_id"]
                    or engine.compile(snapshot.events) != snapshot):
                raise ValueError("Stored snapshot differs from source replay.")
            return snapshot
        except (ValueError, TypeError, KeyError) as error:
            raise AcademicDecisionError("validation_failed", "解析决策快照无法通过来源重放校验。") from error

    def load(self, task_id, snapshot_id=None):
        engine = self._engine(task_id)
        with self.versions._transaction() as connection:
            if snapshot_id is None:
                head = connection.execute("SELECT snapshot_id FROM academic_decision_heads WHERE task_id=?", (task_id,)).fetchone()
                if head is None:
                    baseline = engine.compile()
                    payload, digest = self._encoded(baseline)
                    connection.execute("INSERT INTO academic_decision_snapshots VALUES (?, ?, NULL, 0, ?, ?, ?)",
                                       (baseline.snapshot_id, task_id, payload, digest, _utc_now()))
                    connection.execute("INSERT INTO academic_decision_heads VALUES (?, ?)", (task_id, baseline.snapshot_id))
                    return baseline
                snapshot_id = head[0]
            row = connection.execute("SELECT * FROM academic_decision_snapshots WHERE task_id=? AND snapshot_id=?", (task_id, snapshot_id)).fetchone()
            history = connection.execute("SELECT snapshot_id, parent_snapshot_id, revision FROM academic_decision_snapshots WHERE task_id=? ORDER BY revision", (task_id,)).fetchall()
            decisions = connection.execute("SELECT * FROM decisions WHERE task_id=?", (task_id,)).fetchall()
        if row is None:
            raise AcademicDecisionError("needs_user_input", "该任务没有所请求的解析规则快照。")
        snapshot = self._row(row, engine)
        try:
            chain = [item for item in history if item["revision"] <= snapshot.revision]
            if len(chain) != snapshot.revision + 1 or chain[0]["snapshot_id"] != engine.compile().snapshot_id:
                raise ValueError("Snapshot chain differs from the immutable baseline.")
            records = {item["decision_id"]: item for item in decisions}
            for revision, event in enumerate(snapshot.events, 1):
                current, previous = chain[revision], chain[revision - 1]
                if (current["revision"] != revision or current["parent_snapshot_id"] != previous["snapshot_id"]
                        or event.request.expected_snapshot_id != previous["snapshot_id"]):
                    raise ValueError("Decision base differs from actual snapshot history.")
                record = records[event.decision_id]
                if hashlib.sha256(record["payload_json"].encode("utf-8")).hexdigest() != record["payload_sha256"]:
                    raise ValueError("Decision hash changed.")
                payload = json.loads(record["payload_json"])
                kind = "skip" if event.request.answer.action == "skip" else "defer" if event.request.answer.action == "defer" else "answer"
                if (payload != {"scope_kind": "academic_rule_decision", "event": event.model_dump(mode="json"), "snapshot_id": current["snapshot_id"]}
                        or record["base_version_id"] != event.request.base_version_id or record["request_id"] != event.request.request_id
                        or record["kind"] != kind or record["created_at"] != event.created_at):
                    raise ValueError("Stored decision differs from snapshot event.")
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise AcademicDecisionError("validation_failed", "决定记录或规则快照历史无法通过校验。") from error
        return snapshot

    def list_snapshots(self, task_id):
        self.load(task_id)
        with self.versions._transaction() as connection:
            rows = connection.execute("SELECT snapshot_id, parent_snapshot_id, revision, created_at FROM academic_decision_snapshots WHERE task_id=? ORDER BY revision", (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def questions(self, task_id, reopen_decision_id=None):
        snapshot = self.load(task_id)
        questions = self._engine(task_id).reopen_questions(snapshot, reopen_decision_id) if reopen_decision_id else snapshot.questions
        return AcademicQuestionQueue(task_id=task_id,
                base_version_id=self.versions.working_version_id(task_id), snapshot_id=snapshot.snapshot_id,
                revision=snapshot.revision, reopen_decision_id=reopen_decision_id, questions=questions).model_dump(mode="json")

    def submit(self, task_id, request: AcademicDecisionRequest):
        encoded_request = request.model_dump(mode="json")
        with self.versions._transaction() as connection:
            previous = connection.execute("SELECT * FROM decisions WHERE task_id=? AND request_id=?", (task_id, request.request_id)).fetchone()
        if previous:
            try:
                payload = json.loads(previous["payload_json"])
                if hashlib.sha256(previous["payload_json"].encode("utf-8")).hexdigest() != previous["payload_sha256"]:
                    raise ValueError("Stored decision hash changed.")
                if payload.get("scope_kind") != "academic_rule_decision" or payload["event"]["request"] != encoded_request:
                    raise AcademicDecisionError("blocked_conflict", "请求 ID 已用于其他回答。")
                result = self.load(task_id, payload["snapshot_id"])
                event = next(item for item in result.events if item.decision_id == previous["decision_id"])
                if event.model_dump(mode="json") != payload["event"]:
                    raise ValueError("Stored event differs from snapshot.")
                return result, True
            except (ValueError, KeyError, StopIteration) as error:
                if isinstance(error, AcademicDecisionError):
                    raise
                raise AcademicDecisionError("validation_failed", "已有决定无法通过校验。") from error
        current = self.load(task_id)
        parent = self.versions.get_version(task_id, request.base_version_id)
        self.versions.artifact_path(task_id, parent.version_id, "docx")
        result = self._engine(task_id).submit(current, request, decision_id=new_id(), created_at=_utc_now())
        snapshot_json, snapshot_digest = self._encoded(result)
        event = result.events[-1]
        event_payload = {"scope_kind": "academic_rule_decision", "event": event.model_dump(mode="json"), "snapshot_id": result.snapshot_id}
        payload_json = json.dumps(event_payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(payload_json.encode("utf-8")) > 64 * 1024:
            raise AcademicDecisionError("needs_user_input", "决策回答超出存储上限。")
        kind = "skip" if request.answer.action == "skip" else "defer" if request.answer.action == "defer" else "answer"
        with self.versions._transaction() as connection:
            head = connection.execute("SELECT snapshot_id FROM academic_decision_heads WHERE task_id=?", (task_id,)).fetchone()
            active = connection.execute("SELECT working_version_id FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            version = connection.execute("SELECT status, docx_path, docx_sha256 FROM versions WHERE task_id=? AND version_id=?", (task_id, request.base_version_id)).fetchone()
            if (head is None or head[0] != current.snapshot_id or active is None or active[0] != request.base_version_id
                    or version is None or version["status"] != "ready" or not self.versions._matches_hash(version["docx_path"], parent.docx_sha256)):
                raise AcademicDecisionError("stale_base_version", "工作版本或规则快照已变化，请刷新后提交。")
            if connection.execute("SELECT 1 FROM decisions WHERE task_id=? AND request_id=?", (task_id, request.request_id)).fetchone():
                raise AcademicDecisionError("stale_base_version", "该请求已并发提交，请重试以取得原结果。")
            connection.execute("INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event.decision_id, task_id, request.base_version_id, request.request_id, kind,
                 payload_json, hashlib.sha256(payload_json.encode("utf-8")).hexdigest(), event.created_at))
            connection.execute("INSERT INTO academic_decision_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                (result.snapshot_id, task_id, current.snapshot_id, result.revision, snapshot_json, snapshot_digest, event.created_at))
            connection.execute("UPDATE academic_decision_heads SET snapshot_id=? WHERE task_id=?", (result.snapshot_id, task_id))
        return result, False
