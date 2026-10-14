"""Local backend for the iOS Simulator UI rehearsal (spec 026, evidence S4).

``python ui_backend.py <data_dir> <port>`` (run with ``backend/`` as the working
directory, using an interpreter that has the backend's dependencies and
``bb_core``) starts the production application in ``BRAIN_BUDDY_ENV=test`` with

* ``rust_core_sync`` and ``weekly_review`` switched on,
* the hermetic ``deterministic`` review navigator (no provider, no network),
* two synthetic accounts, A and B (passwords below are local-only fixtures),
* a fault proxy in front of the server.

The simulator talks to the *proxy* (``http://localhost:<port>/api``); the real
server listens on ``<port>+1`` and a control endpoint on ``<port>+2``:

    GET /mode/up       forward everything (default)
    GET /mode/down     refuse: close every connection at once (offline / dead server)
    GET /mode/unauth   answer every request with 401 (an expired session)
    GET /seed-stalled?owner=a&title=T&days=30   a Next task whose wording clock started days ago
    GET /state         the current mode and the number of requests seen per path
    GET /requests      JSON list of ``METHOD path`` lines seen while mode was ``up``

Prints one JSON line with the fixtures and then serves until killed. Test-only:
nothing here may point at, or be reachable from, a deployed environment.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

REQUEST_LINE = re.compile(rb"(GET|POST|PUT|PATCH|DELETE) \S+")

ACCOUNTS = {
    "a": ("rehearsal-a@example.com", "rehearsal-a-password-1"),
    "b": ("rehearsal-b@example.com", "rehearsal-b-password-1"),
}


class FaultProxy:
    """A byte-level TCP proxy whose mode a test can flip over HTTP."""

    def __init__(self, listen: int, upstream: int, control: int, seed_stalled) -> None:
        self.listen, self.upstream, self.control = listen, upstream, control
        self.seed_stalled = seed_stalled
        self.mode = "up"
        self.seen: list[str] = []
        self._pipes: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        await asyncio.start_server(self._client, "127.0.0.1", self.listen)
        await asyncio.start_server(self._control, "127.0.0.1", self.control)
        # The simulator resolves ``localhost`` to ::1 as often as 127.0.0.1.
        try:
            await asyncio.start_server(self._client, "::1", self.listen)
            await asyncio.start_server(self._control, "::1", self.control)
        except OSError:
            pass

    async def _client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if self.mode == "down":
            writer.close()
            return
        if self.mode == "unauth":
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 401 Unauthorized\r\ncontent-type: application/json\r\n"
                    b'content-length: 27\r\nconnection: close\r\n\r\n{"detail":"Not authenticated"}'
                )
                await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            writer.close()
            return
        try:
            up_reader, up_writer = await asyncio.open_connection(
                "127.0.0.1", self.upstream
            )
        except OSError:
            writer.close()
            return
        self._pipes.update({writer, up_writer})

        async def pump(src, dst, record: bool) -> None:
            try:
                while data := await src.read(65536):
                    request = REQUEST_LINE.match(data) if record else None
                    if request:
                        line = request.group(0).decode("latin-1")
                        self.seen.append(line)
                    dst.write(data)
                    await dst.drain()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                dst.close()

        await asyncio.gather(
            pump(reader, up_writer, True), pump(up_reader, writer, False)
        )
        self._pipes.discard(writer)
        self._pipes.discard(up_writer)

    async def _control(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
            path = head.split(" ")[1]
            if path.startswith("/mode/"):
                self.mode = path.removeprefix("/mode/")
                if self.mode != "up":
                    for pipe in list(self._pipes):
                        pipe.close()
                    self._pipes.clear()
                body = {"mode": self.mode}
            elif path.startswith("/seed-stalled"):
                # /seed-stalled?owner=a&title=T&days=30: a Next task whose formulation clock
                # started `days` ago (the server clock is moved back for that one create).
                query = parse_qs(urlsplit(path).query)
                body = await asyncio.to_thread(self.seed_stalled, query)
            elif path == "/requests":
                body = {"requests": self.seen}
            else:
                body = {"mode": self.mode, "requests": len(self.seen)}
            raw = json.dumps(body).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
                b"connection: close\r\ncontent-length: "
                + str(len(raw)).encode()
                + b"\r\n\r\n"
                + raw
            )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        writer.close()


def main(data_dir: str, port: int) -> None:
    sys.path.insert(0, os.getcwd())  # backend/ is the working directory
    os.environ["BRAIN_BUDDY_DATA_DIR"] = data_dir
    os.environ["BRAIN_BUDDY_ENV"] = "test"
    os.environ["BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER"] = "deterministic"
    import uvicorn
    from fastapi.testclient import TestClient

    from app.main import app
    from app.schemas.auth import Invite
    from app.utils.time import utcnow

    container = app.state.container
    reuse = os.environ.get("BB_REHEARSAL_REUSE") == "1"
    owners: dict[str, str] = {}
    for key, (email, password) in ACCOUNTS.items():
        code = f"invite_rehearsal_{key}"
        client = TestClient(app)
        if (
            reuse
        ):  # BB_REHEARSAL_REUSE=1: a data dir from an earlier run (debugging a test)
            client.post("/api/auth/login", json={"email": email, "password": password})
        else:
            container.invite_repo.create(Invite(code=code, created_at=utcnow()))
            signup = client.post(
                "/api/auth/signup",
                json={"email": email, "password": password, "invite_code": code},
            )
            if signup.status_code != 201:
                raise SystemExit(f"signup failed: {signup.status_code} {signup.text}")
        owners[key] = client.get("/api/auth/me").json()["id"]
        client.close()
    for flag in ("rust_core_sync", "weekly_review"):
        container.feature_flag_service.set_mode(flag, "on", operator_id="rehearsal")
    info = {
        "owners": owners,
        "accounts": {k: {"email": e, "password": p} for k, (e, p) in ACCOUNTS.items()},
        "proxy": f"http://localhost:{port}/api",
        "control": f"http://localhost:{port + 2}",
        "data_dir": str(container.task_repo.db_path.parent),
    }
    print(json.dumps(info), flush=True)

    def seed_stalled(query: dict[str, list[str]]) -> dict[str, object]:
        key = query.get("owner", ["a"])[0]
        email, password = ACCOUNTS[key]
        days = int(query.get("days", ["30"])[0])
        title = query["title"][0]
        service = container.task_service
        real_clock = service.clock
        client = TestClient(app)
        try:
            login = client.post(
                "/api/auth/login", json={"email": email, "password": password}
            )
            if login.status_code != 200:
                return {"error": f"login {login.status_code}"}
            service.clock = lambda: real_clock() - timedelta(days=days)
            created = client.post(
                "/api/tasks",
                json={
                    "title": title,
                    "state": "next",
                    "new_formulation_id": f"form_{uuid.uuid4()}",
                },
                headers={"Idempotency-Key": f"seed-{uuid.uuid4().hex}"},
            )
            return {"status": created.status_code, "body": created.text[:300]}
        finally:
            service.clock = real_clock
            client.close()

    async def serve() -> None:
        proxy = FaultProxy(port, port + 1, port + 2, seed_stalled)
        await proxy.start()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port + 1, log_level="warning")
        )
        await server.serve()

    asyncio.run(serve())


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
