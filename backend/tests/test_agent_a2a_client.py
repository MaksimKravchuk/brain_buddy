"""The six JSON-RPC calls BrainBuddy makes, and what each failure means.

This is the module that decides, for every way a stranger's server can answer,
which of three very different things BrainBuddy tells the user:

* **not sent** — nothing left BrainBuddy, so retrying is free;
* **delivery unconfirmed** — something may already be running at the agent, so a
  retry could start the work twice and a lookup must come first;
* **sent / observed** — the agent has it.

Collapsing any two of those is the failure this suite exists to prevent. A
timeout reported as "not sent" invites a duplicate; a definitive 4xx reported as
"unconfirmed" leaves a user staring at a run that never existed.

Everything else here follows from that: every call goes through the pinned
egress path so a rebinding answer cannot move it, bodies are bounded so an agent
cannot choose how much memory BrainBuddy spends, correlation ids are minted
server-side so a caller-supplied header can never become an input at the agent,
and structured logs carry codes rather than content.

014-FR-004, 014-FR-006, 014-FR-008, 014-SC-003, 014-SC-009.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from app.modules.agents.a2a.card import SINGLE_START_EXTENSION_URI
from app.modules.agents.a2a.client import (
    A2A_CREDENTIALS_REJECTED,
    A2A_RATE_LIMITED,
    A2A_REQUEST_REJECTED,
    A2A_RESPONSE_INVALID,
    A2A_RESPONSE_OVER_CAP,
    A2A_SERVER_ERROR,
    A2A_TIMEOUT,
    A2A_UNREACHABLE,
    OBSERVATION_CORRELATION_PREFIX,
    A2AClient,
    A2ATarget,
)
from app.modules.agents.a2a.types import TaskState

from .a2a_fakes import (
    DripFeedingAgent,
    guaranteed_tier_agent,
    helloworld_shaped_agent,
    running,
)

TARGET = A2ATarget(
    interface_url="https://agent.example.com/rpc",
    auth_scheme="bearer",
    auth_header_name=None,
    credential="super-secret-token",
)

API_KEY_TARGET = A2ATarget(
    interface_url="https://agent.example.com/rpc",
    auth_scheme="api_key",
    auth_header_name="X-Agent-Key",
    credential="super-secret-key",
)


def _resolver(host: str, port: int) -> list[str]:
    return {"agent.example.com": ["93.184.216.34"]}[host]


def _client(
    handler: Any,
    *,
    seen: list[httpx.Request] | None = None,
    max_response_bytes: int = 64_000,
    task_max_response_bytes: int = 262_144,
    allow_private_destinations: bool = False,
) -> A2AClient:
    def recording(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    def client_factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(recording), **kwargs)

    return A2AClient(
        timeout_seconds=10.0,
        reply_window_seconds=300,
        max_response_bytes=max_response_bytes,
        task_max_response_bytes=task_max_response_bytes,
        allow_private_destinations=allow_private_destinations,
        resolver=_resolver,
        client_factory=client_factory,
    )


def _bare_task_result(task_id: str = "task-1", context_id: str = "run-1") -> Any:
    """The shape both reference runtimes actually use for `GetTask`."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "id": task_id,
                    "contextId": context_id,
                    "status": {
                        "state": "TASK_STATE_COMPLETED",
                        "timestamp": "2026-08-09T12:00:00Z",
                        "message": {
                            "role": "ROLE_AGENT",
                            "parts": [{"text": "Done."}],
                        },
                    },
                },
            },
        )

    return handler


def test_014_FR_017_get_task_reads_a_task_returned_as_the_result_itself() -> None:
    """A2A 1.0 returns the Task *as* the result, not under a `task` key.

    Both vendored reference runtimes do exactly this — the a2a-sdk sample and
    the Hermes adapter — while `SendMessage` wraps its answer in `{"task": …}`.
    Reading only the wrapped shape means every scheduled observation comes back
    "the agent answered, but said nothing about this run", which is contact
    without news: a completed run would sit at **Running** forever and only a
    conformance test against a real server could catch it (014-FR-017).
    """

    client = _client(_bare_task_result())

    result = client.get_task(TARGET, task_id="task-1", context_id="run-1")

    assert result.ok
    assert result.task is not None
    assert result.task.id == "task-1"
    assert result.task.context_id == "run-1"
    assert result.task.status.state is TaskState.COMPLETED


