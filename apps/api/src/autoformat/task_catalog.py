"""Bounded local task metadata, without file paths or document contents."""
from typing import Annotated, Literal
from pydantic import Field
from .feedback_contracts import Contract, Id, Text


class TaskSummary(Contract):
    task_id: Id
    created_at: Text
    working_version_id: Id
    working_sequence: Annotated[int, Field(ge=0)]
    version_count: Annotated[int, Field(ge=1)]
    has_initial_version: bool


class TaskCatalog(Contract):
    schema_version: Literal["task-catalog/1.0"]
    tasks: Annotated[list[TaskSummary], Field(max_length=50)]
    next_before: Annotated[int, Field(gt=0)] | None


class ApplicationInfo(Contract):
    schema_version: Literal["application-info/1.0"]
    mode: Literal["configured", "demo"]
    upload_available: bool
    max_file_bytes: Annotated[int, Field(gt=0, le=20 * 1024 * 1024)] | None


TASK_CONTRACTS = {"task-catalog/1.0": TaskCatalog, "application-info/1.0": ApplicationInfo}


def list_tasks(store, before=None):
    with store._transaction() as connection:
        rows = connection.execute("""SELECT t.rowid AS cursor_id,t.task_id,t.created_at,t.working_version_id,
            w.sequence AS working_sequence,COUNT(v.version_id) AS version_count,
            MAX(CASE WHEN v.kind='output' THEN 1 ELSE 0 END) AS has_initial_version
            FROM tasks t JOIN versions w ON w.task_id=t.task_id AND w.version_id=t.working_version_id AND w.status='ready'
            JOIN versions v ON v.task_id=t.task_id AND v.status='ready'
            WHERE (? IS NULL OR t.rowid<?) GROUP BY t.task_id ORDER BY t.rowid DESC LIMIT 51""", (before, before)).fetchall()
    return TaskCatalog(schema_version="task-catalog/1.0", tasks=[TaskSummary(
        task_id=r["task_id"], created_at=r["created_at"], working_version_id=r["working_version_id"],
        working_sequence=r["working_sequence"], version_count=r["version_count"],
        has_initial_version=bool(r["has_initial_version"])) for r in rows[:50]],
        next_before=rows[49]["cursor_id"] if len(rows) > 50 else None)
