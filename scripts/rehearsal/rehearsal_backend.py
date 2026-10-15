"""A local Brain Buddy backend for the automated rehearsal (spec 026, S1; 027 test control).

Run with the ``backend`` directory as the working directory::

    python rehearsal_backend.py --data-dir D --port P [--sync-mode on|off] [--resume]

It starts the production application as a child process (``uvicorn app.main:app`` with
``BRAIN_BUDDY_ENV=test`` and a per-run ``BRAIN_BUDDY_TEST_CONTROL_TOKEN``), then seeds it only
through ``/api/__test__/`` (invites and feature-flag modes) and the public auth API. Nothing is
imported into this process from the application. It signs up synthetic accounts A and B, sets
``rust_core_sync`` and ``weekly_review`` as asked, prints one JSON line ``{"base_url", "accounts"}``
and serves until killed. ``--resume`` reuses an existing data dir (accounts already exist).
"""

from __future__ import annotations

import argparse
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
EMAILS = {"A": "rehearsal-a@example.com", "B": "rehearsal-b@example.com"}
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
    headers: dict[str, str] | None = None,
) -> tuple[int, list[tuple[str, str]], str]:
    """One request to the local server: (status, response headers, body text)."""
    send = dict(headers or {})
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


def session_cookie(headers: list[tuple[str, str]]) -> str:
    for name, value in headers:
        if name.lower() == "set-cookie" and value.startswith(f"{SESSION_COOKIE}="):
            return value.split(";", 1)[0]
    return ""


def start_server(data_dir: str, port: int, token: str) -> subprocess.Popen[bytes]:
    """The production app on ``port`` in the test environment; returns once it is healthy."""
    env = dict(
        os.environ,
        BRAIN_BUDDY_DATA_DIR=data_dir,
        BRAIN_BUDDY_ENV="test",
        BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER="deterministic",
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


def set_flag(port: int, token: str, key: str, mode: str) -> None:
    status, _, text = call(
        port,
        "PUT",
        f"/api/__test__/flags/{key}",
        {"mode": mode, "owners": []},
        token=token,
    )
    if status != 200:
        raise SystemExit(f"flag {key} failed: {status} {text[:200]}")


def open_account(
    port: int, token: str, email: str, password: str, *, reuse: bool
) -> tuple[str, str]:
    """Signs up (or logs in when reusing a data dir); returns (session cookie, owner id)."""
    if reuse:
        status, headers, _ = call(
            port, "POST", "/api/auth/login", {"email": email, "password": password}
        )
        expected = 200
    else:
        status, _, text = call(
            port, "POST", "/api/__test__/invites", {"count": 1}, token=token
        )
        if status != 200:
            raise SystemExit(f"invite failed: {status} {text[:200]}")
        code = json.loads(text)["codes"][0]
        status, headers, _ = call(
            port,
            "POST",
            "/api/auth/signup",
            {"email": email, "password": password, "invite_code": code},
        )
        expected = 201
    if status != expected:
        raise SystemExit(f"account {email} failed: {status}")
    cookie = session_cookie(headers)
    _, _, me = call(port, "GET", "/api/auth/me", cookie=cookie)
    return cookie, json.loads(me)["id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--sync-mode", choices=("on", "off"), default="on")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    token = secrets.token_urlsafe(24)
    child = start_server(args.data_dir, args.port, token)
    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        set_flag(args.port, token, "rust_core_sync", args.sync_mode)
        set_flag(args.port, token, "weekly_review", "on")
        accounts: dict[str, dict[str, str]] = {}
        for name, email in EMAILS.items():
            cookie, _ = open_account(
                args.port, token, email, PASSWORD, reuse=args.resume
            )
            accounts[name] = {"email": email, "password": PASSWORD, "cookie": cookie}
        info = {"base_url": f"http://127.0.0.1:{args.port}", "accounts": accounts}
        print(json.dumps(info), flush=True)
        child.wait()
    finally:
        stop_server(child)


if __name__ == "__main__":
    main()