def test_014_FR_006_an_empty_result_is_still_an_answer_with_no_task() -> None:
    """The negative case: a bare `{}` must not be coerced into a Task.

    `CancelTask` and an empty `ListTasks` both answer with an empty object, and
    inventing a task from one would attach a run to work that does not exist.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}}
        )

    result = _client(handler).get_task(TARGET, task_id="task-1")

    assert result.ok
    assert result.task is None
    assert result.tasks == ()


def _task_body(
    *,
    task_id: str = "task-1",
    context_id: str = "run-1",
    state: str = "TASK_STATE_WORKING",
    request_id: str | None = None,
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": request_id or payload["id"],
                "result": {
                    "task": {
                        "id": task_id,
                        "contextId": context_id,
                        "status": {"state": state},
                    }
                },
            },
        )

    return handler


def _error_body(code: int, *, status: int = 200) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if status != 200:
            return httpx.Response(status, json={"detail": "refused"})
        return httpx.Response(
            status,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "error": {"code": code, "message": "agent said so"},
            },
        )

    return handler


class TestRequestEnvelope:
    """What leaves BrainBuddy on every call."""

    def test_014_FR_004_every_call_goes_through_the_pinned_egress_path(self) -> None:
        """FR-004: one resolved address, the original hostname for TLS.

        Re-resolving between the check and the connect is the whole DNS
        rebinding class; pinning is what makes the destination decision
        binding rather than advisory.
        """

        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.send_message(TARGET, message={"messageId": "m", "contextId": "run-1"})

        assert len(seen) == 1
        request = seen[0]
        assert (
            request.url.host == "93.184.216.34"
        ), "the socket goes to the pinned address"
        assert request.headers["host"] == "agent.example.com"
        assert request.extensions["sni_hostname"] == "agent.example.com"

    def test_014_FR_004_a_private_destination_is_refused_before_the_credential_moves(
        self,
    ) -> None:
        """The credential must not reach an address BrainBuddy would not dial."""

        seen: list[httpx.Request] = []

        def client_factory(**kwargs: Any) -> httpx.Client:

            def handler(request: httpx.Request) -> httpx.Response:
                seen.append(request)
                return httpx.Response(200, json={})

            return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

        client = A2AClient(
            timeout_seconds=10.0,
            reply_window_seconds=300,
            max_response_bytes=64_000,
            task_max_response_bytes=262_144,
            allow_private_destinations=False,
            resolver=lambda host, port: ["169.254.169.254"],
            client_factory=client_factory,
        )

        result = client.get_task(TARGET, task_id="task-1")

        assert result.ok is False
        assert result.error_code is not None
        assert result.error_code.startswith("destination_")
        assert seen == []

    def test_014_FR_004_a_redirect_is_never_followed(self) -> None:
        """A credential-bearing request answered with a redirect has no
        legitimate need BrainBuddy must serve, and following it would be a
        one-hop bypass of every destination check above."""

        client = _client(
            lambda request: httpx.Response(302, headers={"location": "https://evil/"})
        )

        result = client.get_task(TARGET, task_id="task-1")

        assert result.ok is False
        assert result.error_code == "destination_redirect_not_allowed"

    def test_014_FR_004_the_wire_envelope_matches_the_contract(self) -> None:
        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.send_message(TARGET, message={"messageId": "m", "contextId": "run-1"})

        request = seen[0]
        assert request.headers["a2a-version"] == "1.0"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["accept"] == "application/json"
        assert request.headers["authorization"] == "Bearer super-secret-token"
        body = json.loads(request.content)
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "SendMessage"
        assert isinstance(body["id"], str) and body["id"]

    def test_014_FR_004_an_api_key_connection_uses_the_header_from_its_card(
        self,
    ) -> None:
        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.get_task(API_KEY_TARGET, task_id="task-1")

        assert seen[0].headers["x-agent-key"] == "super-secret-key"
        assert "authorization" not in {key.lower() for key in seen[0].headers}

    def test_014_FR_006_the_extension_header_travels_with_the_first_send(self) -> None:
        """The extension only obliges an agent to record the dedup key for a
        request that *activated* it, so activating on the first send — not just
        on replays — is what makes the guarantee real when it is needed."""

        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)
        guaranteed = A2ATarget(
            interface_url=TARGET.interface_url,
            auth_scheme="bearer",
            auth_header_name=None,
            credential=TARGET.credential,
            guarantee_tier="guaranteed",
        )

        client.send_message(
            guaranteed, message={"messageId": "run-1:start", "contextId": "run-1"}
        )

        request = seen[0]
        assert request.headers["a2a-extensions"] == SINGLE_START_EXTENSION_URI
        body = json.loads(request.content)
        assert body["params"]["message"]["extensions"] == [SINGLE_START_EXTENSION_URI]

    def test_014_FR_006_a_best_effort_agent_is_never_told_the_extension_is_active(
        self,
    ) -> None:
        """Activating an extension an agent never declared claims a guarantee
        it never made — and would make the tier shown to the user a fiction."""

        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.send_message(TARGET, message={"messageId": "m", "contextId": "run-1"})

        assert "a2a-extensions" not in {key.lower() for key in seen[0].headers}
        assert "extensions" not in json.loads(seen[0].content)["params"]["message"]

    def test_014_FR_004_a_tenant_is_echoed_only_when_the_card_declared_one(
        self,
    ) -> None:
        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)
        tenanted = A2ATarget(
            interface_url=TARGET.interface_url,
            auth_scheme="bearer",
            auth_header_name=None,
            credential=TARGET.credential,
            tenant="acme",
        )

        client.list_tasks(tenanted, context_id="run-1")
        client.list_tasks(TARGET, context_id="run-1")

        assert json.loads(seen[0].content)["params"]["tenant"] == "acme"
        assert "tenant" not in json.loads(seen[1].content)["params"]


class TestCorrelationIds:
    """Who chooses the id an agent sees."""

    def test_014_SC_009_every_call_carries_a_server_minted_correlation_id(self) -> None:
        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.get_task(TARGET, task_id="task-1")
        client.get_task(TARGET, task_id="task-1")

        first = seen[0].headers["x-correlation-id"]
        second = seen[1].headers["x-correlation-id"]
        assert first and second and first != second, "one id per call, not per client"

    def test_014_SC_009_a_scheduled_observation_is_labelled_as_one(self) -> None:
        """Support has to be able to tell a user-triggered call from a
        background one when reading an agent's logs beside BrainBuddy's."""

        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.get_task(TARGET, task_id="task-1", scheduled=True)

        assert (
            seen[0]
            .headers["x-correlation-id"]
            .startswith(OBSERVATION_CORRELATION_PREFIX)
        )

    @pytest.mark.parametrize(
        "inbound",
        [
            "x" * 10_000,
            "../../etc/passwd",
            "run-1\r\nX-Injected: yes",
            "'; DROP TABLE runs;--",
            "",
        ],
    )
    def test_014_SC_009_adversarial_inbound_correlation_id_never_reaches_the_outbound_request(
        self, inbound: str
    ) -> None:
        """Constitution Principle IV: a client-supplied id is an observability
        label, never an input.

        The inbound header is accepted verbatim by ``CorrelationIdMiddleware``
        because it is useful for tracing. Forwarding it would hand a caller a
        string that lands in a third party's logs, its header parser, and — if
        it were ever reused as a `contextId` — its dedup key. The outbound id is
        minted here and nowhere else.
        """

        from app.core.logging import reset_correlation_id, set_correlation_id

        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        token = set_correlation_id(inbound)
        try:
            client.get_task(TARGET, task_id="task-1")
        finally:
            reset_correlation_id(token)

        outbound = seen[0].headers["x-correlation-id"]
        assert outbound != inbound
        assert len(outbound) <= 64
        assert outbound.replace("_", "").isalnum()


class TestBoundedBodies:
    """How much memory an agent gets to make BrainBuddy spend."""

    def test_014_FR_008_a_card_sized_call_uses_the_small_cap(self) -> None:
        oversized = "x" * 200_000
        client = _client(
            lambda request: httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": json.loads(request.content)["id"],
                    "result": {"padding": oversized},
                },
            ),
            max_response_bytes=1_000,
            task_max_response_bytes=1_000_000,
        )

        result = client.cancel_task(TARGET, task_id="task-1")

        assert result.ok is False
        assert result.error_code == A2A_RESPONSE_OVER_CAP

    def test_014_FR_008_task_reads_get_the_larger_cap(self) -> None:
        """``GetTask`` has no ``includeArtifacts`` switch, so a completed task
        with artifacts legitimately exceeds the card cap. Applying the card cap
        to it would report healthy agents as broken."""

        body = {"padding": "x" * 5_000}
        client = _client(
            lambda request: httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": json.loads(request.content)["id"],
                    "result": {
                        "task": {
                            "id": "task-1",
                            "contextId": "run-1",
                            "status": {"state": "TASK_STATE_WORKING"},
                            "metadata": body,
                        }
                    },
                },
            ),
            max_response_bytes=1_000,
            task_max_response_bytes=100_000,
        )

        result = client.get_task(TARGET, task_id="task-1")

        assert result.ok is True
        assert result.task is not None

    def test_014_FR_008_an_over_cap_get_task_falls_back_to_list_tasks(self) -> None:
        """AC-013: the state is still observed, and the run is marked
        "too large" rather than drifting into "Stopped reporting".

        Blaming the agent for BrainBuddy's own byte budget would be a false
        claim about someone else's system — and the user's only recourse would
        be to chase a problem that is not there.
        """

        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            methods.append(payload["method"])
            if payload["method"] == "GetTask":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {"task": {"id": "t", "padding": "x" * 50_000}},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "tasks": [
                            {
                                "id": "task-1",
                                "contextId": "run-1",
                                "status": {"state": "TASK_STATE_COMPLETED"},
                            }
                        ]
                    },
                },
            )

        client = _client(handler, task_max_response_bytes=2_000)

        result = client.get_task(TARGET, task_id="task-1", context_id="run-1")

        assert methods == ["GetTask", "ListTasks"]
        assert result.ok is True
        assert result.task is not None
        assert result.task.status.state is TaskState.COMPLETED
        assert result.result_availability == "too_large"

    def test_014_FR_008_the_fallback_is_not_attempted_without_a_context_id(
        self,
    ) -> None:
        """``ListTasks`` is filtered by ``contextId``; without one the fallback
        would list another conversation's tasks and adopt a foreign task."""

        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            methods.append(payload["method"])
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"task": {"id": "t", "padding": "x" * 50_000}},
                },
            )

        client = _client(handler, task_max_response_bytes=2_000)

        result = client.get_task(TARGET, task_id="task-1")

        assert methods == ["GetTask"]
        assert result.ok is False
        assert result.error_code == A2A_RESPONSE_OVER_CAP


