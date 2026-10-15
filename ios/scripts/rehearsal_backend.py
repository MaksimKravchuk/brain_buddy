"""The real Brain Buddy backend for the automated pilot rehearsal (spec 026, rehearsal S3; 027 test control).

``python rehearsal_backend.py <data_dir> <port>`` (run with ``backend/`` as the working directory
and on ``PYTHONPATH``) starts the production application as a child process in
``BRAIN_BUDDY_ENV=test`` and seeds it only through ``/api/__test__/`` (invites and flags) and the
public auth API. It signs up A and B, switches ``rust_core_sync`` on (``weekly_review`` stays off),
prints one JSON line ``{"accounts": [{"label", "email", "password", "id"}, ...]}`` and serves the
production application until killed. Nothing is mocked. Local rehearsal only: it never talks to a
deployed server and sends no provider request.
"""

from __future__ import annotations

import http.client
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from typing import Any

PASSWORD = "correct-horse-battery-staple"
OWNERS = (("A", "rehearsal-a@example.com"), ("B", "rehearsal-b@example.com"))
CONTROL_HEADER = "X-Test-Control-Token"
SESSION_COOKIE = "brainbuddy_session"


def call(  # one HTTP request to the local server
    port: int,
    method: str,
    path: str,
    body: Any = None,
    *,
    token: str | None = None,
    cookie: str | None = None,
) -> tuple[int, list[tuple[str, str]], str]:
    """One request to the local server: (status, response headers, body text)."""
    send: dict[str, str] = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        send["Content-Type"] = "application/json"
    if token:
        send[CONTROL_HEADER] = token
    if cookie:
        send["Cookie"] = cookie
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request(method, path, body=data, headers=send)
        reply = conn.getresponse()
        return reply.status, reply.getheaders(), reply.read().decode()
    finally:
        conn.close()


def start_server(data_dir: str, port: int, token: str) -> subprocess.Popen[bytes]:
    """The production app on ``port`` in the test environment; returns once it is healthy."""
    env = dict(
        os.environ,
        BRAIN_BUDDY_DATA_DIR=data_dir,
        BRAIN_BUDDY_ENV="test",
        BRAIN_BUDDY_TEST_CONTROL_TOKEN=token,
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=os.getcwd(),
        env=env,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise SystemExit(f"server exited with {child.returncode}")
        try:
            if call(port, "GET", "/api/health")[0] == 200:
                return child
        except OSError:
            time.sleep(0.2)
    stop_server(child)
    raise SystemExit("server did not become healthy")


def stop_server(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()


def open_account(port: int, token: str, email: str) -> tuple[str, str]:
    """Signs the synthetic owner up with a fresh invite; returns (session cookie, owner id)."""
    status, _, text = call(
        port, "POST", "/api/__test__/invites", {"count": 1}, token=token
    )
    if status != 200:
        raise SystemExit(f"invite failed: {status} {text[:200]}")
    code = json.loads(text)["codes"][0]
    status, headers, text = call(
        port,
        "POST",
        "/api/auth/signup",
        {"email": email, "password": PASSWORD, "invite_code": code},
    )
    if status != 201:
        raise SystemExit(f"signup failed: {status} {text[:200]}")
    cookie = next(
        (
            value.split(";", 1)[0]
            for name, value in headers
            if name.lower() == "set-cookie" and value.startswith(f"{SESSION_COOKIE}=")
        ),
        "",
    )
    _, _, me = call(port, "GET", "/api/auth/me", cookie=cookie)
    return cookie, json.loads(me)["id"]


def main(data_dir: str, port: int) -> None:
    token = secrets.token_urlsafe(24)
    child = start_server(data_dir, port, token)
    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        accounts = []
        for label, email in OWNERS:
            _, owner = open_account(port, token, email)
            accounts.append(
                {"label": label, "email": email, "password": PASSWORD, "id": owner}
            )
        # Weekly review stays OFF (the pilot default): the clients here run with the review hidden, and a
        # server that exposed it would require formulation ids they do not send.
        status, _, text = call(
            port,
            "PUT",
            "/api/__test__/flags/rust_core_sync",
            {"mode": "on", "owners": []},
            token=token,
        )
        if status != 200:
            raise SystemExit(f"flag rust_core_sync failed: {status} {text[:200]}")
        print(json.dumps({"accounts": accounts}), flush=True)
        child.wait()
    finally:
        stop_server(child)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
