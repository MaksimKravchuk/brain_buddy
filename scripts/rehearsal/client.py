"""Stdlib HTTP client and local-backend process manager for the rehearsal."""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from guard import GuardError, RequestBudget, is_blocked

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parents[1] / "backend"
DEFAULT_VENV_PYTHON = "/tmp/bb-pr31-venv/bin/python"  # noqa: S108 - dev venv


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    text: str

    @property
    def cid(self) -> str:
        return self.headers.get("x-correlation-id", "")

    def json(self) -> Any:
        try:
            return json.loads(self.text) if self.text else None
        except json.JSONDecodeError:
            return None


@dataclass
class Api:
    base_url: str
    budget: RequestBudget
    prod: bool = False
    cids: list[str] = field(default_factory=list)

    def call(  # noqa: PLR0913 - one HTTP call
        self,
        method: str,
        path: str,
        cookie: str | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
        timeout: float = 20,
    ) -> Resp:
        if self.prod and is_blocked(path):
            raise GuardError(f"blocked on production: {path.split('?', maxsplit=1)[0]}")
        self.budget.spend()
        parts = urlsplit(self.base_url)
        if parts.scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                parts.hostname or "",
                parts.port,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        else:
            conn = http.client.HTTPConnection(
                parts.hostname or "", parts.port, timeout=timeout
            )
        send = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            send["Content-Type"] = "application/json"
        if cookie:
            send["Cookie"] = cookie
        try:
            conn.request(method, path, body=data, headers=send)
            raw = conn.getresponse()
            got = {k.lower(): v for k, v in raw.getheaders()}
            text = "" if stream and raw.status == 200 else raw.read().decode()
        finally:
            conn.close()
        resp = Resp(raw.status, got, text)
        if resp.cid:
            self.cids.append(resp.cid)
        return resp


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def backend_python() -> str:
    explicit = os.environ.get("BB_REHEARSAL_PYTHON")
    if explicit:
        return explicit
    return DEFAULT_VENV_PYTHON if Path(DEFAULT_VENV_PYTHON).exists() else sys.executable


def backend_env(data_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        BRAIN_BUDDY_DATA_DIR=str(data_dir),
        BRAIN_BUDDY_ENV="test",
        BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER="deterministic",
    )
    return env


def run_cli(data_dir: Path, *args: str) -> tuple[int, str]:
    """``python -m app.cli`` against ``data_dir`` (the backend must be stopped)."""
    done = subprocess.run(  # noqa: S603 - fixed local interpreter and arguments
        [backend_python(), "-m", "app.cli", *args],
        cwd=BACKEND_DIR,
        env=backend_env(data_dir),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return done.returncode, (done.stdout + done.stderr).strip()[-1500:]


class LocalBackend:
    """``rehearsal_backend.py`` as a child process."""

    def __init__(self, data_dir: Path, sync_mode: str = "on", resume: bool = False):
        self.data_dir, self.sync_mode, self.resume = data_dir, sync_mode, resume
        self.log: Any = None
        self.proc: subprocess.Popen[str] | None = None
        self.info: dict[str, Any] = {}

    def start(self) -> dict[str, Any]:
        port = free_port()
        self.log = (self.data_dir.parent / f"{self.data_dir.name}.log").open("a")
        self.data_dir.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            backend_python(),
            str(HERE / "rehearsal_backend.py"),
            "--data-dir",
            str(self.data_dir),
            "--port",
            str(port),
            "--sync-mode",
            self.sync_mode,
        ]
        if self.resume:
            cmd.append("--resume")
        self.proc = subprocess.Popen(  # noqa: S603 - fixed local interpreter
            cmd,
            cwd=BACKEND_DIR,
            env={**backend_env(self.data_dir), "PYTHONPATH": str(BACKEND_DIR)},
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
        )
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("local backend exited before printing its identity")
        self.info = json.loads(line)
        deadline = time.monotonic() + 30
        probe = Api(self.info["base_url"], RequestBudget(10**6))
        while time.monotonic() < deadline:
            try:
                if probe.call("GET", "/api/health").status == 200:
                    return self.info
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("local backend did not become healthy")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