class TestResponseValidity:
    """What counts as an answer at all."""

    @pytest.mark.parametrize(
        "body",
        [
            "not json",
            "[]",
            '"string"',
            '{"jsonrpc": "2.0", "id": "1"}',
            '{"jsonrpc": "2.0", "id": "1", "result": {}, "error": {"code": -1}}',
        ],
        ids=["nonjson", "array", "string", "neither", "both"],
    )
    def test_014_FR_006_a_malformed_envelope_is_never_read_as_a_result(
        self, body: str
    ) -> None:
        """A body carrying both halves is not a partial success to salvage.

        BrainBuddy cannot tell which one the agent meant, and guessing on a
        hand-off is how a run acquires a state nobody reported. For a start
        exchange this becomes *delivery unconfirmed*, so the next step is a
        lookup rather than a resend.
        """

        client = _client(
            lambda request: httpx.Response(
                200, content=body, headers={"content-type": "application/json"}
            )
        )

        result = client.send_message(TARGET, message={"contextId": "run-1"})

        assert result.ok is False
        assert result.error_code == A2A_RESPONSE_INVALID

    def test_014_FR_006_a_mismatched_response_id_is_rejected(self) -> None:
        """A JSON-RPC answer that does not name the request it answers could
        belong to any call; accepting it would let a slow or muddled server
        settle the wrong exchange."""

        client = _client(_task_body(request_id="a-different-id"))

        result = client.send_message(TARGET, message={"contextId": "run-1"})

        assert result.ok is False
        assert result.error_code == A2A_RESPONSE_INVALID


