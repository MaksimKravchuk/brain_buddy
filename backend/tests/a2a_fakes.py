"""Loopback A2A agents, for the behaviours the vendored runtimes cannot show.

The two vendored reference runtimes (``backend/vendor/``) are what prove
BrainBuddy's client works against real third-party code. They cannot, however,
be made to misbehave on demand: neither implements the single-start extension,
neither can be told to drip-feed a response one byte at a time, and neither will
hold a request open on a barrier so a concurrency test can interleave two
callers deterministically. These fakes exist for exactly those cases, and for
nothing the real runtimes already cover.

Each one is a ``ThreadingHTTPServer`` on loopback — the pattern Hermes' own
plugin tests use — serving a card at ``/.well-known/agent-card.json`` and
JSON-RPC at ``/``. They bind port 0, so parallel test lanes never collide.

Used with ``BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS`` / the
``allow_private_destinations`` egress opt-in, which is the governed private
class and test-only.

014-SC-002, 014-SC-008, 014-FR-006, 014-FR-007.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.modules.agents.a2a.card import (
    SINGLE_START_EXTENSION_URI,
    AgentAuthSchemeOffer,
    AgentCardSummary,
    AgentSkillSummary,
    CardDiscovery,
    card_fingerprint,
)
from app.modules.agents.a2a.client import A2AResult, A2ATarget

EXTENSION_HEADER = "A2A-Extensions"

TASK_SUBMITTED = "TASK_STATE_SUBMITTED"
TASK_WORKING = "TASK_STATE_WORKING"
TASK_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
TASK_COMPLETED = "TASK_STATE_COMPLETED"
TASK_FAILED = "TASK_STATE_FAILED"

MAX_REQUEST_BYTES = 4 * 1024 * 1024


@dataclass
class RecordedCall:
    """One JSON-RPC call, as the agent saw it."""

    method: str
    params: dict[str, Any]
    headers: dict[str, str]

    @property
    def message(self) -> dict[str, Any]:
        message = self.params.get("message")
        return message if isinstance(message, dict) else {}

    @property
    def context_id(self) -> str | None:
        return self.message.get("contextId")

    @property
    def message_id(self) -> str | None:
        return self.message.get("messageId")

    @property
    def carries_content(self) -> bool:
        """Whether this call could have started or advanced work at the agent.

        Only ``SendMessage`` can. The whole point of
        ``test_no_background_thread_ever_sends_content`` is to count these and
        find zero, so "content-bearing" is defined once, here.
        """

        return self.method == "SendMessage"


class FakeA2AAgent:
    """A configurable loopback A2A agent.

    Deliberately one class with flags rather than a hierarchy: every flag below
    corresponds to a behaviour some real runtime has, and keeping them in one
    place makes the differences between the runtimes readable side by side
    instead of scattered across subclasses.
    """

    def __init__(
        self,
        *,
        declares_extension: bool = False,
        dedup: bool = False,
        require_extension_header_for_dedup: bool = True,
        list_tasks_returns_empty: bool = False,
        foreign_context_id: str | None = None,
        push_notifications: bool = False,
        legacy_card_shape: bool = False,
        reply_state: str = TASK_COMPLETED,
        reply_delay_seconds: float = 0.0,
        barrier: threading.Barrier | None = None,
        error_for_method: dict[str, dict[str, Any]] | None = None,
        http_status_for_method: dict[str, int] | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self.declares_extension = declares_extension
        self.dedup = dedup
        self.require_extension_header_for_dedup = require_extension_header_for_dedup
        self.list_tasks_returns_empty = list_tasks_returns_empty
        self.foreign_context_id = foreign_context_id
        self.push_notifications = push_notifications
        self.legacy_card_shape = legacy_card_shape
        self.reply_state = reply_state
        self.reply_delay_seconds = reply_delay_seconds
        self.barrier = barrier
        self.error_for_method = error_for_method or {}
        self.http_status_for_method = http_status_for_method or {}
        self.bearer_token = bearer_token
        #: A socket that answers but serves no card is `a2a_not_an_agent`, which
        #: is a different product category from "unreachable" and needs its own
        #: fake.
        self.serves_card = True

        self.calls: list[RecordedCall] = []
        self.card_fetches = 0
        self._tasks: dict[str, dict[str, Any]] = {}
        self._by_dedup_key: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # --- lifecycle ---------------------------------------------------------

    @property
    def port(self) -> int:
        assert self._server is not None, "the fake agent is not running"
        return int(self._server.server_address[1])

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def interface_url(self) -> str:
        return f"{self.origin}/"

    def start(self) -> FakeA2AAgent:
        agent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                """Silence: the suite's own log is the evidence, not this one."""

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if self.path.startswith("/.well-known/agent-card.json"):
                    agent.card_fetches += 1
                    if not agent.serves_card:
                        agent._respond(self, 404, {"error": "not found"})
                        return
                    agent._respond(self, 200, agent.card())
                    return
                agent._respond(self, 404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                agent._handle_rpc(self)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-a2a", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # --- the card ----------------------------------------------------------

    def card(self) -> dict[str, Any]:
        capabilities: dict[str, Any] = {
            "streaming": False,
            "pushNotifications": self.push_notifications,
        }
        if self.declares_extension:
            capabilities["extensions"] = [
                {
                    "uri": SINGLE_START_EXTENSION_URI,
                    "description": "Deduplicates by (contextId, messageId).",
                    "required": False,
                }
            ]
        card: dict[str, Any] = {
            "name": "Fake A2A Agent",
            "version": "1.0.0",
            "description": "A loopback agent for BrainBuddy's own tests.",
            "supportedInterfaces": [
                {
                    "url": self.interface_url,
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                }
            ],
            "capabilities": capabilities,
            "skills": [],
        }
        if self.legacy_card_shape:
            # What Hermes actually serves: a flat security scheme, an unknown
            # capability field, and the legacy `security` key.
            card["securitySchemes"] = {"bearer": {"type": "http", "scheme": "bearer"}}
            card["security"] = [{"bearer": []}]
            capabilities["stateTransitionHistory"] = False
        else:
            card["securitySchemes"] = {
                "bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}}
            }
            card["securityRequirements"] = [{"bearer": []}]
        return card

    # --- JSON-RPC ----------------------------------------------------------

    def _respond(
        self, handler: BaseHTTPRequestHandler, status: int, payload: Any
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _handle_rpc(self, handler: BaseHTTPRequestHandler) -> None:
        length = min(int(handler.headers.get("Content-Length") or 0), MAX_REQUEST_BYTES)
        raw = handler.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw)
        except ValueError:
            self._respond(handler, 200, _rpc_error(None, -32700, "parse error"))
            return

        method = str(request.get("method") or "")
        params = request.get("params") or {}
        request_id = request.get("id")
        headers = {key.lower(): value for key, value in handler.headers.items()}

        if (
            self.bearer_token is not None
            and headers.get("authorization") != f"Bearer {self.bearer_token}"
        ):
            self._respond(handler, 401, _rpc_error(request_id, -32050, "unauthorized"))
            return

        with self._lock:
            self.calls.append(RecordedCall(method, params, headers))

        status = self.http_status_for_method.get(method)
        if status is not None and status != 200:
            self._respond(handler, status, {"detail": "refused"})
            return

        error = self.error_for_method.get(method)
        if error is not None:
            self._respond(
                handler,
                200,
                _rpc_error(request_id, error["code"], error.get("message", "")),
            )
            return

        if self.barrier is not None:
            # Deterministic interleaving for the SC-008 barrier cases: two
            # callers meet here, so neither can win by being faster.
            self.barrier.wait(timeout=10)

        if self.reply_delay_seconds:
            time.sleep(self.reply_delay_seconds)

        handlers: dict[str, Callable[[Any, dict[str, Any]], dict[str, Any]]] = {
            "SendMessage": self._send_message,
            "GetTask": self._get_task,
            "ListTasks": self._list_tasks,
            "CancelTask": self._cancel_task,
            "CreateTaskPushNotificationConfig": self._register_push,
        }
        operation = handlers.get(method)
        if operation is None:
            self._respond(
                handler, 200, _rpc_error(request_id, -32601, "method not found")
            )
            return
        self._respond(handler, 200, operation(request_id, params))

    def _next_task_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"task-{self._counter}"

    def _send_message(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        message = params.get("message") or {}
        context_id = message.get("contextId") or "ctx"
        message_id = message.get("messageId") or ""
        activated = SINGLE_START_EXTENSION_URI in (message.get("extensions") or [])

        if self.dedup:
            # The extension's whole promise is that a *replay* returns the
            # original task. Refusing to dedup when the activation header is
            # absent is what makes the client's obligation testable: an agent
            # that deduped anyway would hide a client that forgot to activate.
            header_present = any(
                SINGLE_START_EXTENSION_URI in call.headers.get("a2a-extensions", "")
                for call in self.calls
            )
            may_dedup = activated or header_present
            if self.require_extension_header_for_dedup and not may_dedup:
                may_dedup = False
            key = (context_id, message_id)
            if may_dedup:
                with self._lock:
                    existing = self._by_dedup_key.get(key)
                if existing is not None:
                    return _rpc_result(request_id, {"task": self._tasks[existing]})

        task_id = self._next_task_id()
        task = _task_payload(
            task_id,
            self.foreign_context_id or context_id,
            self.reply_state,
            "Fake agent reply.",
        )
        with self._lock:
            self._tasks[task_id] = task
            if self.dedup:
                self._by_dedup_key[(context_id, message_id)] = task_id
        return _rpc_result(request_id, {"task": task})

    def _get_task(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        task = self._tasks.get(str(params.get("id") or ""))
        if task is None:
            return _rpc_error(request_id, -32001, "task not found")
        return _rpc_result(request_id, {"task": task})

    def _list_tasks(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if self.list_tasks_returns_empty:
            return _rpc_result(request_id, {"tasks": []})
        context_id = params.get("contextId")
        with self._lock:
            tasks = [
                task
                for task in self._tasks.values()
                if context_id is None or task["contextId"] == context_id
            ]
        return _rpc_result(request_id, {"tasks": tasks})

    def _cancel_task(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        task = self._tasks.get(str(params.get("id") or ""))
        if task is None:
            return _rpc_error(request_id, -32001, "task not found")
        task["status"]["state"] = "TASK_STATE_CANCELED"
        return _rpc_result(request_id, {"task": task})

    def _register_push(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self.push_notifications:
            return _rpc_error(request_id, -32003, "push not supported")
        return _rpc_result(request_id, {"config": dict(params)})

    # --- assertions the suites share ---------------------------------------

    @property
    def content_bearing_calls(self) -> list[RecordedCall]:
        """Every call that could have started or advanced work at the agent."""

        return [call for call in self.calls if call.carries_content]

    def calls_to(self, method: str) -> list[RecordedCall]:
        return [call for call in self.calls if call.method == method]

    @property
    def task_count(self) -> int:
        with self._lock:
            return len(self._tasks)


class DripFeedingAgent:
    """An agent that answers one byte per interval, forever.

    This is the shape no configured limit catches: every chunk restarts httpx's
    read timeout, so the request never "times out", and the body stays far under
    any byte cap, so it never trips the budget either. Only the absolute
    wall-clock deadline closes it.
    """

    def __init__(self, *, interval_seconds: float = 0.01) -> None:
        self.interval_seconds = interval_seconds
        self.bytes_sent = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.server_address[1])

    @property
    def interface_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> DripFeedingAgent:
        agent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                """Silence."""

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(min(length, MAX_REQUEST_BYTES))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                # No Content-Length: the point is a body that never ends.
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    while True:
                        self.wfile.write(b"1\r\n{\r\n")
                        self.wfile.flush()
                        agent.bytes_sent += 1
                        time.sleep(agent.interval_seconds)
                except (BrokenPipeError, ConnectionResetError, ValueError):
                    # The client closed the stream, which is the whole point.
                    return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-a2a-drip", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


@dataclass
class BlockingA2AAgent:
    """A barrier port for the SC-008 contention cases.

    Two callers reaching the agent meet at the barrier, so neither can win by
    being faster and the test proves the *lock* converges them rather than the
    scheduler happening to.
    """

    parties: int = 2
    timeout_seconds: float = 10.0
    released: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self.barrier = threading.Barrier(self.parties)

    def agent(self, **kwargs: Any) -> FakeA2AAgent:
        return FakeA2AAgent(barrier=self.barrier, **kwargs)


# --- helpers -----------------------------------------------------------------


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _task_payload(
    task_id: str, context_id: str, state: str, text: str
) -> dict[str, Any]:
    return {
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": state,
            "timestamp": "2026-09-04T12:00:00Z",
            "message": {
                "role": "ROLE_AGENT",
                "parts": [{"text": text, "mediaType": "text/plain"}],
            },
        },
        "artifacts": [],
    }


@contextmanager
def running(agent: FakeA2AAgent | DripFeedingAgent) -> Iterator[Any]:
    """Start an agent and guarantee its teardown.

    A leaked ``ThreadingHTTPServer`` holds a port and a thread for the rest of
    the session, so teardown is a context manager rather than a convention.
    """

    started = agent.start()
    try:
        yield started
    finally:
        agent.stop()


def guaranteed_tier_agent(**kwargs: Any) -> FakeA2AAgent:
    """An agent that declares the single-start extension and honours it."""

    kwargs.setdefault("declares_extension", True)
    kwargs.setdefault("dedup", True)
    return FakeA2AAgent(**kwargs)


def hermes_shaped_agent(**kwargs: Any) -> FakeA2AAgent:
    """Blocking send, a new task per message, no dedup, legacy card shape."""

    kwargs.setdefault("legacy_card_shape", True)
    kwargs.setdefault("push_notifications", True)
    return FakeA2AAgent(**kwargs)


def helloworld_shaped_agent(**kwargs: Any) -> FakeA2AAgent:
    """Blocking send, a new task per message, no dedup, no push capability."""

    return FakeA2AAgent(**kwargs)


def recording_agent(**kwargs: Any) -> FakeA2AAgent:
    """An agent whose only job is to count content-bearing sends.

    ``test_no_background_thread_ever_sends_content`` asserts that number is
    zero after the scheduler, the observation pool, restart recovery and the
    retention sweep have all run.
    """

    return FakeA2AAgent(**kwargs)


def foreign_context_agent(foreign_context_id: str = "not-your-run", **kwargs: Any):
    """An agent that ignores the client ``contextId`` and assigns its own.

    BrainBuddy must notice and never resend for such a connection: an empty
    lookup there proves nothing, so a resend could start the work twice.
    """

    kwargs.setdefault("foreign_context_id", foreign_context_id)
    return FakeA2AAgent(**kwargs)


# --- in-process doubles for the service's two ports --------------------------
#
# The loopback servers above prove the *client* works against real HTTP. These
# prove the *service* works against a scripted wire, with no socket, no thread
# and no sleep, which is what lets its state machines be driven exhaustively
# rather than only along their happy paths.


class FakeCardFetcher:
    """Discovery as one scriptable call (spec 014, FR-002).

    The service reaches the agent card through a single injected port, so a test
    can hand it a `CardDiscovery` directly instead of standing up a socket. The
    two cases that genuinely need HTTP — a malformed body and an over-cap one —
    drive the *real* `fetch_card` through `httpx.MockTransport` instead.
    """

    def __init__(self) -> None:
        self.discovery = ready_discovery()
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self,
        address: str,
        *,
        auth_scheme: str,
        now: datetime | None = None,
    ) -> CardDiscovery:
        self.calls.append((address, auth_scheme))
        return self.discovery


def card_summary(**overrides: Any) -> AgentCardSummary:
    payload: dict[str, Any] = {
        "name": "Hermes",
        "version": "1.2.3",
        "description": "A research agent.",
        "protocol_version": "1.0",
        "interface_url": "https://agent.example.com/a2a",
        "streaming": True,
        "push_notifications": False,
        "skills": [AgentSkillSummary(id="research", name="Research")],
        "auth_schemes_offered": [AgentAuthSchemeOffer(name="bearer", kind="bearer")],
        "security_required": True,
        "extension_uris": [],
        "security_requirements": [["bearer"]],
        "fetched_at": datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    }
    payload.update(overrides)
    return AgentCardSummary(**payload)


def ready_discovery(**overrides: Any) -> CardDiscovery:
    """A discovery result a bearer connection can be tested against."""

    summary = overrides.pop("summary", None) or card_summary()
    payload: dict[str, Any] = {
        "summary": summary,
        "interface_url": summary.interface_url,
        "auth_header_name": None,
        "guarantee_tier": (
            "guaranteed"
            if SINGLE_START_EXTENSION_URI in summary.extension_uris
            else "best_effort"
        ),
        "card_fingerprint": card_fingerprint(summary),
    }
    payload.update(overrides)
    return CardDiscovery(**payload)


class FakeA2AClient:
    """A scriptable `A2AClientPort` that never opens a socket."""

    def __init__(self) -> None:
        self.results: dict[str, list[A2AResult]] = {}
        self.calls: list[tuple[str, A2ATarget, dict[str, Any]]] = []

    def script(self, method: str, *results: A2AResult) -> None:
        self.results[method] = list(results)

    def _answer(self, method: str, target: A2ATarget, **kwargs: Any) -> A2AResult:
        self.calls.append((method, target, kwargs))
        queued = self.results.get(method)
        if not queued:
            return A2AResult(ok=True, correlation_id="corr")
        return queued.pop(0) if len(queued) > 1 else queued[0]

    def send_message(self, target: A2ATarget, **kwargs: Any) -> A2AResult:
        return self._answer("SendMessage", target, **kwargs)

    def get_task(self, target: A2ATarget, **kwargs: Any) -> A2AResult:
        return self._answer("GetTask", target, **kwargs)

    def list_tasks(self, target: A2ATarget, **kwargs: Any) -> A2AResult:
        return self._answer("ListTasks", target, **kwargs)

    def cancel_task(self, target: A2ATarget, **kwargs: Any) -> A2AResult:
        return self._answer("CancelTask", target, **kwargs)

    def create_push_config(self, target: A2ATarget, **kwargs: Any) -> A2AResult:
        return self._answer("CreateTaskPushNotificationConfig", target, **kwargs)

    def calls_to(self, method: str) -> list[tuple[str, A2ATarget, dict[str, Any]]]:
        return [call for call in self.calls if call[0] == method]


def _serve_forever() -> None:  # pragma: no cover - exercised as a subprocess
    """Run one fake agent until the parent kills it.

    The mobile integration harness needs a *real* agent on a real socket: it
    drives the shipped TypeScript client against a real backend, so a
    Python-side double would prove nothing about that path. This entry point is
    what that harness spawns. It prints the chosen port on stdout as its ready
    signal — the port is bound to 0, so the parent cannot know it in advance and
    a fixed one would collide with a parallel lane.
    """

    import argparse
    import signal

    parser = argparse.ArgumentParser(description="A loopback A2A agent for tests.")
    parser.add_argument("--bearer-token", default=None)
    parser.add_argument("--declares-extension", action="store_true")
    parser.add_argument("--dedup", action="store_true")
    parser.add_argument("--push-notifications", action="store_true")
    parser.add_argument("--legacy-card-shape", action="store_true")
    parser.add_argument(
        "--not-an-agent",
        action="store_true",
        help="Serve no card at the well-known location.",
    )
    args = parser.parse_args()

    agent = FakeA2AAgent(
        bearer_token=args.bearer_token,
        declares_extension=args.declares_extension,
        dedup=args.dedup,
        push_notifications=args.push_notifications,
        legacy_card_shape=args.legacy_card_shape,
    )
    if args.not_an_agent:
        # A socket that answers but has no card is its own product category
        # (`a2a_not_an_agent`), and the harness has to be able to produce it.
        agent.serves_card = False
    agent.start()
    print(f"PORT={agent.port}", flush=True)

    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    try:
        stopping.wait()
    finally:
        agent.stop()


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    _serve_forever()


__all__ = [
    "EXTENSION_HEADER",
    "A2AResult",
    "A2ATarget",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "TASK_INPUT_REQUIRED",
    "TASK_SUBMITTED",
    "TASK_WORKING",
    "BlockingA2AAgent",
    "DripFeedingAgent",
    "FakeA2AAgent",
    "FakeA2AClient",
    "FakeCardFetcher",
    "RecordedCall",
    "card_summary",
    "foreign_context_agent",
    "guaranteed_tier_agent",
    "helloworld_shaped_agent",
    "hermes_shaped_agent",
    "ready_discovery",
    "recording_agent",
    "running",
]
