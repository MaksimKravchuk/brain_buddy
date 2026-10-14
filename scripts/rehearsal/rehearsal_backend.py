"""A local Brain Buddy backend for the automated rehearsal (spec 026, S1).

Run with the ``backend`` directory as the working directory::

    python rehearsal_backend.py --data-dir D --port P [--sync-mode on|off] [--resume]

It signs up synthetic accounts A and B (invite + ``POST /api/auth/signup``), sets
``rust_core_sync`` and ``weekly_review`` as asked, uses the deterministic review
navigator, prints one JSON line ``{"base_url", "accounts"}`` and serves until
killed. ``--resume`` reuses an existing data dir (accounts already exist).
"""

# ruff: noqa: PLC0415 - the backend app must import after the environment is set
from __future__ import annotations

import argparse
import json
import os
import secrets

PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - synthetic local account
EMAILS = {"A": "rehearsal-a@example.com", "B": "rehearsal-b@example.com"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--sync-mode", choices=("on", "off"), default="on")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    os.environ["BRAIN_BUDDY_DATA_DIR"] = args.data_dir
    os.environ["BRAIN_BUDDY_ENV"] = "test"
    os.environ["BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER"] = "deterministic"
    import uvicorn
    from app.main import app
    from app.schemas.auth import Invite
    from app.utils.time import utcnow
    from fastapi.testclient import TestClient

    container = app.state.container
    accounts: dict[str, dict[str, str]] = {}
    for name, email in EMAILS.items():
        client = TestClient(app)
        if args.resume:
            reply = client.post(
                "/api/auth/login", json={"email": email, "password": PASSWORD}
            )
            ok = reply.status_code == 200
        else:
            code = f"invite_rehearsal_{secrets.token_hex(4)}"
            container.invite_repo.create(Invite(code=code, created_at=utcnow()))
            reply = client.post(
                "/api/auth/signup",
                json={"email": email, "password": PASSWORD, "invite_code": code},
            )
            ok = reply.status_code == 201
        if not ok:
            raise SystemExit(f"account {name} failed: {reply.status_code}")
        cookie = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
        accounts[name] = {"email": email, "password": PASSWORD, "cookie": cookie}
        client.close()
    flags = container.feature_flag_service
    flags.set_mode("rust_core_sync", args.sync_mode, operator_id="rehearsal")
    flags.set_mode("weekly_review", "on", operator_id="rehearsal")
    info = {"base_url": f"http://127.0.0.1:{args.port}", "accounts": accounts}
    print(json.dumps(info), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