class TestErrorMapping:
    """Every documented failure, mapped to the category the contract names."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            (-32001, "a2a_task_not_found"),
            (-32002, "a2a_not_cancelable"),
            (-32003, "a2a_push_unsupported"),
            (-32004, "a2a_unsupported_operation"),
            (-32005, "a2a_content_unsupported"),
            (-32006, "a2a_invalid_agent_response"),
            (-32007, "a2a_extended_card_not_configured"),
            (-32008, "a2a_extension_support_required"),
            (-32009, "a2a_version_not_supported"),
            (-32600, A2A_REQUEST_REJECTED),
            (-32602, A2A_REQUEST_REJECTED),
            (-32700, A2A_REQUEST_REJECTED),
            (-32601, "a2a_method_not_found"),
            (-32603, "a2a_internal_error"),
            (-32050, A2A_CREDENTIALS_REJECTED),
            (-32052, A2A_CREDENTIALS_REJECTED),
            (-32051, A2A_RATE_LIMITED),
        ],
    )
    def test_014_FR_006_each_jsonrpc_error_code_maps_to_its_own_category(
        self, code: int, expected: str
    ) -> None:
        """AC-018, AC-029: only an *explicit* agent answer may become a durable
        capability claim. `-32603` is internal and ambiguous, so it is mapped
        apart from `-32004`/`-32601` — a transient blip must never harden into
        "this agent does not support cancellation"."""

        client = _client(_error_body(code))

        result = client.cancel_task(TARGET, task_id="task-1")

        assert result.ok is False
        assert result.error_code == expected
        assert result.a2a_error_code == code

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, A2A_CREDENTIALS_REJECTED),
            (403, A2A_CREDENTIALS_REJECTED),
            (429, A2A_RATE_LIMITED),
            (500, A2A_SERVER_ERROR),
            (502, A2A_SERVER_ERROR),
            (503, A2A_SERVER_ERROR),
        ],
    )
    def test_014_FR_006_http_status_classes_map_before_the_body_is_trusted(
        self, status: int, expected: str
    ) -> None:
        client = _client(_error_body(0, status=status))

        result = client.get_task(TARGET, task_id="task-1")

        assert result.ok is False
        assert result.error_code == expected

    def test_014_FR_006_a_rate_limit_reports_when_to_try_again(self) -> None:
        """AC-037: without the retry hint the only honest thing the product can
        say is "try later", which is what makes users retry immediately."""

        client = _client(
            lambda request: httpx.Response(
                429, headers={"retry-after": "42"}, json={"detail": "slow down"}
            )
        )

        result = client.list_tasks(TARGET, context_id="run-1")

        assert result.error_code == A2A_RATE_LIMITED
        assert result.retry_after_seconds == 42

    @pytest.mark.parametrize("header", ["not-a-number", "", "-5", "999999999999"])
    def test_014_FR_006_a_nonsense_retry_after_is_dropped_not_guessed(
        self, header: str
    ) -> None:
        """Showing a fabricated countdown would be a claim the agent never
        made. Absent is honest; invented is not."""

        client = _client(
            lambda request: httpx.Response(
                429, headers={"retry-after": header}, json={"detail": "slow down"}
            )
        )

        result = client.list_tasks(TARGET, context_id="run-1")

        assert result.error_code == A2A_RATE_LIMITED
        assert result.retry_after_seconds is None

    def test_014_FR_006_a_transport_failure_is_unreachable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        client = _client(handler)

        result = client.get_task(TARGET, task_id="task-1")

        assert result.ok is False
        assert result.error_code == A2A_UNREACHABLE

    def test_014_FR_006_a_timeout_is_its_own_category(self) -> None:
        """A timeout is not "unreachable": the connection succeeded and the
        message may already be at the agent. That distinction is what keeps a
        start exchange out of "not sent"."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        client = _client(handler)

        result = client.send_message(TARGET, message={"contextId": "run-1"})

        assert result.ok is False
        assert result.error_code == A2A_TIMEOUT

    def test_014_FR_006_the_credential_never_appears_in_a_failure(self) -> None:
        """SC-009: an error is a surface, and secrets do not belong on it."""

        client = _client(
            lambda request: httpx.Response(
                401, json={"detail": "bad token super-secret-token"}
            )
        )

        result = client.get_task(TARGET, task_id="task-1")

        rendered = repr(result)
        assert "super-secret-token" not in rendered
        assert result.error_code == A2A_CREDENTIALS_REJECTED


