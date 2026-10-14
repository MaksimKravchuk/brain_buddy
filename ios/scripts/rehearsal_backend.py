"""The real Brain Buddy backend for the automated pilot rehearsal (spec 026, rehearsal S3).

``python rehearsal_backend.py <data_dir> <port>`` (run with ``backend/`` as the working directory
and on ``PYTHONPATH``) is ``rust/crates/bb-client/tests/support/sse_backend.py`` with two synthetic
owners instead of one: it signs up A and B, switches ``rust_core_sync`` on (``weekly_review`` stays off),
prints one JSON line ``{"accounts": [{"label", "email", "password", "id"}, ...]}`` and serves the
production application until killed. Nothing is mocked. Local rehearsal only: it never talks to a
deployed server and sends no provider request.
"""

from __future__ import annotations

import json
import os
import sys

PASSWORD = "correct-horse-battery-staple"
OWNERS = (("A", "rehearsal-a@example.com"), ("B", "rehearsal-b@example.com"))


def main(data_dir: str, port: int) -> None:
    os.environ["BRAIN_BUDDY_DATA_DIR"] = data_dir
    os.environ["BRAIN_BUDDY_ENV"] = "test"
    import uvicorn
    from app.main import app
    from app.schemas.auth import Invite
    from app.utils.time import utcnow
    from fastapi.testclient import TestClient

    container = app.state.container
    accounts = []
    for label, email in OWNERS:
        code = f"invite_rehearsal_{label.lower()}"
        container.invite_repo.create(Invite(code=code, created_at=utcnow()))
        client = TestClient(app)
        signup = client.post(
            "/api/auth/signup",
            json={"email": email, "password": PASSWORD, "invite_code": code},
        )
        if signup.status_code != 201:
            raise SystemExit(f"signup failed: {signup.status_code} {signup.text}")
        owner = client.get("/api/auth/me").json()["id"]
        client.close()
        accounts.append(
            {"label": label, "email": email, "password": PASSWORD, "id": owner}
        )
    # Weekly review stays OFF (the pilot default): the clients here run with the review hidden, and a
    # server that exposed it would require formulation ids they do not send.
    container.feature_flag_service.set_mode(
        "rust_core_sync", "on", operator_id="rehearsal"
    )
    print(json.dumps({"accounts": accounts}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
