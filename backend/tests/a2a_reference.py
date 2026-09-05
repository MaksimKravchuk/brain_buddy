"""Shared plumbing for the two reference-runtime conformance suites.

These suites are the only tests in the repository that speak A2A to a process
BrainBuddy did not write. Everything here exists to make that honest:

* a port is *checked before it is bound*, and a failure names what is already
  there, because "the sample would not start" and "something else answered on
  9999" are different bugs and only one of them is ours;
* a runtime that does not come up **fails**, it never skips. A conformance
  suite that skips itself when the thing it conforms to is missing reports
  green for the one condition it exists to catch (research.md Decision J);
* teardown is registered with ``request.addfinalizer`` the moment the process
  exists, so an assertion failure, a timeout or a `KeyboardInterrupt` still
  reaps it.
"""

from __future__ import annotations

import contextlib
import os
import queue
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = BACKEND_ROOT / "vendor"

#: How long a vendored runtime is given to answer on its card URL.
STARTUP_TIMEOUT_SECONDS = 30.0

#: How often the wait polls. Short enough that a fast start is not penalised.
STARTUP_POLL_SECONDS = 0.2


def describe_occupant(port: int, host: str = "127.0.0.1") -> str:
    """Best-effort identification of whatever already holds ``port``.

    Three sources, cheapest first, because the useful answer differs: another
    copy of the sample identifies itself by its own agent card, an unrelated
    local process is identifiable from ``/proc``, and anything else is at least
    reported as present rather than as an unexplained bind failure.
    """

    with contextlib.suppress(Exception):
        card = httpx.get(
            f"http://{host}:{port}/.well-known/agent-card.json", timeout=2.0
        )
        if card.status_code == 200:
            name = card.json().get("name")
            if name:
                return f"an A2A agent card naming {name!r}"

    inode = _listening_inode(port)
    if inode is not None:
        owner = _process_holding(inode)
        if owner is not None:
            return f"pid {owner[0]} ({owner[1]})"
        return f"an unidentified process (socket inode {inode})"
    return "an unidentified listener"


def _listening_inode(port: int) -> str | None:
    try:
        rows = Path("/proc/net/tcp").read_text(encoding="utf-8").splitlines()[1:]
    except OSError:  # pragma: no cover - non-Linux
        return None
    wanted = f"{port:04X}"
    for row in rows:
        fields = row.split()
        if len(fields) < 10:
            continue
        if fields[1].split(":")[1] == wanted and fields[3] == "0A":
            return fields[9]
    return None


def _process_holding(inode: str) -> tuple[str, str] | None:
    target = f"socket:[{inode}]"
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            for descriptor in (entry / "fd").iterdir():
                if os.readlink(descriptor) == target:
                    cmdline = (entry / "cmdline").read_bytes()
                    return entry.name, cmdline.replace(b"\0", b" ").decode().strip()
        except OSError:
            continue
    return None


def require_free_port(port: int, host: str = "127.0.0.1") -> None:
    """Fail — never skip — when the port a runtime must bind is taken."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
    except OSError:
        pytest.fail(
            f"{host}:{port} is already bound by {describe_occupant(port, host)}. "
            "The reference runtime cannot start, and skipping would report this "
            "suite green without ever speaking to an agent."
        )
    finally:
        probe.close()


def free_port(host: str = "127.0.0.1") -> int:
    """A port the OS says is free right now, for a runtime that binds port 0."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def start_runtime(
    request: pytest.FixtureRequest,
    *,
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    ready: Callable[[], bool],
    name: str,
) -> subprocess.Popen[bytes]:
    """Start one vendored runtime and guarantee it is reaped.

    The finalizer is registered *before* the readiness wait, so a runtime that
    starts and then fails to answer is still killed.
    """

    process = subprocess.Popen(  # noqa: S603 - fixed argv, vendored entrypoint
        argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    request.addfinalizer(lambda: _reap(process))

    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(
                f"{name} exited with code {process.returncode} before it was "
                f"ready. Output:\n{_drain(process)}"
            )
        with contextlib.suppress(Exception):
            if ready():
                return process
        time.sleep(STARTUP_POLL_SECONDS)

    pytest.fail(
        f"{name} did not become ready within {STARTUP_TIMEOUT_SECONDS:.0f}s. "
        f"Output so far:\n{_drain(process)}"
    )


def _reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)


def _drain(process: subprocess.Popen[bytes]) -> str:
    _reap(process)
    if process.stdout is None:
        return "<no output captured>"
    with contextlib.suppress(Exception):
        return process.stdout.read().decode(errors="replace")[-4000:]
    return "<no output captured>"


def start_announcing_runtime(
    request: pytest.FixtureRequest,
    *,
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    prefix: str,
    name: str,
) -> tuple[subprocess.Popen[bytes], int]:
    """Start a runtime that binds port 0 and prints the port it got.

    The output is drained by a thread for the process's whole life. A pipe
    nobody reads fills at 64 KiB and blocks the child mid-write, which would
    look exactly like an agent that stopped answering — the failure this suite
    exists to be able to trust.
    """

    process = subprocess.Popen(  # noqa: S603 - fixed argv, vendored entrypoint
        argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    request.addfinalizer(lambda: _reap(process))
    lines: list[str] = []
    announced: queue.Queue[int] = queue.Queue(maxsize=1)

    def drain() -> None:
        assert process.stdout is not None
        for raw in iter(process.stdout.readline, b""):
            line = raw.decode(errors="replace").rstrip("\n")
            lines.append(line)
            if line.startswith(prefix) and announced.empty():
                with contextlib.suppress(ValueError, queue.Full):
                    announced.put_nowait(int(line[len(prefix) :]))

    reader = threading.Thread(target=drain, daemon=True, name=f"{name}-output")
    reader.start()

    try:
        port = announced.get(timeout=STARTUP_TIMEOUT_SECONDS)
    except queue.Empty:
        _reap(process)
        pytest.fail(
            f"{name} never announced its port within "
            f"{STARTUP_TIMEOUT_SECONDS:.0f}s. Output:\n" + "\n".join(lines[-40:])
        )
    return process, port


def wait_until(
    ready: Callable[[], bool], *, name: str, timeout: float = STARTUP_TIMEOUT_SECONDS
) -> None:
    """Poll a readiness probe, and fail — never skip — when it never passes."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            if ready():
                return
        time.sleep(STARTUP_POLL_SECONDS)
    pytest.fail(f"{name} did not become ready within {timeout:.0f}s.")


def card_is_served(url: str) -> Callable[[], bool]:
    """A readiness probe that only passes on a parseable agent card."""

    def ready() -> bool:
        response = httpx.get(url, timeout=2.0)
        return response.status_code == 200 and bool(response.json().get("name"))

    return ready


def jsonrpc(
    url: str, method: str, params: dict[str, Any], *, bearer: str | None = None
) -> dict[str, Any]:
    """One JSON-RPC call straight at a runtime, bypassing BrainBuddy.

    Used only to observe what the *agent* did — never to drive BrainBuddy — so
    a suite can assert "exactly one task exists at the agent" without asking
    the code under test to confirm its own behaviour.
    """

    headers = {"Content-Type": "application/json", "A2A-Version": "1.0"}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    response = httpx.post(
        url,
        json={"jsonrpc": "2.0", "id": "probe", "method": method, "params": params},
        headers=headers,
        timeout=15.0,
    )
    response.raise_for_status()
    return dict(response.json())