class TestOperationShapes:
    """The params each operation puts on the wire."""

    def test_014_FR_006_send_message_carries_only_proto_defined_fields(self) -> None:
        """The a2a-sdk server rejects unknown params outright, so a stray field
        does not degrade — it fails the hand-off."""

        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.send_message(
            TARGET,
            message={
                "messageId": "run-1:start",
                "contextId": "run-1",
                "role": "ROLE_USER",
                "parts": [{"text": "title"}],
            },
            push_config={
                "url": "https://bb.example/api/a2a/push/run-1/tok",
                "token": "tok",
            },
        )

        params = json.loads(seen[0].content)["params"]
        assert set(params) <= {"message", "configuration", "tenant"}
        assert params["configuration"]["taskPushNotificationConfig"]["token"] == "tok"

    def test_014_FR_006_get_task_asks_for_no_history_by_default(self) -> None:
        """History is agent text BrainBuddy has not been asked to store; it is
        fetched only when the observed state actually needs it."""

        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.get_task(TARGET, task_id="task-1")
        client.get_task(TARGET, task_id="task-1", history_length=20)

        assert json.loads(seen[0].content)["params"] == {
            "id": "task-1",
            "historyLength": 0,
        }
        assert json.loads(seen[1].content)["params"]["historyLength"] == 20

    def test_014_FR_006_list_tasks_filters_by_the_run_id(self) -> None:
        seen: list[httpx.Request] = []
        client = _client(
            lambda request: httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": json.loads(request.content)["id"],
                    "result": {"tasks": []},
                },
            ),
            seen=seen,
        )

        client.list_tasks(TARGET, context_id="run-1", page_size=5)

        assert json.loads(seen[0].content)["params"] == {
            "contextId": "run-1",
            "pageSize": 5,
            "includeArtifacts": False,
            "historyLength": 0,
        }

    def test_014_FR_006_cancel_carries_the_command_id_as_metadata(self) -> None:
        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)

        client.cancel_task(TARGET, task_id="task-1", command_id="cmd-9")

        params = json.loads(seen[0].content)["params"]
        assert params["id"] == "task-1"
        assert params["metadata"]["brainbuddy.command_id"] == "cmd-9"

    def test_014_FR_008_push_registration_sends_the_per_run_url_and_token(self) -> None:
        seen: list[httpx.Request] = []
        client = _client(
            lambda request: httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": json.loads(request.content)["id"],
                    "result": {"config": {}},
                },
            ),
            seen=seen,
        )

        client.create_push_config(
            TARGET,
            task_id="task-1",
            url="https://bb.example/api/a2a/push/run-1/tok",
            token="tok",
        )

        body = json.loads(seen[0].content)
        assert body["method"] == "CreateTaskPushNotificationConfig"
        assert body["params"] == {
            "taskId": "task-1",
            "url": "https://bb.example/api/a2a/push/run-1/tok",
            "token": "tok",
        }


