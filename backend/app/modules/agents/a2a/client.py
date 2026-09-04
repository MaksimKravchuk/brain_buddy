"""The six A2A JSON-RPC calls BrainBuddy makes, over pinned egress.

Every method here answers one question for its caller: **did anything leave
BrainBuddy, and could it already be running at the agent?** Three outcomes, and
collapsing any two of them is the failure this module exists to prevent:

* *not sent* — a definitive refusal before the agent could act. Retrying is
  free.
* *unconfirmed* — a timeout, a 5xx, a transport loss, a malformed answer. The
  message may already be at the agent, so the next step is a **lookup**, never a
  resend.
* *sent* — the agent answered with a task or a message.

A timeout reported as "not sent" invites a duplicate hand-off; a definitive 4xx
reported as "unconfirmed" leaves a user waiting on a run that never existed.
That is why the error table below is explicit rather than a fallback chain, and
why :class:`A2AResult` carries a category rather than an exception message.

Three further properties, each a deliberate refusal to be convenient:

* **Pinning.** Every call goes through ``validate_destination`` +
  ``pinned_request``: one resolved address, the original hostname for TLS, no
  redirects. This is why the client is hand-written rather than built on
  ``a2a-sdk``, whose transport builds its own request on an async client
  (research.md Decision A).
* **Server-minted correlation ids.** The id an agent sees is generated here,
  never taken from the inbound header a caller supplied. A forwarded id would
  land in a third party's logs and header parser at a stranger's choosing.
* **Bounded bodies, with one considered exception.** Task reads get a larger cap
  than card reads because ``GetTask`` has no ``includeArtifacts`` switch; when
  even that is exceeded the call falls back to ``ListTasks`` so the *state* is
  still observed and the run is marked "too large" rather than drifting into
  "Stopped reporting" — which would blame the agent for BrainBuddy's budget.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from app.core.logging import get_logger
from app.modules.agents.a2a.card import (
    SINGLE_START_EXTENSION_URI,
    AuthScheme,
    GuaranteeTier,
)
from app.modules.agents.a2a.types import (
    CONTENT_TYPE_NOT_SUPPORTED,
    EXTENDED_CARD_NOT_CONFIGURED,
    EXTENSION_SUPPORT_REQUIRED,
    INTERNAL_ERROR,
    INVALID_AGENT_RESPONSE,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PUSH_NOTIFICATION_NOT_SUPPORTED,
    RATE_LIMITED,
    TASK_NOT_CANCELABLE,
    TASK_NOT_FOUND,
    UNAUTHORIZED,
    UNSUPPORTED_OPERATION,
    UNTRUSTED,
    VERSION_NOT_SUPPORTED,
    JsonRpcResponse,
    Message,
    Task,
    loggable_error_code,
)
from app.modules.agents.egress import (
    DestinationRejected,
    EgressDeadlineExceeded,
    Resolver,
    pinned_request,
    validate_destination,
)

logger = get_logger(__name__)

A2A_VERSION = "1.0"
EXTENSION_HEADER = "A2A-Extensions"
CORRELATION_HEADER = "X-Correlation-ID"

OBSERVATION_CORRELATION_PREFIX = "obs_"
"""Prefix on a scheduled observation's correlation id.

