"""Cloud provider adapters for the weekly-review navigator (spec 020, R13).

The concrete side of the ``NavigatorProvider`` port declared in
``app.modules.tasks.navigator`` (ADR-0001 rule 9: network clients live outside
the Tasks module). Three providers:

- ``disabled``: the only way to run without the navigator. The API then reports
  ``available: false`` and answers suggestions with ``503 navigator_disabled``.
- ``deterministic``: TEST only. Hermetic, grounded output derived from the
  input; no network. Test markers in the title or notes force the failure
  paths (quickstart Scenario 4 step 4).
- ``openai``: chat completions with a JSON-schema response format and
  temperature 0.4; the key is read from the variable named by
  ``BRAIN_BUDDY_REVIEW_NAVIGATOR_API_KEY_ENV``.

Unlike title completion, a misconfiguration never degrades silently:
``build_review_navigator_provider`` raises (constitution I), naming the key
variable and never its value. Nothing here logs; the service logs codes only.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import AppEnvironment, ReviewNavigatorSettings
from app.modules.tasks.navigator import (
    CHARS_PER_TOKEN,
    NavigatorInput,
    NavigatorProvider,
    NavigatorProviderFailure,
    NavigatorProviderResult,
    NavigatorProviderTimeout,
    system_prompt,
    user_prompt,
)

PROVIDER_ENV = "BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER"
SUPPORTED_PROVIDERS = ("disabled", "deterministic", "openai")
OPENAI_CATEGORY = "openai"
TEMPERATURE = 0.4

# US dollars per million tokens (input, output). A model missing here is
# estimated at the conservative fallback, so the per-call cap still bounds it.
_PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}
_FALLBACK_PRICE_PER_MILLION = (15.00, 60.00)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "At most 3 one-line next actions; empty when asking.",
        },
        "clarifying_question": {"type": ["string", "null"]},
    },
    "required": ["proposals", "clarifying_question"],
    "additionalProperties": False,
}
"""contracts/navigator.md §3; the ≤ 3 bound is enforced by the §2 validation."""

TEST_MARKER_TIMEOUT = "navigator-test:timeout"
TEST_MARKER_PROVIDER_ERROR = "navigator-test:provider_error"
TEST_MARKER_MALFORMED = "navigator-test:malformed"
TEST_MARKER_QUESTION = "navigator-test:question"


class ReviewNavigatorConfigurationError(ValueError):
    """A navigator configuration that must stop the container build."""


def _cost(model: str, *, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = _PRICES_PER_MILLION.get(
        model, _FALLBACK_PRICE_PER_MILLION
    )
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def _tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class DisabledNavigatorProvider:
    """The operator switched the navigator off (``provider: null``)."""

    @property
    def category(self) -> str | None:
        return None

    def estimate_cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        del input_tokens, output_tokens
        return 0.0

    def suggest(self, navigator_input: NavigatorInput) -> NavigatorProviderResult:
        del navigator_input
        raise NavigatorProviderFailure("navigator disabled")


@dataclass(frozen=True, slots=True)
class DeterministicNavigatorProvider:
    """Hermetic TEST provider standing in for the configured cloud provider.

    It reports the ``openai`` category so consent copy, wire fixtures and the
    end-to-end consent flow look exactly as in production; it never touches
    the network. Its proposals reuse only words of the input, so they pass the
    §2 grounding check.
    """

    model: str = "gpt-4o-mini"

    @property
    def category(self) -> str | None:
        return OPENAI_CATEGORY

    def estimate_cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return _cost(self.model, input_tokens=input_tokens, output_tokens=output_tokens)

    def suggest(self, navigator_input: NavigatorInput) -> NavigatorProviderResult:
        text = f"{navigator_input.task_title or ''}\n{navigator_input.task_notes or ''}"
        if TEST_MARKER_TIMEOUT in text:
            raise NavigatorProviderTimeout
        if TEST_MARKER_PROVIDER_ERROR in text:
            raise NavigatorProviderFailure("deterministic provider error")
        input_tokens = _tokens(
            system_prompt(navigator_input.kind) + user_prompt(navigator_input)
        )
        if TEST_MARKER_MALFORMED in text:
            return NavigatorProviderResult(
                proposals=("first line\nsecond line", "#tag step"),
                clarifying_question=None,
                input_tokens=input_tokens,
                output_tokens=8,
            )
        if TEST_MARKER_QUESTION in text:
            question = "Which part of this should come first?"
            return NavigatorProviderResult(
                proposals=(),
                clarifying_question=question,
                input_tokens=input_tokens,
                output_tokens=_tokens(question),
            )
        proposals = _deterministic_proposals(navigator_input)
        return NavigatorProviderResult(
            proposals=proposals,
            clarifying_question=None,
            input_tokens=input_tokens,
            output_tokens=_tokens("".join(proposals)),
        )


def _subject(value: str) -> str:
    return " ".join(value.split())[:120].strip()


def _deterministic_proposals(navigator_input: NavigatorInput) -> tuple[str, ...]:
    if navigator_input.kind == "project_next_action":
        name = _subject(navigator_input.project_name or "")
        return (f"List what {name} needs next", f"Pick one open question for {name}")
    title = _subject(navigator_input.task_title or "")
    if navigator_input.kind == "reformulate":
        return (
            f"Name the outcome of: {title}",
            f"Decide the next visible action for: {title}",
        )
    return (
        f"Write down the smallest first step for: {title}",
        f"Spend ten minutes on: {title}",
    )


@dataclass(frozen=True, slots=True)
class OpenAINavigatorProvider:
    """OpenAI chat completions behind the navigator port (one call, no retry)."""

    api_key: str = field(repr=False)
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 8.0
    max_output_tokens: int = 300
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    transport: httpx.BaseTransport | None = field(default=None, repr=False)

    @property
    def category(self) -> str | None:
        return OPENAI_CATEGORY

    def estimate_cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return _cost(self.model, input_tokens=input_tokens, output_tokens=output_tokens)

    def request_body(self, navigator_input: NavigatorInput) -> dict[str, Any]:
        """The exact request: instructions and delimited data, nothing else."""

        return {
            "model": self.model,
            "temperature": TEMPERATURE,
            "max_tokens": self.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "navigator_reply",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                },
            },
            "messages": [
                {"role": "system", "content": system_prompt(navigator_input.kind)},
                {"role": "user", "content": user_prompt(navigator_input)},
            ],
        }

    def suggest(self, navigator_input: NavigatorInput) -> NavigatorProviderResult:
        """One call bounded by **one** overall deadline of ``timeout_seconds``.

        httpx timeouts apply per phase (connect, each read), so a slow
        connect followed by a trickling body could take several times the
        limit. The call therefore runs on a short-lived worker thread that
        also stops reading once the deadline passes, and this thread waits
        for it no longer than the deadline.
        """

        deadline = time.monotonic() + self.timeout_seconds
        outcome: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        worker = threading.Thread(
            target=self._call_into,
            args=(self.request_body(navigator_input), deadline, outcome),
            name="review-navigator-call",
            daemon=True,
        )
        worker.start()
        try:
            ok, value = outcome.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            raise NavigatorProviderTimeout from None
        if not ok:
            raise value
        status, body = value
        if not 200 <= status < 300:
            raise NavigatorProviderFailure("provider returned an error status")
        return _parse_completion(body)

    def _call_into(
        self,
        payload: dict[str, Any],
        deadline: float,
        outcome: queue.Queue[tuple[bool, Any]],
    ) -> None:
        """The worker: ``(True, (status, body))`` or ``(False, exception)``."""

        try:
            outcome.put((True, self._post(payload, deadline)))
        except httpx.TimeoutException:
            outcome.put((False, NavigatorProviderTimeout()))
        except httpx.HTTPError:
            outcome.put((False, NavigatorProviderFailure("provider transport failed")))
        except Exception as error:  # noqa: BLE001 - re-raised by the caller
            outcome.put((False, error))

    def _post(self, payload: dict[str, Any], deadline: float) -> tuple[int, bytes]:
        chunks: list[bytes] = []
        with (
            httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as c,
            c.stream(
                "POST",
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as response,
        ):
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise httpx.ReadTimeout("navigator deadline passed")
                chunks.append(chunk)
            return response.status_code, b"".join(chunks)


def _parse_completion(raw: bytes) -> NavigatorProviderResult:
    """Read the reply; an unusable body becomes an empty (malformed) result."""

    try:
        body: Any = json.loads(raw)
    except ValueError:
        return NavigatorProviderResult(proposals=(), clarifying_question=None)
    usage = body.get("usage") if isinstance(body, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = _token_count(usage.get("prompt_tokens"))
    output_tokens = _token_count(usage.get("completion_tokens"))
    try:
        decoded = json.loads(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError):
        decoded = None
    if not isinstance(decoded, dict):
        decoded = {}
    raw_proposals = decoded.get("proposals")
    proposals = (
        tuple(item for item in raw_proposals if isinstance(item, str))
        if isinstance(raw_proposals, list)
        else ()
    )
    question = decoded.get("clarifying_question")
    return NavigatorProviderResult(
        proposals=proposals,
        clarifying_question=question if isinstance(question, str) else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _token_count(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def build_review_navigator_provider(
    settings: ReviewNavigatorSettings,
    *,
    environment: AppEnvironment,
    environ: Mapping[str, str],
) -> NavigatorProvider:
    """The configured provider, or raise (research R13; never degrade silently).

    Messages name variables only; a key value never reaches an error or a log.
    """

    provider = settings.provider
    if provider == "disabled":
        return DisabledNavigatorProvider()
    if provider == "deterministic":
        if environment is not AppEnvironment.TEST:
            raise ReviewNavigatorConfigurationError(
                f"{PROVIDER_ENV}=deterministic is allowed only in the test "
                f"environment; set {PROVIDER_ENV}=disabled or openai."
            )
        return DeterministicNavigatorProvider(model=settings.model)
    if provider == "openai":
        api_key = (environ.get(settings.api_key_env) or "").strip()
        if not api_key:
            raise ReviewNavigatorConfigurationError(
                f"{PROVIDER_ENV}=openai needs the API key variable "
                f"{settings.api_key_env} to be set and non-empty. Set "
                f"{PROVIDER_ENV}=disabled before rotating or removing the key, "
                "and set it back after the new key is in place."
            )
        return OpenAINavigatorProvider(
            api_key=api_key,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
        )
    raise ReviewNavigatorConfigurationError(
        f"{PROVIDER_ENV} must be one of: {', '.join(SUPPORTED_PROVIDERS)}."
    )


__all__ = [
    "PROVIDER_ENV",
    "RESPONSE_SCHEMA",
    "SUPPORTED_PROVIDERS",
    "TEST_MARKER_MALFORMED",
    "TEST_MARKER_PROVIDER_ERROR",
    "TEST_MARKER_QUESTION",
    "TEST_MARKER_TIMEOUT",
    "DeterministicNavigatorProvider",
    "DisabledNavigatorProvider",
    "OpenAINavigatorProvider",
    "ReviewNavigatorConfigurationError",
    "build_review_navigator_provider",
]
