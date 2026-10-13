"""Child processes for the sync hints tests (spec 026 PR-58).

``python -m tests.sync_hints_processes serve <data_dir> <port>`` serves the real
application plus the hints router. ``... write <data_dir> <owner> <key> [rollback]``
commits (or rolls back) one feed transaction through the real unit of work and
receipt store, from a process that shares no memory with the server.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def commit(data_dir: Path, owner: str, key: str, *, rollback: bool = False) -> str:
    """One legacy command through ``ReceiptStore``; returns its commit sequence."""
    from app.modules.tasks import TaskRepository
    from app.modules.tasks.domain import TaskDocument
    from app.modules.tasks.jobs import JobRepository
    from app.modules.tasks.rust_adapter import RustCore
    from app.modules.tasks.rust_review_facade import encode_task
    from app.modules.tasks.sync.receipts import (
        CommandRequest,
        ReceiptStore,
        ScopeAuthority,
    )
    from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork

    repo = TaskRepository(data_dir)
    units = TaskUnitOfWork(repo, JobRepository(repo.db_path))

    def authority(unit):  # type: ignore[no-untyped-def]
        with sqlite3.connect(repo.db_path) as conn:
            row = conn.execute(
                "SELECT server_generation, feed_generation, access_generation, "
                "storage_epoch FROM sync_scopes WHERE owner_id = ?",
                (unit.owner_id,),
            ).fetchone()
        return ScopeAuthority(unit.owner_id, *row)

    task = TaskDocument(
        id=f"task_{key}",
        owner_id=owner,
        title="Secret title",
        state="inbox",
        order_key=0,
        created_at=NOW,
        updated_at=NOW,
    )
    request = CommandRequest.legacy(owner, key, "task.create", {"title": task.title})
    try:
        with ReceiptStore(RustCore()).command(
            units, request, authority, now=NOW
        ) as cmd:
            repo.create(task)
            result = cmd.accept(
                [
                    {
                        "operation": "upsert",
                        "entity_type": "task",
                        "value": encode_task(task),
                    }
                ]
            )
            if rollback:
                raise RuntimeError("rolled back")
    except RuntimeError as error:
        return str(error)
    return str(result["commit_seq"])


def serve(data_dir: str, port: int) -> None:
    # The module-level ``app`` in app.main reads the environment when imported.
    os.environ["BRAIN_BUDDY_DATA_DIR"] = data_dir
    os.environ["BRAIN_BUDDY_ENV"] = "test"
    import uvicorn

    from app.api.sync_hints import router
    from app.main import create_app
    from app.modules.tasks.sync.hints import HintHub, SqliteCommitCounter

    app = create_app()
    app.include_router(router, prefix="/api")
    container = app.state.container
    app.state.sync_hint_hub = HintHub(
        SqliteCommitCounter(container.task_repo.db_path),
        container.task_service.clock,
        heartbeat=1.0,
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    if mode == "serve":
        serve(args[0], int(args[1]))
    else:
        print(commit(Path(args[0]), args[1], args[2], rollback="rollback" in args[3:]))
