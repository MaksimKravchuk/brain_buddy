"""Run the **unmodified** vendored Hermes A2A adapter with a scripted reply.

BrainBuddy-owned harness (spec 014 FR-017, 014-SC-001, 014-SC-006; research.md
Decision G). Not upstream code — see ``PROVENANCE.md``.

The point of this file is what it does *not* do. It never loads a model, never
reimplements the wire, and never patches the adapter: it starts the real
``A2AAdapter`` — its real HTTP server, JSON-RPC dispatch, agent card, task
store, blocking-send semantics and 300 s orphan watchdog — and only replaces
the agent brain behind it with a deterministic function. That is the same seam
Hermes' own plugin tests use (`_make_live_adapter`: override
``handle_message``, set ``_message_handler`` to a truthy sentinel), so the
behaviour BrainBuddy's client meets here is Hermes' behaviour, not ours.

Scripted replies
----------------
* text containing ``ask me`` (case-insensitive) → ``[INPUT_REQUIRED] <text>``,
  which the adapter's own ``_finalize_task`` maps to
  ``TASK_STATE_INPUT_REQUIRED`` — so even the blocked state comes from Hermes'
  code path, not from ours.
* anything else → the text echoed back, completing the task.
* ``STUB_REPLY_DELAY_SECONDS`` delays the reply, which is how the SC-006
  "answers at exactly the window" case is driven.

Environment
-----------
``A2A_PORT`` (``0`` under pytest, so the OS assigns and nothing collides),
``A2A_HOST``, ``A2A_BEARER_TOKEN``, ``A2A_PUBLIC_URL`` are read by the vendored
adapter and its security module. ``HOME`` is redirected to a scratch directory
before those modules are imported, because the plugin's optional Hermes imports
fall back to ``~/.hermes`` for its message store and audit log; the harness must
not write into the real home.

The bound port is printed to stdout as ``A2A_STUB_PORT=<port>`` and flushed, so
a test that asked for port 0 can read it back.

Usage::

    python run_stub.py                 # blocks until SIGINT/SIGTERM
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import tempfile
from pathlib import Path

#: Printed on stdout once the server is listening. Tests match on this exact
#: prefix rather than parsing the adapter's own log lines.
PORT_ANNOUNCEMENT_PREFIX = "A2A_STUB_PORT="

#: Substring that makes the scripted agent ask a clarifying question instead of
#: completing. Kept here rather than in the test so both the pytest harness and
#: the compose fixture drive the same script.
INPUT_REQUIRED_TRIGGER = "ask me"


def _redirect_home() -> Path:
    """Point ``HOME`` at a scratch directory before the plugin is imported.

    The vendored plugin's optional Hermes imports fall back to ``~/.hermes``
    for its SQLite message store and audit log. Left alone it would write into
    the real home directory of whoever runs the suite, which is both a
    side effect a test must not have and a cross-run contamination channel.
    """

    existing = os.environ.get("A2A_STUB_HOME")
    if existing:
        home = Path(existing)
        home.mkdir(parents=True, exist_ok=True)
    else:
        home = Path(tempfile.mkdtemp(prefix="hermes-a2a-stub-"))
    os.environ["HOME"] = str(home)
    return home


def _prepare_import_path() -> None:
    """Make ``gateway`` and ``plugins`` importable from this directory."""

    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


def _reply_delay_seconds() -> float:
    raw = os.environ.get("STUB_REPLY_DELAY_SECONDS", "0")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def scripted_reply(text: str) -> str:
    """The whole agent brain: deterministic, model-free, one line of policy."""

    if INPUT_REQUIRED_TRIGGER in (text or "").lower():
        return f"[INPUT_REQUIRED] {text}"
    return text or ""


def build_adapter(port: int | None = None):
    """Construct the real ``A2AAdapter`` over the stub gateway."""

    _prepare_import_path()
    from gateway.config import PlatformConfig  # noqa: PLC0415  (path set above)
    from plugins.platforms.a2a.adapter import A2AAdapter  # noqa: PLC0415

    if port is None:
        port = int(os.environ.get("A2A_PORT", "0"))
    config = PlatformConfig(enabled=True, extra={"port": port})
    adapter = A2AAdapter(config)

    delay = _reply_delay_seconds()

    async def handle_message(event) -> None:
        """Answer one dispatched task through the adapter's own reply path.

        ``send()`` with ``metadata['notify']`` is the marker the adapter treats
        as a final user-visible reply; without it the send is ignored as a
        progress update. Resolving through ``send()`` rather than poking the
        task store keeps the blocking-exchange semantics, the push
        notification and the input-required mapping all in Hermes' code.
        """

        if delay:
            await asyncio.sleep(delay)
        source = getattr(event, "source", None)
        chat_id = getattr(source, "chat_id", "") or ""
        await adapter.send(
            chat_id=chat_id,
            content=scripted_reply(getattr(event, "text", "") or ""),
            metadata={"notify": True},
        )

    # The adapter refuses to dispatch when `_message_handler` is None (it fails
    # the task as "gateway not ready"), so a truthy sentinel stands in for the
    # gateway session the harness deliberately does not have.
    adapter._message_handler = object()
    adapter.handle_message = handle_message  # type: ignore[method-assign]
    return adapter


async def serve() -> None:
    adapter = build_adapter()
    connected = await adapter.connect()
    if not connected:
        raise SystemExit(f"A2A stub failed to bind: {adapter.fatal_error}")

    bound_port = adapter._httpd.server_address[1]
    print(f"{PORT_ANNOUNCEMENT_PREFIX}{bound_port}", flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(getattr(signal, signal_name), stop.set)

    try:
        await stop.wait()
    finally:
        await adapter.disconnect()


def main() -> None:
    _redirect_home()
    _prepare_import_path()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve())


if __name__ == "__main__":
    main()