Support reads BrainBuddy's log beside an agent's, and "was this call something
the user did, or something the schedule did?" is the first question asked. The
answer belongs in the id itself rather than in a second field an agent's log
would not carry.
"""

#: Seconds added to a short call's timeout to form its absolute deadline. Small
#: on purpose: it is a margin for the response to finish arriving, not a second
#: timeout.
SHORT_CALL_DEADLINE_MARGIN_SECONDS = 5.0

#: Seconds added to the reply window for an exchange's absolute deadline. An
#: agent answering at exactly the window is on time; this is the room for its
#: answer to finish crossing the wire.
EXCHANGE_DEADLINE_MARGIN_SECONDS = 15.0

EXCHANGE_CONNECT_TIMEOUT_SECONDS = 5.0

# --- BrainBuddy-facing failure categories -----------------------------------
#
# Named rather than derived, because each one means something different to a
# user and to the resend rules.

A2A_UNREACHABLE = "a2a_unreachable"
A2A_TIMEOUT = "a2a_timeout"
A2A_SERVER_ERROR = "a2a_server_error"
A2A_CREDENTIALS_REJECTED = "a2a_credentials_rejected"
A2A_RATE_LIMITED = "a2a_rate_limited"
A2A_REQUEST_REJECTED = "a2a_request_rejected"
A2A_RESPONSE_INVALID = "a2a_response_invalid"
A2A_RESPONSE_OVER_CAP = "a2a_response_over_cap"
A2A_TASK_NOT_FOUND = "a2a_task_not_found"
A2A_NOT_CANCELABLE = "a2a_not_cancelable"
A2A_PUSH_UNSUPPORTED = "a2a_push_unsupported"
A2A_UNSUPPORTED_OPERATION = "a2a_unsupported_operation"
A2A_CONTENT_UNSUPPORTED = "a2a_content_unsupported"
A2A_METHOD_NOT_FOUND = "a2a_method_not_found"
A2A_INTERNAL_ERROR = "a2a_internal_error"
A2A_INVALID_AGENT_RESPONSE = "a2a_invalid_agent_response"
A2A_EXTENDED_CARD_NOT_CONFIGURED = "a2a_extended_card_not_configured"
A2A_EXTENSION_SUPPORT_REQUIRED = "a2a_extension_support_required"
A2A_VERSION_NOT_SUPPORTED = "a2a_version_not_supported"

#: JSON-RPC error code -> BrainBuddy category (contracts/a2a-wire.md).
#:
#: `-32603` is deliberately apart from `-32004`/`-32601`: an internal error is
#: ambiguous, and only an explicit agent answer may ever harden into a durable
#: "this agent does not support cancellation" claim.
_ERROR_CODE_CATEGORIES: dict[int, str] = {
    TASK_NOT_FOUND: A2A_TASK_NOT_FOUND,
    TASK_NOT_CANCELABLE: A2A_NOT_CANCELABLE,
    PUSH_NOTIFICATION_NOT_SUPPORTED: A2A_PUSH_UNSUPPORTED,
    UNSUPPORTED_OPERATION: A2A_UNSUPPORTED_OPERATION,
    CONTENT_TYPE_NOT_SUPPORTED: A2A_CONTENT_UNSUPPORTED,
    INVALID_AGENT_RESPONSE: A2A_INVALID_AGENT_RESPONSE,
    EXTENDED_CARD_NOT_CONFIGURED: A2A_EXTENDED_CARD_NOT_CONFIGURED,
    EXTENSION_SUPPORT_REQUIRED: A2A_EXTENSION_SUPPORT_REQUIRED,
    VERSION_NOT_SUPPORTED: A2A_VERSION_NOT_SUPPORTED,
    INVALID_REQUEST: A2A_REQUEST_REJECTED,
    INVALID_PARAMS: A2A_REQUEST_REJECTED,
    PARSE_ERROR: A2A_REQUEST_REJECTED,
    METHOD_NOT_FOUND: A2A_METHOD_NOT_FOUND,
    INTERNAL_ERROR: A2A_INTERNAL_ERROR,
    UNAUTHORIZED: A2A_CREDENTIALS_REJECTED,
    UNTRUSTED: A2A_CREDENTIALS_REJECTED,
    RATE_LIMITED: A2A_RATE_LIMITED,
}

#: A ``Retry-After`` this far out is not a hint, it is a parsing accident.
_MAX_RETRY_AFTER_SECONDS = 24 * 60 * 60

ResultAvailability = Literal["available", "too_large"]


@dataclass(frozen=True)
class A2ATarget:
    """Where one call goes, and what it may carry.

    Assembled from a connection (and, for a dispatched run, from the run's
    *pinned* copy — a card that changes mid-run must not move a run's
    observations to a new endpoint).
    """

    interface_url: str
    auth_scheme: AuthScheme
    auth_header_name: str | None
    credential: str | None
    tenant: str | None = None
    guarantee_tier: GuaranteeTier = "best_effort"


@dataclass(frozen=True)
class A2AResult:
    """One call's outcome.

    ``repr`` is safe to log or attach to an error: the credential is never a
    field here, and the only agent-supplied strings are ids and codes.
    """

    ok: bool
    correlation_id: str
    task: Task | None = None
    message: Message | None = None
    tasks: tuple[Task, ...] = ()
    error_code: str | None = None
    a2a_error_code: int | None = None
    http_status: int | None = None
    retry_after_seconds: int | None = None
    result_availability: ResultAvailability | None = None


class A2AClientPort(Protocol):
    """The client surface the service and observer depend on.

    A protocol rather than the class, so the service can be constructed with a
    deterministic double and no test needs a socket to exercise a state
    machine.
    """

    def send_message(
        self,
        target: A2ATarget,
        *,
        message: dict[str, Any],
        push_config: dict[str, Any] | None = ...,
        run_id: str | None = ...,
    ) -> A2AResult: ...

    def get_task(
        self,
        target: A2ATarget,
        *,
        task_id: str,
        context_id: str | None = ...,
        history_length: int = ...,
        scheduled: bool = ...,
        run_id: str | None = ...,
        deadline_seconds: float | None = ...,
    ) -> A2AResult: ...

    def list_tasks(
        self,
        target: A2ATarget,
        *,
        context_id: str | None = ...,
        page_size: int = ...,
        scheduled: bool = ...,
        run_id: str | None = ...,
    ) -> A2AResult: ...

    def cancel_task(
        self,
        target: A2ATarget,
        *,
        task_id: str,
        command_id: str | None = ...,
        run_id: str | None = ...,
    ) -> A2AResult: ...

    def create_push_config(
        self,
        target: A2ATarget,
        *,
        task_id: str,
        url: str,
        token: str,
        run_id: str | None = ...,
    ) -> A2AResult: ...


def _parse_retry_after(raw: str | None) -> int | None:
    """A ``Retry-After`` in seconds, or nothing.

    Nothing is honest; a guessed countdown is a claim the agent never made, and
    a user shown a fabricated one will retry at exactly the wrong moment.
    """

    if not raw:
        return None
    try:
        seconds = int(raw.strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0 or seconds > _MAX_RETRY_AFTER_SECONDS:
        return None
    return seconds


class A2AClient:
    """A minimal, synchronous A2A JSON-RPC client on BrainBuddy's egress path."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        reply_window_seconds: int,
        max_response_bytes: int,
        task_max_response_bytes: int,
        allow_private_destinations: bool = False,
        resolver: Resolver | None = None,
        client_factory: Callable[..., httpx.Client] | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._reply_window_seconds = reply_window_seconds
        self._max_response_bytes = max_response_bytes
        self._task_max_response_bytes = task_max_response_bytes
        self._allow_private_destinations = allow_private_destinations
        self._resolver = resolver
        self._client_factory = client_factory

    # --- public operations -------------------------------------------------

    def send_message(
        self,
        target: A2ATarget,
        *,
        message: dict[str, Any],
        push_config: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> A2AResult:
        """Start or continue work at the agent. The only content-bearing call.

        Blocking by default: ``returnImmediately`` is deliberately absent,
        because the runtimes that matter create the task synchronously on
        receipt, which is what makes a lookup able to find it later.
        """

        payload = dict(message)
        if target.guarantee_tier == "guaranteed":
            # Activated on the *first* send, not only on replays: the extension
            # only obliges an agent to record the dedup key for a request that
            # activated it, so activating late would leave the first send —
            # the one that matters — outside the guarantee.
            payload["extensions"] = [SINGLE_START_EXTENSION_URI]

        configuration: dict[str, Any] = {"historyLength": 0}
        if push_config is not None:
            configuration["taskPushNotificationConfig"] = push_config

        return self._call(
            target,
            method="SendMessage",
            params={"message": payload, "configuration": configuration},
            timeout=httpx.Timeout(
                connect=EXCHANGE_CONNECT_TIMEOUT_SECONDS,
                read=self._reply_window_seconds + EXCHANGE_DEADLINE_MARGIN_SECONDS,
                write=EXCHANGE_CONNECT_TIMEOUT_SECONDS,
                pool=EXCHANGE_CONNECT_TIMEOUT_SECONDS,
            ),
            deadline_seconds=(
                self._reply_window_seconds + EXCHANGE_DEADLINE_MARGIN_SECONDS
            ),
            max_response_bytes=self._task_max_response_bytes,
            run_id=run_id,
        )

    def get_task(
        self,
        target: A2ATarget,
        *,
        task_id: str,
        context_id: str | None = None,
        history_length: int = 0,
        scheduled: bool = False,
        run_id: str | None = None,
        deadline_seconds: float | None = None,
    ) -> A2AResult:
        """Read one task. History is fetched only when a state needs its text."""

        result = self._call(
            target,
            method="GetTask",
            params={"id": task_id, "historyLength": history_length},
            max_response_bytes=self._task_max_response_bytes,
            scheduled=scheduled,
            run_id=run_id,
            deadline_seconds=deadline_seconds,
        )
        if result.error_code != A2A_RESPONSE_OVER_CAP or context_id is None:
            # Without a contextId the fallback would list a different
            # conversation's tasks, and adopting a foreign task is worse than
            # failing the observation.
            return result

        fallback = self.list_tasks(
            target,
            context_id=context_id,
            page_size=5,
            scheduled=scheduled,
            run_id=run_id,
            deadline_seconds=deadline_seconds,
        )
        if not fallback.ok or not fallback.tasks:
            return result
        newest = fallback.tasks[0]
        return A2AResult(
            ok=True,
            correlation_id=fallback.correlation_id,
            task=newest,
            # The state is true; only the result is missing. Saying so is the
            # difference between an honest marker and reporting a healthy agent
            # as having stopped reporting.
            result_availability="too_large",
        )

    def list_tasks(
        self,
        target: A2ATarget,
        *,
        context_id: str | None = None,
        page_size: int = 5,
        scheduled: bool = False,
        run_id: str | None = None,
        deadline_seconds: float | None = None,
    ) -> A2AResult:
        """List the tasks in one conversation. Never carries content."""

        params: dict[str, Any] = {
            "pageSize": page_size,
            "includeArtifacts": False,
            "historyLength": 0,
        }
        if context_id is not None:
            params = {"contextId": context_id, **params}
        return self._call(
            target,
            method="ListTasks",
            params=params,
            max_response_bytes=self._task_max_response_bytes,
            scheduled=scheduled,
            run_id=run_id,
            deadline_seconds=deadline_seconds,
        )

    def cancel_task(
        self,
        target: A2ATarget,
        *,
        task_id: str,
        command_id: str | None = None,
        run_id: str | None = None,
    ) -> A2AResult:
        """Ask the agent to stop. Runs on the control pool, never behind an
        exchange — on some runtimes a cancel is what *resolves* a blocked
        exchange, so queueing it behind one would wait out the whole window."""

        params: dict[str, Any] = {"id": task_id}
        if command_id is not None:
            params["metadata"] = {"brainbuddy.command_id": command_id}
        return self._call(target, method="CancelTask", params=params, run_id=run_id)

    def create_push_config(
        self,
        target: A2ATarget,
        *,
        task_id: str,
        url: str,
        token: str,
        run_id: str | None = None,
    ) -> A2AResult:
        """Register a push callback for a task adopted after an interruption.

        Any failure is silent to the user: push only accelerates an observation
        the schedule performs anyway, so an error here is not something the
        owner can or should act on.
        """

        return self._call(
            target,
            method="CreateTaskPushNotificationConfig",
            params={"taskId": task_id, "url": url, "token": token},
            run_id=run_id,
        )

    # --- the one place a request is built ----------------------------------

    def _headers(self, target: A2ATarget, correlation_id: str) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "A2A-Version": A2A_VERSION,
            CORRELATION_HEADER: correlation_id,
        }
        if target.credential:
            if target.auth_scheme == "bearer":
                headers["Authorization"] = f"Bearer {target.credential}"
            elif target.auth_header_name:
                headers[target.auth_header_name] = target.credential
        if target.guarantee_tier == "guaranteed":
            headers[EXTENSION_HEADER] = SINGLE_START_EXTENSION_URI
        return headers

    @staticmethod
    def _mint_correlation_id(*, scheduled: bool) -> str:
        """Minted here and nowhere else (constitution Principle IV).

        The inbound ``X-Correlation-ID`` a caller may send is an observability
        label for BrainBuddy's own request. Forwarding it would put a
        caller-chosen string into a stranger's log and header parser, and — if
        an agent ever reused it — into a dedup or authorization decision.
        """

        identifier = uuid.uuid4().hex
        return (
            f"{OBSERVATION_CORRELATION_PREFIX}{identifier}" if scheduled else identifier
        )

    def _call(
        self,
        target: A2ATarget,
        *,
        method: str,
        params: dict[str, Any],
        timeout: httpx.Timeout | float | None = None,
        deadline_seconds: float | None = None,
        max_response_bytes: int | None = None,
        scheduled: bool = False,
        run_id: str | None = None,
    ) -> A2AResult:
        correlation_id = self._mint_correlation_id(scheduled=scheduled)
        if target.tenant:
            params = {**params, "tenant": target.tenant}

        # Held as its own local so the response check below compares a `str`
        # against a `str`; reading it back out of the request dict would make
        # the id's type depend on the widest value in the envelope.
        request_id = uuid.uuid4().hex
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            destination = validate_destination(
                target.interface_url,
                allow_private_destinations=self._allow_private_destinations,
                resolver=self._resolver,
            )
        except DestinationRejected as exc:
            return self._log_and_return(
                A2AResult(
                    ok=False,
                    correlation_id=correlation_id,
                    error_code=exc.code,
                ),
                method=method,
                run_id=run_id,
            )

        try:
            response = pinned_request(
                method="POST",
                destination=destination,
                headers=self._headers(target, correlation_id),
                json_body=body,
                timeout_seconds=(
                    timeout
                    if timeout is not None
                    else self._timeout_seconds  # type: ignore[arg-type]
                ),
                max_response_bytes=max_response_bytes or self._max_response_bytes,
                client_factory=self._client_factory,
                deadline_seconds=(
                    deadline_seconds
                    if deadline_seconds is not None
                    else self._timeout_seconds + SHORT_CALL_DEADLINE_MARGIN_SECONDS
                ),
            )
        except EgressDeadlineExceeded:
            # Distinct from unreachable: the connection succeeded, so the
            # message may already be at the agent. A start exchange that
            # breaches here is *unconfirmed*, never "not sent".
            return self._log_and_return(
                A2AResult(
                    ok=False, correlation_id=correlation_id, error_code=A2A_TIMEOUT
                ),
                method=method,
                run_id=run_id,
            )
        except DestinationRejected as exc:
            code = (
                A2A_RESPONSE_OVER_CAP if exc.code == "destination_invalid" else exc.code
            )
            return self._log_and_return(
                A2AResult(ok=False, correlation_id=correlation_id, error_code=code),
                method=method,
                run_id=run_id,
            )
        except httpx.TimeoutException:
            return self._log_and_return(
                A2AResult(
                    ok=False, correlation_id=correlation_id, error_code=A2A_TIMEOUT
                ),
                method=method,
                run_id=run_id,
            )
        except httpx.HTTPError:
            return self._log_and_return(
                A2AResult(
                    ok=False, correlation_id=correlation_id, error_code=A2A_UNREACHABLE
                ),
                method=method,
                run_id=run_id,
            )

        return self._log_and_return(
            self._interpret(
                response.status_code,
                response.body,
                response.headers,
                request_id,
                correlation_id,
            ),
            method=method,
            run_id=run_id,
            http_status=response.status_code,
        )

    def _interpret(
        self,
        status_code: int,
        raw: bytes,
        headers: Mapping[str, str],
        request_id: str,
        correlation_id: str,
    ) -> A2AResult:
        """Turn one HTTP answer into a category. Status class first."""

        if status_code in (401, 403):
            return A2AResult(
                ok=False,
                correlation_id=correlation_id,
                error_code=A2A_CREDENTIALS_REJECTED,
                http_status=status_code,
            )
        if status_code == 429:
            return A2AResult(
                ok=False,
                correlation_id=correlation_id,
                error_code=A2A_RATE_LIMITED,
                http_status=status_code,
                retry_after_seconds=_parse_retry_after(headers.get("retry-after")),
            )
        if status_code >= 500:
            return A2AResult(
                ok=False,
                correlation_id=correlation_id,
                error_code=A2A_SERVER_ERROR,
                http_status=status_code,
            )
        if status_code >= 400:
            return A2AResult(
                ok=False,
                correlation_id=correlation_id,
                error_code=A2A_REQUEST_REJECTED,
                http_status=status_code,
            )

        try:
            payload = json.loads(raw)
            envelope = JsonRpcResponse.model_validate(payload)
        except (ValueError, UnicodeDecodeError):
            return A2AResult(
                ok=False,
                correlation_id=correlation_id,
                error_code=A2A_RESPONSE_INVALID,
                http_status=status_code,
            )

        if str(envelope.id) != request_id:
            # An answer that does not name its request could belong to any
            # call; accepting it would let a muddled server settle the wrong
            # exchange.
            return A2AResult(
                ok=False,
                correlation_id=correlation_id,
                error_code=A2A_RESPONSE_INVALID,
                http_status=status_code,
            )

        if envelope.error is not None:
            code = envelope.error.code
            return A2AResult(
                ok=False,
                correlation_id=correlation_id,
                error_code=_ERROR_CODE_CATEGORIES.get(code, A2A_RESPONSE_INVALID),
                a2a_error_code=code,
                http_status=status_code,
            )

        return self._read_result(envelope.result or {}, correlation_id, status_code)

    @staticmethod
    def _read_result(
        result: dict[str, Any], correlation_id: str, status_code: int
    ) -> A2AResult:
        try:
            task = Task.model_validate(result["task"]) if "task" in result else None
            message = (
                Message.model_validate(result["message"])
                if "message" in result
                else None
            )
            tasks = tuple(
                Task.model_validate(entry) for entry in result.get("tasks", [])
            )
        except (ValueError, TypeError):
            return A2AResult(
                ok=False,
                correlation_id=correlation_id,
                error_code=A2A_RESPONSE_INVALID,
                http_status=status_code,
            )
        return A2AResult(
            ok=True,
            correlation_id=correlation_id,
            task=task,
            message=message,
            tasks=tasks,
            http_status=status_code,
        )

    def _log_and_return(
        self,
        result: A2AResult,
        *,
        method: str,
        run_id: str | None,
        http_status: int | None = None,
    ) -> A2AResult:
        """Log the Decision K allowlist and nothing else.

        Codes, ids and a status class — never a card body, message part,
        artifact, credential or push token. An agent-chosen error integer is
        collapsed to ``other`` so it cannot grow log cardinality or become an
        injection surface.
        """

        status = http_status if http_status is not None else result.http_status
        logger.info(
            "a2a_call method=%s status_class=%s a2a_error_code=%s error=%s "
            "protocol_version=%s correlation_id=%s run_id=%s",
            method,
            f"{status // 100}xx" if status else "none",
            loggable_error_code(result.a2a_error_code),
            result.error_code or "none",
            A2A_VERSION,
            result.correlation_id,
            run_id or "none",
        )
        return result


__all__ = [
    "A2A_CONTENT_UNSUPPORTED",
    "A2A_CREDENTIALS_REJECTED",
    "A2A_INTERNAL_ERROR",
    "A2A_METHOD_NOT_FOUND",
    "A2A_NOT_CANCELABLE",
    "A2A_PUSH_UNSUPPORTED",
    "A2A_RATE_LIMITED",
    "A2A_REQUEST_REJECTED",
    "A2A_RESPONSE_INVALID",
    "A2A_RESPONSE_OVER_CAP",
    "A2A_SERVER_ERROR",
    "A2A_TASK_NOT_FOUND",
    "A2A_TIMEOUT",
    "A2A_UNREACHABLE",
    "A2A_UNSUPPORTED_OPERATION",
    "A2A_VERSION",
    "EXTENSION_HEADER",
    "OBSERVATION_CORRELATION_PREFIX",
    "A2AClient",
    "A2AClientPort",
    "A2AResult",
    "A2ATarget",
]
