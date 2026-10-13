"""The real Brain Buddy backend, served for the bb-client hint-stream test.

``python sse_backend.py <data_dir> <port>`` (run with the backend directory as the
working directory) signs a user up, switches the ``rust_core_sync`` scope flag on,
prints one JSON line ``{"owner", "cookie", "data_dir", "db_path"}`` and then serves the production
application, hints router included, until it is killed. Nothing here is mocked:
the stream under test is the one PR-58 ships (``HintHub`` over the shared SQLite
commit counter), and writers are separate ``tests.sync_hints_processes write``
processes.
"""

from __future__ import annotations

import json
import os
import sys


def main(data_dir: str, port: int) -> None:
    os.environ["BRAIN_BUDDY_DATA_DIR"] = data_dir
    os.environ["BRAIN_BUDDY_ENV"] = "test"
    import uvicorn
    from fastapi.testclient import TestClient

    # The module-level application is the production one: it mounts the sync
    # routers (PR-63). It reads the environment above when it is imported.
    from app.main import app
    from app.schemas.auth import Invite
    from app.utils.time import utcnow

    container = app.state.container
    container.invite_repo.create(Invite(code="invite_bb_client", created_at=utcnow()))
    client = TestClient(app)
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": "bb-client@example.com",
            "password": "correct-horse-battery-staple",
            "invite_code": "invite_bb_client",
        },
    )
    if signup.status_code != 201:
        raise SystemExit(f"signup failed: {signup.status_code} {signup.text}")
    owner = client.get("/api/auth/me").json()["id"]
    container.feature_flag_service.set_mode(
        "rust_core_sync", "on", operator_id="bb-client-test"
    )
    cookie = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
    client.close()
    db_path = container.task_repo.db_path
    info = {
        "owner": owner,
        "cookie": cookie,
        "data_dir": str(db_path.parent),
        "db_path": str(db_path),
    }
    print(json.dumps(info), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