class TestStructuredLogging:
    """What a log line is allowed to say about someone else's agent."""

    def test_014_SC_009_logs_carry_codes_and_ids_but_never_content(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Decision K's allowlist. Agent text, card bodies, message parts,
        credentials and push tokens are all absent by construction rather than
        by redaction — nothing puts them in a record in the first place."""

        client = _client(
            lambda request: httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": json.loads(request.content)["id"],
                    "result": {
                        "task": {
                            "id": "task-1",
                            "contextId": "run-1",
                            "status": {
                                "state": "TASK_STATE_COMPLETED",
                                "message": {
                                    "role": "ROLE_AGENT",
                                    "parts": [{"text": "PRIVATE-AGENT-OUTPUT"}],
                                },
                            },
                        }
                    },
                },
            )
        )

        with caplog.at_level(logging.INFO, logger="app.modules.agents.a2a.client"):
            client.get_task(TARGET, task_id="task-1", run_id="run-1")

        messages = [record.getMessage() for record in caplog.records]
        assert messages, "an outbound call must be observable"
        joined = "\n".join(messages)
        assert "PRIVATE-AGENT-OUTPUT" not in joined
        assert "super-secret-token" not in joined
        assert "GetTask" in joined
        assert "run-1" in joined

    def test_014_SC_009_an_unknown_error_code_is_logged_as_other(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An agent-chosen integer in a log field is unbounded cardinality and
        a small injection surface; the allowlist collapses it."""

        client = _client(_error_body(-99999))

        with caplog.at_level(logging.INFO, logger="app.modules.agents.a2a.client"):
            client.get_task(TARGET, task_id="task-1")

        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "a2a_error_code=other" in joined
        assert "-99999" not in joined


class TestAgainstLoopbackAgents:
    """The behaviours only a real socket can show."""

    @staticmethod
    def _loopback_client(**kwargs: Any) -> A2AClient:
        return A2AClient(
            timeout_seconds=5.0,
            reply_window_seconds=300,
            max_response_bytes=64_000,
            task_max_response_bytes=262_144,
            allow_private_destinations=True,
            **kwargs,
        )

    def test_014_FR_006_a_replay_to_a_guaranteed_agent_returns_the_original_task(
        self,
    ) -> None:
        """SC-002: three identical sends, one task at the agent.

        This is the whole promise the "Guaranteed single start" label makes to
        a user, proved against an agent that refuses to dedup unless the client
        actually activated the extension.
        """

        with running(guaranteed_tier_agent()) as agent:
            client = self._loopback_client()
            target = A2ATarget(
                interface_url=agent.interface_url,
                auth_scheme="bearer",
                auth_header_name=None,
                credential=None,
                guarantee_tier="guaranteed",
            )
            message = {
                "messageId": "run-1:start",
                "contextId": "run-1",
                "role": "ROLE_USER",
                "parts": [{"text": "do the thing"}],
            }

            ids = [
                client.send_message(target, message=dict(message)).task.id
                for _ in range(3)
            ]

        assert len(set(ids)) == 1
        assert agent.task_count == 1

    def test_014_FR_006_a_best_effort_agent_creates_a_task_per_send(self) -> None:
        """The honest counterpart: without the extension a replay really can
        start the work twice, which is exactly what the best-effort disclosure
        tells the user before they confirm."""

        with running(helloworld_shaped_agent()) as agent:
            client = self._loopback_client()
            target = A2ATarget(
                interface_url=agent.interface_url,
                auth_scheme="bearer",
                auth_header_name=None,
                credential=None,
            )
            message = {"messageId": "run-1:start", "contextId": "run-1"}

            ids = [
                client.send_message(target, message=dict(message)).task.id
                for _ in range(3)
            ]

        assert len(set(ids)) == 3

    def test_014_FR_008_a_drip_feeding_agent_trips_the_absolute_deadline(self) -> None:
        """The failure mode no configured limit catches.

        Every chunk restarts httpx's read timeout and the body stays far under
        the byte cap, so without the wall-clock deadline this request holds a
        bounded exchange worker open indefinitely.
        """

        agent = DripFeedingAgent(interval_seconds=0.01)
        with running(agent):
            client = self._loopback_client()
            target = A2ATarget(
                interface_url=agent.interface_url,
                auth_scheme="bearer",
                auth_header_name=None,
                credential=None,
            )

            result = client.get_task(target, task_id="task-1", deadline_seconds=0.5)

        assert result.ok is False
        assert result.error_code == A2A_TIMEOUT


class TestAnswerEdges:
    """Answers that are well-formed HTTP and still tell BrainBuddy nothing.

    Each of these ends in the same place — the observation is not accepted —
    and the value under test is which code says so, because that code is what
    later decides whether a retry is safe.

    014-FR-004, 014-FR-006, 014-FR-008.
    """

    def test_014_FR_006_an_over_cap_task_with_no_findable_task_stays_over_cap(
        self,
    ) -> None:
        """The fallback either finds the task or changes nothing.

        An empty `ListTasks` is not evidence that the task is gone — the read
        was refused for size, not answered — so the original over-cap failure is
        what the caller is told. Reporting "no such task" here would let a byte
        cap look like the agent having dropped the run.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if payload["method"] == "ListTasks":
                return httpx.Response(
                    200,
                    json={"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                )
            return httpx.Response(200, json={"result": "x" * 400_000})

        client = _client(handler, task_max_response_bytes=1_024)

        result = client.get_task(TARGET, task_id="task-1", context_id="run-1")

        assert result.ok is False
        assert result.error_code == A2A_RESPONSE_OVER_CAP
        assert result.result_availability is None

    def test_014_FR_006_listing_without_a_conversation_sends_no_context_id(
        self,
    ) -> None:
        """The connection test lists tasks to prove the credential works.

        It has no run to ask about, so it must not invent a `contextId`: sending
        one would silently scope the probe to a conversation that does not
        exist, and an empty answer would then be read as a working credential
        when it proved nothing.
        """

        seen: list[httpx.Request] = []
        client = _client(
            lambda request: httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": json.loads(request.content)["id"],
                    "result": {"tasks": []},
                },
            ),
            seen=seen,
        )

        result = client.list_tasks(TARGET)

        assert result.ok is True
        assert "contextId" not in json.loads(seen[0].content)["params"]

    def test_014_FR_004_an_api_key_target_without_a_header_name_sends_no_credential(
        self,
    ) -> None:
        """A credential with nowhere to go is not put somewhere.

        The header name comes from the agent's own card, so it is absent exactly
        when discovery has not established one. Falling back to `Authorization`
        would send the user's key to a scheme the agent never offered.
        """

        seen: list[httpx.Request] = []
        client = _client(_task_body(), seen=seen)
        target = A2ATarget(
            interface_url="https://agent.example.com/rpc",
            auth_scheme="api_key",
            auth_header_name=None,
            credential="super-secret-key",
        )

        client.get_task(target, task_id="task-1")

        headers = seen[0].headers
        assert "authorization" not in headers
        assert "super-secret-key" not in json.dumps(dict(headers))

    def test_014_FR_006_a_plain_4xx_is_a_rejected_request_not_a_lost_one(
        self,
    ) -> None:
        """A 400 is definitive, and that is the whole point of separating it.

        The agent parsed the request and refused it, so nothing is running and a
        retry is free. Folding this into the server-error class would leave the
        run **Delivery unconfirmed** and demand a lookup before every retry.
        """

        client = _client(_error_body(0, status=400))

        result = client.get_task(TARGET, task_id="task-1")

        assert result.ok is False
        assert result.error_code == A2A_REQUEST_REJECTED
        assert result.http_status == 400

    def test_014_FR_006_a_result_whose_task_does_not_parse_is_response_invalid(
        self,
    ) -> None:
        """A JSON-RPC success carrying a task BrainBuddy cannot read.

        Accepting the envelope and dropping the task would advance the run's
        version on an observation that established nothing, and the next real
        answer would then be rejected as a straggler.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"task": {"id": "task-1", "status": "not-an-object"}},
                },
            )

        client = _client(handler)

        result = client.get_task(TARGET, task_id="task-1")

        assert result.ok is False
        assert result.error_code == A2A_RESPONSE_INVALID
        assert result.task is None
