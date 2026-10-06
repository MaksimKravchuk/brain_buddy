"""Spec 020 slice PR-07: the review navigator backend (contracts/http.md §7,
contracts/navigator.md).

The first test of the slice is the configuration rule of research R13: a
navigator configured for ``openai`` without its key, ``deterministic`` outside
TEST, or an unknown provider makes the container build raise, naming the key
variable and never a value. Every provider call here goes to a deterministic
stub; no test makes a live provider call.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import allure
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai.review_navigator import (
    RESPONSE_SCHEMA,
    DeterministicNavigatorProvider,
    DisabledNavigatorProvider,
    OpenAINavigatorProvider,
)
from app.container import Container, build_container
from app.core import get_config
from app.core.rate_limit import navigator_rate_limiter
from app.main import create_app
from app.modules.tasks.navigator import (
    CONSENT_TEXT_VERSION,
    NOTES_BUDGET_CHARS,
    PROMPT_VERSION,
    NavigatorInput,
    NavigatorLimits,
    NavigatorOutput,
    NavigatorProviderFailure,
    NavigatorProviderResult,
    NavigatorProviderTimeout,
    consent_is_current,
    reduce_notes,
    system_prompt,
    user_prompt,
    validate_navigator_output,
)
from app.modules.tasks.review_domain import (
    NavigatorConsentDocument,
    NavigatorUsageDocument,
    ReviewSettingsDocument,
)
from app.schemas.auth import Invite
from app.schemas.review import NavigatorSuggestionRequest
from app.utils.time import utcnow

from .conftest import FrozenClock

KEY_ENV = "BB_TEST_NAVIGATOR_KEY"
PROVIDER_ENV = "BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER"
KEY_ENV_ENV = "BRAIN_BUDDY_REVIEW_NAVIGATOR_API_KEY_ENV"


@pytest.fixture
def navigator_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[pytest.MonkeyPatch]:
    """A fresh data dir and a clean navigator environment for a container build."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "nav-config"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv(KEY_ENV_ENV, KEY_ENV)
    monkeypatch.delenv(KEY_ENV, raising=False)
    get_config.cache_clear()
    yield monkeypatch
    get_config.cache_clear()


@pytest.mark.parametrize(
    ("environment", "provider", "key_value"),
    [
        pytest.param("test", "openai", None, id="openai-key-unset"),
        pytest.param("test", "openai", "", id="openai-key-empty"),
        pytest.param("test", "openai", "   ", id="openai-key-blank"),
        pytest.param("development", "deterministic", None, id="deterministic-dev"),
        pytest.param("test", "anthropic-ish", None, id="unknown-provider"),
    ],
)
def test_020_FR_025_container_build_raises_without_key(
    navigator_env: pytest.MonkeyPatch,
    environment: str,
    provider: str,
    key_value: str | None,
) -> None:
    """A misconfigured navigator fails the container build (research R13):
    ``openai`` without the key named by ``…_API_KEY_ENV``, ``deterministic``
    outside TEST and an unknown provider all raise; the message names the key
    variable for the key case and never echoes a value."""

    navigator_env.setenv("BRAIN_BUDDY_ENV", environment)
    navigator_env.setenv(PROVIDER_ENV, provider)
    if key_value is not None:
        navigator_env.setenv(KEY_ENV, key_value)
    get_config.cache_clear()
    with pytest.raises(ValueError) as raised:
        build_container(get_config())
    message = str(raised.value)
    allure.attach(
        message, name="startup error", attachment_type=allure.attachment_type.TEXT
    )
    assert PROVIDER_ENV in message
    if provider == "openai":
        assert KEY_ENV in message
    if key_value and key_value.strip():
        assert key_value not in message


def test_020_FR_025_openai_with_a_key_builds_and_never_shows_the_key(
    navigator_env: pytest.MonkeyPatch,
) -> None:
    """With the key present the build succeeds; the key is not in any repr."""

    secret = "sk-test-not-a-real-key-0123456789"
    navigator_env.setenv(PROVIDER_ENV, "openai")
    navigator_env.setenv(KEY_ENV, secret)
    get_config.cache_clear()
    with allure.step("build the container with an openai key"):
        container = build_container(get_config())
    provider = container.navigator_service.provider
    assert isinstance(provider, OpenAINavigatorProvider)
    assert provider.category == "openai"
    assert secret not in repr(provider)
    assert secret not in repr(container.navigator_service)


def test_020_FR_025_env_example_documents_the_navigator_and_its_runbook() -> None:
    """``.env.example`` is the authoritative reference (T105, c2 AH-05): every
    ``BRAIN_BUDDY_REVIEW_NAVIGATOR_*`` variable ``config.py`` reads is listed
    with the code's default, next to the key-rotation runbook line."""

    repo_root = Path(__file__).resolve().parents[2]
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")
    config_source = (repo_root / "backend" / "app" / "core" / "config.py").read_text(
        encoding="utf-8"
    )
    read = dict(
        re.findall(
            r'"(BRAIN_BUDDY_REVIEW_NAVIGATOR_[A-Z_]+)",\s*"([^"]*)"', config_source
        )
    )
    assert len(read) == 8
    documented = dict(
        re.findall(r"^(BRAIN_BUDDY_REVIEW_NAVIGATOR_[A-Z_]+)=(.*)$", env_example, re.M)
    )
    assert documented == read
    flattened = " ".join(env_example.replace("#", " ").split())
    assert (
        "set `BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=disabled` before rotating or "
        "removing the key, and set it back after the new key is in place"
    ) in flattened


# ----------------------------------------------------------- T099 adapter
# The OpenAI adapter runs against ``httpx.MockTransport`` only: no test here,
# or anywhere in CI, reaches a provider.

ADAPTER_INPUT = NavigatorInput(
    kind="first_step",
    task_title="Renovate the bathroom",
    task_notes="Tiles from the old shop",
    stall_reason="too_big",
    project_name="Flat",
    open_task_titles=("Buy paint",),
)


def _completion(content: object, usage: object = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "choices": [{"message": {"content": json.dumps(content)}}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> Any:
    return OpenAINavigatorProvider(
        api_key="sk-test-adapter",
        timeout_seconds=8.0,
        max_output_tokens=300,
        transport=httpx.MockTransport(handler),
    )


def test_020_FR_025_openai_adapter_sends_the_versioned_prompt_and_schema() -> None:
    """Chat completions with a strict JSON-schema reply, temperature 0.4, the
    output-token cap and exactly the FR-019 data; usage tokens are read."""

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_completion(
                {"proposals": ["Measure the wall"], "clarifying_question": None},
                {"prompt_tokens": 412, "completion_tokens": 17},
            ),
        )

    result = _adapter(handler).suggest(ADAPTER_INPUT)
    assert result == NavigatorProviderResult(
        proposals=("Measure the wall",),
        clarifying_question=None,
        input_tokens=412,
        output_tokens=17,
    )
    (request,) = captured
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test-adapter"
    body = json.loads(request.content)
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.4
    assert body["max_tokens"] == 300
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == RESPONSE_SCHEMA
    assert body["messages"] == [
        {"role": "system", "content": system_prompt("first_step")},
        {"role": "user", "content": user_prompt(ADAPTER_INPUT)},
    ]
    assert '"language' not in request.content.decode()
    assert "<language" not in body["messages"][1]["content"]


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        pytest.param(httpx.ReadTimeout("slow"), NavigatorProviderTimeout, id="timeout"),
        pytest.param(
            httpx.ConnectError("down"), NavigatorProviderFailure, id="transport"
        ),
    ],
)
def test_020_FR_025_openai_adapter_maps_transport_errors(
    raised: Exception, expected: type[Exception]
) -> None:
    """A timeout and a transport error become the port's two failures."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise raised

    with pytest.raises(expected):
        _adapter(handler).suggest(ADAPTER_INPUT)


def test_020_FR_025_openai_adapter_maps_http_errors_to_provider_failure() -> None:
    """A 5xx/4xx status is a provider error carrying no response content."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "SENTINEL-UPSTREAM"}})

    with pytest.raises(NavigatorProviderFailure) as raised:
        _adapter(handler).suggest(ADAPTER_INPUT)
    assert "SENTINEL-UPSTREAM" not in str(raised.value)


@pytest.mark.parametrize(
    ("response", "proposals", "question"),
    [
        pytest.param(httpx.Response(200, text="not json"), (), None, id="not-json"),
        pytest.param(
            httpx.Response(200, json={"choices": []}), (), None, id="no-choice"
        ),
        pytest.param(
            httpx.Response(200, json=_completion(["a list"])), (), None, id="not-object"
        ),
        pytest.param(
            httpx.Response(
                200,
                json=_completion(
                    {"proposals": ["Measure", 3, None], "clarifying_question": 7}
                ),
            ),
            ("Measure",),
            None,
            id="mixed-types",
        ),
        pytest.param(
            httpx.Response(
                200,
                json=_completion(
                    {"proposals": "Measure", "clarifying_question": "Which wall?"},
                    {"prompt_tokens": True, "completion_tokens": -1},
                ),
            ),
            (),
            "Which wall?",
            id="question",
        ),
    ],
)
def test_020_FR_021_openai_adapter_turns_unusable_replies_into_empty_results(
    response: httpx.Response, proposals: tuple[str, ...], question: str | None
) -> None:
    """Unusable bodies are not errors here: the §2 validation calls them
    ``malformed``; bad usage figures are ignored."""

    result = _adapter(lambda request: response).suggest(ADAPTER_INPUT)
    assert result.proposals == proposals
    assert result.clarifying_question == question
    assert result.input_tokens is None
    assert result.output_tokens is None


def test_020_FR_025_cost_estimates_use_the_model_price_table() -> None:
    """gpt-4o-mini is priced per token; an unpriced model uses the
    conservative fallback, so the per-call cap still bounds it."""

    mini = OpenAINavigatorProvider(api_key="k")
    unknown = OpenAINavigatorProvider(api_key="k", model="some-future-model")
    assert mini.estimate_cost_usd(
        input_tokens=1_000_000, output_tokens=1_000_000
    ) == pytest.approx(0.75)
    assert (
        unknown.estimate_cost_usd(input_tokens=6_000, output_tokens=300)
        > NavigatorLimits().max_cost_usd
    )
    disabled = DisabledNavigatorProvider()
    assert disabled.category is None
    assert disabled.estimate_cost_usd(input_tokens=1, output_tokens=1) == 0.0
    with pytest.raises(NavigatorProviderFailure):
        disabled.suggest(ADAPTER_INPUT)


def test_020_FR_021_deterministic_provider_is_grounded_and_hermetic() -> None:
    """The TEST provider's proposals pass the §2 validation for every kind."""

    provider = DeterministicNavigatorProvider()
    for kind in ("first_step", "reformulate", "project_next_action"):
        navigator_input = replace(ADAPTER_INPUT, kind=kind)  # type: ignore[arg-type]
        result = provider.suggest(navigator_input)
        output = validate_navigator_output(
            navigator_input,
            proposals=result.proposals,
            clarifying_question=result.clarifying_question,
        )
        assert output is not None
        assert output.proposals == result.proposals


# ------------------------------------------------------------ T100 input


def _input(
    *,
    kind: str = "first_step",
    title: str | None = "Renovate the bathroom",
    notes: str | None = None,
    stall_reason: str | None = None,
    project_name: str | None = None,
    open_task_titles: tuple[str, ...] = (),
) -> NavigatorInput:
    return NavigatorInput(
        kind=kind,  # type: ignore[arg-type]
        task_title=title,
        task_notes=notes,
        stall_reason=stall_reason,
        project_name=project_name,
        open_task_titles=open_task_titles,
    )


def _lines(count: int, width: int, prefix: str = "l") -> list[str]:
    return [f"{prefix}{index:03d}".ljust(width, "x") for index in range(count)]


_NINETY_LINES = _lines(90, 99)
_CRLF_LINES = _lines(70, 99, "c")
REDUCE_NOTES_VECTORS: list[tuple[str, str, str | None, bool]] = [
    ("empty", "", "", False),
    ("short", "Tiles from the old shop\nAsk Anna", None, False),
    ("exactly-budget", "a" * 5_000 + "\n" + "b" * 999, None, False),
    (
        "ninety-lines",
        "\n".join(_NINETY_LINES),
        "\n".join(_NINETY_LINES[:20]) + "\n…\n" + "\n".join(_NINETY_LINES[-40:]),
        True,
    ),
    (
        "crlf-lines",
        "\r\n".join(_CRLF_LINES),
        "\n".join(_CRLF_LINES[:20]) + "\n…\n" + "\n".join(_CRLF_LINES[-40:]),
        True,
    ),
    ("one-huge-line", "z" * 7_000, "\n…\n", True),
    ("astral-at-budget", "😀" * 6_000, None, False),
    (
        "astral-over-budget",
        "😀" * 1_000 + "\n" + "😀" * 5_001,
        "😀" * 1_000 + "\n…\n",
        True,
    ),
    ("already-reduced", "h" * 2_000 + "\n…\n" + "t" * 4_000, None, False),
    (
        "separator-out-of-place",
        "x" * 2_500 + "\n…\n" + "y" * 3_499,
        "\n…\n…\n" + "y" * 3_499,
        True,
    ),
    ("two-lines-no-drop", "h" * 2_000 + "\n" + "t" * 4_000, None, False),
]
"""Shared-rule vectors for ``reduce_notes`` (contracts/navigator.md §1).

``None`` as the expected text means "unchanged". Lengths are Unicode scalars.
"""


@pytest.mark.parametrize(
    ("notes", "expected", "truncated"),
    [pytest.param(n, e, t, id=i) for i, n, e, t in REDUCE_NOTES_VECTORS],
)
def test_020_FR_019_reduce_notes_vectors(
    notes: str, expected: str | None, truncated: bool
) -> None:
    """Notes up to 6 000 scalars are unchanged; longer notes keep whole first
    lines up to 2 000 and whole last lines up to 4 000, joined by one ``…``
    line, and report ``truncated``; a reduced note is a fixed point."""

    reduced, was_truncated = reduce_notes(notes)
    assert reduced == (notes if expected is None else expected)
    assert was_truncated is truncated
    assert len(reduced) <= NOTES_BUDGET_CHARS + 3
    # Reducing again changes nothing: the server's backstop is a fixed point.
    assert reduce_notes(reduced) == (reduced, False)


def test_020_FR_019_reduced_ninety_lines_fit_the_head_and_tail_budgets() -> None:
    """The head is at most 2 000 and the tail at most 4 000 scalars."""

    reduced, _ = reduce_notes("\n".join(_NINETY_LINES))
    head, tail = reduced.split("\n…\n")
    assert len(head) <= 2_000
    assert len(tail) <= 4_000
    assert len(reduced) == 1_999 + 3 + 3_999


# ----------------------------------------------------------- T100 output §2


def _check(
    proposals: list[str],
    *,
    question: str | None = None,
    navigator_input: NavigatorInput | None = None,
) -> NavigatorOutput | None:
    return validate_navigator_output(
        navigator_input or _input(notes="Tiles from the old shop. Ask Anna."),
        proposals=proposals,
        clarifying_question=question,
    )


@pytest.mark.parametrize(
    "proposal",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("Measure the wall\nthen tile it", id="multi-line"),
        pytest.param("Measure the wall\rthen tile it", id="carriage-return"),
        pytest.param("Measure the wall then tile it", id="line-separator"),
        pytest.param("m" * 201, id="over-200"),
        pytest.param("Buy tiles #home", id="hashtag"),
        pytest.param("Buy tiles @errands", id="at-tag"),
        pytest.param('Buy tiles @"big shop"', id="quoted-tag"),
        pytest.param("Buy tiles !1", id="priority-marker"),
    ],
)
def test_020_FR_021_rule_1_drops_unusable_lines(proposal: str) -> None:
    """Rule 1: trim; drop empty, multi-line, over-200 and Smart Add lines."""

    output = _check([proposal, "Measure the wall"])
    assert output is not None
    assert output.proposals == ("Measure the wall",)


def test_020_FR_021_rule_1_trims_and_keeps_exclamations_and_200_chars() -> None:
    """A trailing ``!`` is not a priority marker; exactly 200 characters pass."""

    longest = "m" * 200
    output = _check(["  Measure the wall!  ", longest, "Mail the shop, now!"])
    assert output is not None
    assert output.proposals == ("Measure the wall!", longest, "Mail the shop, now!")


@pytest.mark.parametrize(
    "proposal",
    [
        pytest.param("Measure the wall #", id="hash-at-end"),
        pytest.param("Pay the shop # later", id="hash-before-space"),
        pytest.param("Measure it ! then tile", id="bang-before-space"),
        pytest.param("Write the c# notes", id="hash-inside-word"),
        pytest.param("Mail the shop@once", id="at-inside-word"),
    ],
)
def test_020_FR_021_rule_1_keeps_sigils_the_parser_would_not_read(
    proposal: str,
) -> None:
    """Only a sigil that starts a word and is followed by a name (or ``!`` by
    any non-space) is a Smart Add token; the others are ordinary text."""

    output = _check([proposal])
    assert output is not None
    assert output.proposals == (proposal,)


def test_020_FR_025_retry_after_is_zero_below_the_limit() -> None:
    """``Retry-After`` is computed only once the owner is at the limit."""

    navigator_rate_limiter.reset()
    assert navigator_rate_limiter.retry_after_seconds("user_fresh") == 0
    for _ in range(20):
        assert navigator_rate_limiter.check("user_fresh")
    assert not navigator_rate_limiter.check("user_fresh")
    assert 1 <= navigator_rate_limiter.retry_after_seconds("user_fresh") <= 600


def test_020_FR_019_rule_2_drops_duplicates_by_formulation_key() -> None:
    """Rule 2: the current title, any sent open title and earlier proposals."""

    navigator_input = _input(
        notes="Tiles from the old shop",
        project_name="Flat",
        open_task_titles=("Buy paint", "Call the plumber"),
    )
    output = _check(
        [
            "renovate the BATHROOM.",
            "Buy  paint!",
            "Measure the wall",
            "measure the wall",
            "Pick tile samples",
        ],
        navigator_input=navigator_input,
    )
    assert output is not None
    assert output.proposals == ("Measure the wall", "Pick tile samples")


@pytest.mark.parametrize(
    ("proposal", "kept"),
    [
        pytest.param("Call Anna about the tiles", True, id="name-in-notes"),
        pytest.param("Call anna about the tiles", True, id="lower-name"),
        pytest.param("Call Boris about the tiles", False, id="invented-name"),
        pytest.param("Measure the wall", True, id="first-word-capital"),
        pytest.param("Visit IKEA for tiles", False, id="invented-brand"),
        pytest.param("Order 12 tiles", False, id="invented-number"),
        pytest.param("Spend $50 on tiles", False, id="invented-amount"),
        pytest.param("Spend €50 on tiles", False, id="invented-currency"),
        pytest.param("Go to the shop on Monday", False, id="invented-weekday"),
        pytest.param("Сходить в магазин в понедельник", False, id="ru-weekday"),
        pytest.param("Заказать плитку к марту", False, id="ru-month"),
        pytest.param("Order tiles in march", False, id="en-month-lower"),
        pytest.param("Visit the old shop", True, id="plain-words"),
    ],
)
def test_020_FR_021_rule_3_grounding_check(proposal: str, kept: bool) -> None:
    """Rule 3: a capitalised token after the first word, a number, an amount
    or a date expression must occur in the input (after formulation_key)."""

    output = _check([proposal, "Write down the next step"])
    assert output is not None
    assert output.proposals is not None
    assert (proposal.strip() in output.proposals) is kept


def test_020_FR_021_rule_3_keeps_facts_present_in_the_input() -> None:
    """Numbers, amounts, dates and names from the input are allowed."""

    navigator_input = _input(
        title="Pay Anna 50 € by Monday",
        notes="Invoice 2026-10-12, Сбербанк, до понедельника, IKEA",
        project_name="Flat",
    )
    grounded = [
        "Open the Сбербанк app",
        "Transfer 50 € to Anna",
        "Ask IKEA about Monday",
        "Check the invoice 2026-10-12",
        "Позвонить до понедельника",
    ]
    for proposal in grounded:
        output = _check([proposal], navigator_input=navigator_input)
        assert output is not None
        assert output.proposals == (proposal,)


def test_020_FR_021_rule_4_question_when_no_proposal_survives() -> None:
    """Rule 4: none survive and the question is grounded → the question."""

    output = _check(["Call Boris"], question="  Which wall comes first?  ")
    assert output == NavigatorOutput(
        proposals=None, clarifying_question="Which wall comes first?"
    )


def test_020_FR_021_rule_4_proposals_win_over_a_question_and_cap_at_three() -> None:
    """At least one survivor → proposals only, at most three."""

    output = _check(
        ["Measure the wall", "Pick tile samples", "Visit the old shop", "Ask Anna"],
        question="Which wall?",
    )
    assert output == NavigatorOutput(
        proposals=("Measure the wall", "Pick tile samples", "Visit the old shop"),
        clarifying_question=None,
    )


@pytest.mark.parametrize(
    ("proposals", "question"),
    [
        pytest.param([], None, id="nothing"),
        pytest.param(["Call Boris"], None, id="all-dropped"),
        pytest.param([], "Should Boris do it?", id="ungrounded-question"),
        pytest.param([], "Which wall?\nOr the floor?", id="multi-line-question"),
        pytest.param([], "   ", id="blank-question"),
    ],
)
def test_020_FR_021_rule_4_malformed(
    proposals: list[str], question: str | None
) -> None:
    """Nothing usable after rules 1–3 → ``malformed`` (None)."""

    assert _check(proposals, question=question) is None


def test_020_FR_021_project_next_action_may_ask_a_question() -> None:
    """For a project without a next action a question is allowed (M-08)."""

    navigator_input = _input(
        kind="project_next_action",
        title=None,
        project_name="Flat",
        open_task_titles=(),
    )
    output = _check(
        [], question="What is the Flat project for?", navigator_input=navigator_input
    )
    assert output == NavigatorOutput(
        proposals=None, clarifying_question="What is the Flat project for?"
    )


# ----------------------------------------------------------- T100 schema


def test_020_FR_019_strict_request_schema_rejects_extra_fields() -> None:
    """Nothing beyond FR-019 can be sent: a language field or a due date → 422."""

    body = {
        "kind": "first_step",
        "consent": {"external_processing_allowed": True, "provider": "openai"},
        "task": {"title": "Renovate the bathroom", "notes": None, "stall_reason": None},
    }
    NavigatorSuggestionRequest.model_validate(body)
    for extra in (
        {"language": "ru"},
        {"language_hint": "ru"},
        {"due_date": "2026-10-12"},
    ):
        with pytest.raises(ValidationError):
            NavigatorSuggestionRequest.model_validate({**body, **extra})
    with pytest.raises(ValidationError):
        NavigatorSuggestionRequest.model_validate(
            {**body, "task": {**body["task"], "language": "ru"}}  # type: ignore[dict-item]
        )


def test_020_FR_019_prompt_carries_exactly_the_fr_019_input() -> None:
    """The data role holds the delimited FR-019 fields and nothing else; the
    instructions are fixed text (``navigator-prompt/v1``)."""

    navigator_input = _input(
        notes="Tiles from the old shop",
        stall_reason="too_big",
        project_name="Flat",
        open_task_titles=("Buy paint", "Call the plumber"),
    )
    assert user_prompt(navigator_input) == (
        "<task_title>Renovate the bathroom</task_title>\n"
        "<task_notes>Tiles from the old shop</task_notes>\n"
        "<stall_reason>too_big</stall_reason>\n"
        "<project_name>Flat</project_name>\n"
        "<open_tasks>\n- Buy paint\n- Call the plumber\n</open_tasks>\n"
        "<kind>first_step</kind>"
    )
    instructions = system_prompt("first_step")
    assert instructions.startswith(
        "You help a person get unstuck on a task they keep postponing.\n"
        "Propose 1 to 3 concrete next physical actions"
    )
    assert "Renovate" not in instructions
    assert "Write in the same language as the task text." in instructions
    assert (
        system_prompt("project_next_action")
        .splitlines()[1]
        .startswith("Propose 1 to 3 first next actions for this project.")
    )
    assert PROMPT_VERSION == "navigator-prompt/v1"


# ----------------------------------------------------------- T101 consent


def _consent(
    *,
    provider: str = "openai",
    version: int = CONSENT_TEXT_VERSION,
    revoked: bool = False,
) -> NavigatorConsentDocument:
    granted = datetime(2026, 10, 1, 10, tzinfo=UTC)
    return NavigatorConsentDocument(
        owner_id="user_a",
        provider=provider,
        granted_at=granted,
        revoked_at=granted + timedelta(days=1) if revoked else None,
        consent_text_version=version,
    )


def test_020_FR_024_consent_is_current_only_for_the_provider_and_version() -> None:
    """A revoked grant, another provider or an older version counts as absent."""

    assert consent_is_current(_consent(), provider="openai") is True
    assert consent_is_current(None, provider="openai") is False
    assert consent_is_current(_consent(revoked=True), provider="openai") is False
    assert consent_is_current(_consent(provider="other"), provider="openai") is False
    assert consent_is_current(_consent(), provider=None) is False
    # A stored version 1 grant once the server's version is 2.
    assert consent_is_current(_consent(), provider="openai", version=2) is False
    assert CONSENT_TEXT_VERSION == 1


# ================================================================ T102 API
NAVIGATOR = "/api/review/navigator"
CONSENT = f"{NAVIGATOR}/consent"
SUGGESTIONS = f"{NAVIGATOR}/suggestions"
LOGGER = "app.modules.tasks.review"

SENTINEL_TITLE = "SENTINEL-NAVTITLE-w3Kd"
SENTINEL_NOTES = "SENTINEL-NAVNOTES-r8Pq"
SENTINEL_SIBLING = "SENTINEL-NAVSIBLING-c5Hx"
SENTINEL_PROJECT = "SENTINEL-NAVPROJECT-m1Zt"


@pytest.fixture(autouse=True)
def _deterministic_navigator(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every app built in this module uses the hermetic TEST provider.

    Autouse, so it runs before ``api_client`` builds the app; the T098 cases
    override the provider themselves. The navigator limiter is reset per test.
    """

    monkeypatch.setenv(PROVIDER_ENV, "deterministic")
    navigator_rate_limiter.reset()
    yield
    navigator_rate_limiter.reset()


def _body(
    *,
    kind: str = "first_step",
    title: str = "Renovate the bathroom",
    notes: str | None = "Tiles from the old shop",
    stall_reason: str | None = "too_big",
    project: dict[str, Any] | None = None,
    provider: str = "openai",
    allowed: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": kind,
        "consent": {"external_processing_allowed": allowed, "provider": provider},
    }
    if kind != "project_next_action":
        body["task"] = {"title": title, "notes": notes, "stall_reason": stall_reason}
    if project is not None:
        body["project"] = project
    return body


class SpyProvider:
    """A stub ``NavigatorProvider``: records calls, may run a hook or fail."""

    category = "openai"

    def __init__(
        self,
        *,
        proposals: tuple[str, ...] = ("Measure the wall", "Pick tile samples"),
        question: str | None = None,
        error: Exception | None = None,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self.proposals = proposals
        self.question = question
        self.error = error
        self.on_call = on_call
        self.inputs: list[NavigatorInput] = []

    def estimate_cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * 0.15 + output_tokens * 0.60) / 1_000_000

    def suggest(self, navigator_input: NavigatorInput) -> NavigatorProviderResult:
        self.inputs.append(navigator_input)
        if self.on_call is not None:
            self.on_call()
        if self.error is not None:
            raise self.error
        return NavigatorProviderResult(
            proposals=self.proposals,
            clarifying_question=self.question,
            input_tokens=900,
            output_tokens=40,
        )


class Nav:
    """A signed-in client with the navigator helpers."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.owner_id: str = client.get("/api/auth/me").json()["id"]
        self.keys = 0

    @property
    def container(self) -> Container:
        return self.client.app.state.container  # type: ignore[attr-defined]

    def key(self) -> dict[str, str]:
        self.keys += 1
        return {"Idempotency-Key": f"nav-{self.keys}"}

    def flag(self, mode: str) -> None:
        self.container.feature_flag_service.set_mode(
            "weekly_review", mode, operator_id="test-operator"
        )

    def status(self) -> dict[str, Any]:
        response = self.client.get(NAVIGATOR)
        assert response.status_code == 200, response.text
        assert response.headers["X-Correlation-ID"]
        return response.json()

    def grant(
        self, provider: str = "openai", version: int = CONSENT_TEXT_VERSION
    ) -> Any:
        return self.client.post(
            CONSENT,
            json={"provider": provider, "consent_text_version": version},
            headers=self.key(),
        )

    def revoke(self) -> Any:
        return self.client.delete(CONSENT, headers=self.key())

    def suggest(self, body: dict[str, Any] | None = None) -> Any:
        return self.client.post(SUGGESTIONS, json=body or _body())

    def usage(self) -> list[Any]:
        return self.container.task_repo.list_navigator_usage(self.owner_id)

    def spy(self, provider: SpyProvider) -> SpyProvider:
        self.container.navigator_service.provider = provider
        return provider


def _reason(response: Any) -> str:
    return str(response.json()["detail"]["reason"])


def _assert_error(response: Any, status: int, reason: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["detail"] == {"reason": reason}
    assert body["reference_id"]
    assert body["reference_id"] == response.headers["X-Correlation-ID"]


@pytest.fixture
def nav(api_client: TestClient, frozen_clock: FrozenClock) -> Nav:
    del frozen_clock
    return Nav(api_client)


@pytest.fixture
def ready(nav: Nav) -> Nav:
    """Flag on and a current cloud consent."""

    nav.flag("on")
    assert nav.grant().status_code == 200
    return nav


def test_020_FR_024_status_reports_provider_consent_and_availability(
    nav: Nav,
) -> None:
    """``GET /review/navigator``: provider, no consent yet, available."""

    with allure.step("read the navigator status"):
        status = nav.status()
    assert status == {
        "provider": "openai",
        "consent": None,
        "consent_current": False,
        "consent_text_version": CONSENT_TEXT_VERSION,
        "available": True,
    }


def test_020_FR_024_grant_then_status_is_current_and_idempotent(nav: Nav) -> None:
    """A grant is stored once per provider; granting again changes nothing."""

    nav.flag("on")
    with allure.step("grant twice"):
        first = nav.grant()
        second = nav.grant()
    assert first.status_code == 200, first.text
    assert second.json() == first.json()
    status = nav.status()
    assert status["consent_current"] is True
    assert status["consent"]["revoked_at"] is None
    assert status["consent"]["consent_text_version"] == CONSENT_TEXT_VERSION
    stored = nav.container.task_repo.list_navigator_consents(nav.owner_id)
    assert [(c.provider, c.history) for c in stored] == [("openai", [])]


@pytest.mark.parametrize(
    ("provider", "version", "reason"),
    [
        pytest.param(
            "anthropic", CONSENT_TEXT_VERSION, "provider_mismatch", id="mismatch"
        ),
        pytest.param(
            "openai", CONSENT_TEXT_VERSION + 1, "consent_text_outdated", id="newer"
        ),
    ],
)
def test_020_FR_024_grant_refuses_another_provider_or_text_version(
    nav: Nav, provider: str, version: int, reason: str
) -> None:
    """Grant → 400 ``provider_mismatch`` / ``consent_text_outdated``."""

    nav.flag("on")
    with allure.step(f"grant {provider} v{version}"):
        response = nav.grant(provider, version)
    _assert_error(response, 400, reason)
    assert nav.container.task_repo.list_navigator_consents(nav.owner_id) == []


def test_020_FR_045_consent_mutations_need_an_idempotency_key(nav: Nav) -> None:
    """Grant and revoke are mutations: 400 without ``Idempotency-Key``."""

    nav.flag("on")
    grant = nav.client.post(
        CONSENT, json={"provider": "openai", "consent_text_version": 1}
    )
    revoke = nav.client.delete(CONSENT)
    assert grant.status_code == 400, grant.text
    assert revoke.status_code == 400, revoke.text
    assert grant.headers["X-Correlation-ID"]


def test_020_FR_024_flag_off_read_and_revoke_work_grant_and_suggest_are_404(
    nav: Nav,
) -> None:
    """Quickstart Scenario 4 step 9: the privacy routes are never gated."""

    nav.flag("on")
    assert nav.grant().status_code == 200
    nav.flag("off")
    with allure.step("flag off: read and revoke"):
        status = nav.status()
        revoke = nav.revoke()
    assert status["consent_current"] is True
    assert revoke.status_code == 204, revoke.text
    assert revoke.headers["X-Correlation-ID"]
    assert nav.status()["consent"]["revoked_at"] is not None
    with allure.step("flag off: grant and suggestions are hidden"):
        _assert_error(nav.grant(), 404, "weekly_review_disabled")
        _assert_error(nav.suggest(), 404, "weekly_review_disabled")
    nav.flag("on")
    with allure.step("flag on again: the revoked consent stops the request"):
        _assert_error(nav.suggest(), 400, "navigator_consent_required")


def test_020_FR_024_regrant_after_revoke_keeps_content_free_history(
    nav: Nav, frozen_clock: FrozenClock
) -> None:
    """Re-granting after a revoke sets a new grant and keeps the old one."""

    nav.flag("on")
    assert nav.grant().status_code == 200
    frozen_clock.advance(hours=1)
    assert nav.revoke().status_code == 204
    assert nav.revoke().status_code == 204
    frozen_clock.advance(hours=1)
    assert nav.grant().status_code == 200
    (stored,) = nav.container.task_repo.list_navigator_consents(nav.owner_id)
    assert stored.revoked_at is None
    assert stored.granted_at == frozen_clock()
    assert [sorted(entry) for entry in stored.history] == [
        ["consent_text_version", "granted_at", "revoked_at"]
    ]
    assert nav.suggest().status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_body(allowed=False), id="not-allowed"),
        pytest.param(_body(provider="other"), id="other-provider"),
    ],
)
def test_020_FR_024_request_consent_echo_must_match(
    ready: Nav, body: dict[str, Any]
) -> None:
    """The request's own consent must allow the configured provider."""

    spy = ready.spy(SpyProvider())
    _assert_error(ready.suggest(body), 400, "navigator_consent_required")
    assert spy.inputs == []


def test_020_FR_024_no_grant_revoked_or_older_version_is_consent_required(
    nav: Nav,
) -> None:
    """Quickstart Scenario 4 steps 3 and 5: no request reaches the provider."""

    nav.flag("on")
    spy = nav.spy(SpyProvider())
    with allure.step("no grant"):
        _assert_error(nav.suggest(), 400, "navigator_consent_required")
    assert nav.grant().status_code == 200
    with allure.step("the server's consent text moves to version 2"):
        nav.container.navigator_service.consent_text_version = 2
        _assert_error(nav.suggest(), 400, "navigator_consent_required")
        status = nav.status()
    assert status["consent_current"] is False
    assert status["consent_text_version"] == 2
    nav.container.navigator_service.consent_text_version = CONSENT_TEXT_VERSION
    assert nav.revoke().status_code == 204
    with allure.step("revoked"):
        _assert_error(nav.suggest(), 400, "navigator_consent_required")
    assert spy.inputs == []
    assert nav.usage() == []


def test_020_FR_019_suggestion_returns_validated_proposals(ready: Nav) -> None:
    """Quickstart Scenario 4 step 2: 1–3 proposals from the deterministic
    provider, none equal to an open title; no Idempotency-Key needed."""

    body = _body(project={"name": "Flat", "open_task_titles": ["Buy paint"]})
    with allure.step("ask for a first step"):
        response = ready.suggest(body)
    assert response.status_code == 200, response.text
    assert response.headers["X-Correlation-ID"]
    answer = response.json()
    uuid.UUID(answer["request_id"])
    assert answer["provider"] == "openai"
    assert answer["notes_truncated"] is False
    assert answer["clarifying_question"] is None
    assert 1 <= len(answer["proposals"]) <= 3
    assert "Buy paint" not in answer["proposals"]
    (usage,) = ready.usage()
    assert (usage.calls, usage.shown, usage.reserved_cost_usd) == (1, 1, 0.0)
    assert usage.estimated_cost_usd > 0


def test_020_FR_021_clarifying_question_and_project_next_action(ready: Nav) -> None:
    """A question is returned instead of proposals and is not counted as shown;
    a project without a next action gets proposals from the project only."""

    question = ready.suggest(_body(notes="navigator-test:question"))
    assert question.status_code == 200, question.text
    assert question.json()["proposals"] is None
    assert question.json()["clarifying_question"]
    project = ready.suggest(
        _body(
            kind="project_next_action", project={"name": "Flat", "open_task_titles": []}
        )
    )
    assert project.status_code == 200, project.text
    assert project.json()["proposals"]
    (usage,) = ready.usage()
    assert (usage.calls, usage.shown) == (2, 1)


def test_020_FR_020_a_suggestion_writes_nothing_to_any_task(ready: Nav) -> None:
    """Nothing is written without confirmation: the owner's tasks keep their
    revision, title and notes after suggestions of every kind."""

    created = ready.client.post(
        "/api/tasks",
        json={"title": "Renovate the bathroom", "details": "Tiles", "state": "next"},
        headers=ready.key(),
    )
    assert created.status_code == 201, created.text
    before = ready.client.get("/api/tasks").json()
    for kind in ("first_step", "reformulate", "project_next_action"):
        project = {"name": "Flat", "open_task_titles": []}
        response = ready.suggest(_body(kind=kind, project=project))
        assert response.status_code == 200, response.text
    assert ready.client.get("/api/tasks").json() == before


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"language_hint": "ru"}, id="language-hint"),
        pytest.param({"due_date": "2026-10-12"}, id="due-date"),
    ],
)
def test_020_FR_019_endpoint_refuses_any_extra_field(
    ready: Nav, extra: dict[str, str]
) -> None:
    """Quickstart Scenario 4 step 5: an extra field → 422; nothing reaches the
    provider and nothing is counted."""

    spy = ready.spy(SpyProvider())
    response = ready.suggest({**_body(), **extra})
    assert response.status_code == 422, response.text
    assert response.headers["X-Correlation-ID"]
    assert spy.inputs == []
    assert ready.usage() == []


def test_020_FR_019_server_backstop_reduces_unreduced_notes(ready: Nav) -> None:
    """Notes over the budget that are not in reduced form are reduced by the
    server (``notes_truncated: true``); the provider sees the reduced text."""

    spy = ready.spy(SpyProvider())
    notes = "a" * 3_000 + "\n" + "b" * 3_001
    response = ready.suggest(_body(notes=notes))
    assert response.status_code == 200, response.text
    assert response.json()["notes_truncated"] is True
    assert spy.inputs[0].task_notes == "\n…\n" + "b" * 3_001
    already = "h" * 2_000 + "\n…\n" + "t" * 4_000
    response = ready.suggest(_body(notes=already))
    assert response.json()["notes_truncated"] is False
    assert spy.inputs[1].task_notes == already


def test_020_FR_019_input_too_large_never_reaches_the_provider(ready: Nav) -> None:
    """Above ``MAX_INPUT_TOKENS`` even after reduction → 400, nothing reserved."""

    spy = ready.spy(SpyProvider())
    body = _body(
        title="t" * 500,
        notes="n" * 2_000 + "\n…\n" + "n" * 4_000,
        project={"name": "p" * 500, "open_task_titles": ["s" * 500] * 20},
    )
    _assert_error(ready.suggest(body), 400, "navigator_input_too_large")
    assert spy.inputs == []
    assert ready.usage() == []


def test_020_FR_025_rate_limit_is_429_with_retry_after(ready: Nav) -> None:
    """20 calls per 10 minutes per owner; the 21st → 429 with ``Retry-After``."""

    for _ in range(20):
        assert ready.suggest().status_code == 200
    with allure.step("the 21st call"):
        response = ready.suggest()
    _assert_error(response, 429, "navigator_rate_limited")
    assert 1 <= int(response.headers["Retry-After"]) <= 600


def test_020_FR_025_per_call_cost_cap(ready: Nav) -> None:
    """The per-call estimate above ``MAX_COST_USD`` → 429 ``navigator_cost_cap``."""

    spy = ready.spy(SpyProvider())
    ready.container.navigator_service.limits = replace(
        ready.container.navigator_service.limits, max_cost_usd=0.000_000_1
    )
    _assert_error(ready.suggest(), 429, "navigator_cost_cap")
    assert spy.inputs == []
    assert ready.usage() == []


def test_020_FR_025_daily_cost_cap_counts_settled_and_reserved(
    ready: Nav, frozen_clock: FrozenClock
) -> None:
    """The owner's day (settled + reserved + this estimate) above the daily cap
    → 429; the next UTC day starts a fresh row."""

    spy = ready.spy(SpyProvider())
    ready.container.task_repo.save_navigator_usage(
        NavigatorUsageDocument(
            owner_id=ready.owner_id,
            day=frozen_clock().date(),
            calls=9,
            estimated_cost_usd=0.15,
            reserved_cost_usd=0.05,
        )
    )
    _assert_error(ready.suggest(), 429, "navigator_cost_cap")
    assert spy.inputs == []
    frozen_clock.advance(days=1)
    assert ready.suggest().status_code == 200
    assert [u.calls for u in ready.usage()] == [9, 1]


@pytest.mark.parametrize(
    ("marker", "reason"),
    [
        pytest.param("navigator-test:timeout", "navigator_timeout", id="timeout"),
        pytest.param(
            "navigator-test:provider_error", "navigator_provider_error", id="error"
        ),
        pytest.param(
            "navigator-test:malformed", "navigator_malformed_output", id="malformed"
        ),
    ],
)
def test_020_FR_025_provider_failures_are_503_with_reference_id(
    ready: Nav, marker: str, reason: str
) -> None:
    """Quickstart Scenario 4 step 4, forced in the deterministic provider."""

    with allure.step(f"force {reason}"):
        response = ready.suggest(_body(notes=marker))
    _assert_error(response, 503, reason)
    (usage,) = ready.usage()
    assert usage.reserved_cost_usd == 0.0
    assert usage.shown == 0
    if reason == "navigator_malformed_output":
        assert usage.estimated_cost_usd > 0
    else:
        assert usage.estimated_cost_usd == 0.0


def test_020_FR_025_reservation_is_released_on_timeout(ready: Nav) -> None:
    """Reserve → call → release: a timed-out call leaves nothing reserved."""

    seen: dict[str, Any] = {}

    def during_call() -> None:
        (usage,) = ready.usage()
        seen["reserved"] = usage.reserved_cost_usd
        seen["calls"] = usage.calls

    ready.spy(SpyProvider(error=NavigatorProviderTimeout(), on_call=during_call))
    _assert_error(ready.suggest(), 503, "navigator_timeout")
    assert seen["reserved"] > 0
    assert seen["calls"] == 1
    (usage,) = ready.usage()
    assert (usage.reserved_cost_usd, usage.estimated_cost_usd) == (0.0, 0.0)


def test_020_FR_025_provider_call_holds_no_command_lock(ready: Nav) -> None:
    """Lock case (contracts/http.md §7): a provider stub that takes
    ``command_lock`` for another owner neither deadlocks nor waits, because
    the call runs between the reservation and the settlement with no lock."""

    repo = ready.container.task_repo
    seen: dict[str, Any] = {}

    def take_another_owners_lock() -> None:
        acquired = threading.Event()

        def worker() -> None:
            with repo.command_lock("user_another_owner"):
                acquired.set()

        started = time.monotonic()
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        seen["acquired"] = acquired.wait(timeout=2.0)
        seen["waited"] = time.monotonic() - started
        with repo.command_lock("user_another_owner"):
            seen["same_thread"] = True
        thread.join(timeout=5.0)
        (usage,) = ready.usage()
        seen["reserved_during_call"] = usage.reserved_cost_usd

    ready.spy(SpyProvider(on_call=take_another_owners_lock))
    with allure.step("suggest while the stub takes another owner's lock"):
        response = ready.suggest()
    assert response.status_code == 200, response.text
    assert seen["acquired"] is True
    assert seen["waited"] < 0.5
    assert seen["same_thread"] is True
    assert seen["reserved_during_call"] > 0
    (usage,) = ready.usage()
    assert usage.reserved_cost_usd == 0.0


def test_020_FR_044_suggestion_persists_nothing_and_logs_one_line(
    ready: Nav, caplog: pytest.LogCaptureFixture
) -> None:
    """Quickstart Scenario 4 step 7: no idempotency record, no
    ``task-commands/`` entry, no sentinel text stored or logged; one log line
    of codes and counts; ``navigator_usage.shown`` counted."""

    repo = ready.container.task_repo
    before = len(repo.list_idempotency_for_owner(owner_id=ready.owner_id))
    caplog.set_level(logging.DEBUG)
    body = _body(
        title=f"Renovate {SENTINEL_TITLE}",
        notes=f"Ask {SENTINEL_NOTES}",
        stall_reason="waiting_on_someone",
        project={"name": SENTINEL_PROJECT, "open_task_titles": [SENTINEL_SIBLING]},
    )
    with allure.step("one suggestion with sentinel content"):
        response = ready.suggest(body)
    assert response.status_code == 200, response.text
    assert any(SENTINEL_TITLE in text for text in response.json()["proposals"])
    assert len(repo.list_idempotency_for_owner(owner_id=ready.owner_id)) == before
    assert not repo.resolve("task-commands", ready.owner_id).exists() or not any(
        repo.resolve("task-commands", ready.owner_id).iterdir()
    )
    (usage,) = ready.usage()
    assert usage.shown == 1
    sentinels = (SENTINEL_TITLE, SENTINEL_NOTES, SENTINEL_SIBLING, SENTINEL_PROJECT)
    for path in Path(repo.db_path).parent.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for sentinel in sentinels:
                assert sentinel.encode() not in data, path.name
    lines = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    navigator_lines = [line for line in lines if line.startswith("navigator ")]
    assert len(navigator_lines) == 1
    assert navigator_lines[0].startswith("navigator outcome=success request_id=")
    assert f"request_id={response.json()['request_id']}" in navigator_lines[0]
    assert "proposals=" in navigator_lines[0]
    for record in caplog.records:
        message = record.getMessage()
        for text in (*sentinels, "waiting_on_someone"):
            assert text not in message


@pytest.mark.parametrize(
    "notes",
    [
        pytest.param("navigator-test:timeout", id="timeout"),
        pytest.param("navigator-test:malformed", id="malformed"),
        pytest.param(None, id="consent"),
    ],
)
def test_020_FR_044_failure_paths_log_one_content_free_line(
    ready: Nav, caplog: pytest.LogCaptureFixture, notes: str | None
) -> None:
    """Every outcome logs exactly one ``navigator`` line without content."""

    caplog.set_level(logging.DEBUG)
    if notes is None:
        assert ready.revoke().status_code == 204
    response = ready.suggest(
        _body(title=SENTINEL_TITLE, notes=f"{notes or ''} {SENTINEL_NOTES}")
    )
    assert response.status_code in {400, 503}
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER and r.getMessage().startswith("navigator ")
    ]
    assert len(lines) == 1
    for record in caplog.records:
        assert SENTINEL_TITLE not in record.getMessage()
        assert SENTINEL_NOTES not in record.getMessage()


def test_020_FR_026_later_decision_stores_ai_use_and_request_id_only(
    ready: Nav, frozen_clock: FrozenClock
) -> None:
    """A decision confirming an edited proposal records ``ai_use`` and the
    server's ``request_id``; the proposal text is in no review record."""

    repo = ready.container.task_repo
    settings = ReviewSettingsDocument(
        owner_id=ready.owner_id,
        activated_at=frozen_clock() - timedelta(days=30),
        last_effective_sweep_at=frozen_clock() - timedelta(days=30),
    )
    repo.save_review_settings(settings)
    created = ready.client.post(
        "/api/tasks",
        json={"title": "Renovate the bathroom", "state": "next"},
        headers=ready.key(),
    ).json()
    frozen_clock.advance(days=15)
    task = ready.client.get(f"/api/tasks/{created['id']}").json()
    suggestion = ready.suggest().json()
    proposal = suggestion["proposals"][0]
    edited = f"{proposal} first"
    response = ready.client.post(
        f"/api/tasks/{task['id']}/decisions",
        json={
            "type": "first_step",
            "expected_revision": task["revision"],
            "formulation_id": task["formulation"]["id"],
            "title": edited,
            "ai_use": "edited",
            "navigator_request_id": suggestion["request_id"],
        },
        headers=ready.key(),
    )
    assert response.status_code == 200, response.text
    (decision,) = repo.list_review_decisions(ready.owner_id)
    assert decision.ai_use == "edited"
    assert decision.navigator_request_id == suggestion["request_id"]
    stored = decision.model_dump_json()
    assert proposal not in stored
    assert edited not in stored


def test_020_FR_025_disabled_provider_builds_and_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``disabled`` builds: status says ``available: false`` with no provider,
    a suggestion is 503 ``navigator_disabled`` and a grant names no provider."""

    monkeypatch.setenv(PROVIDER_ENV, "disabled")
    client = _signed_in_client(tmp_path, monkeypatch)
    nav = Nav(client)
    nav.flag("on")
    status = nav.status()
    assert status == {
        "provider": None,
        "consent": None,
        "consent_current": False,
        "consent_text_version": CONSENT_TEXT_VERSION,
        "available": False,
    }
    _assert_error(nav.suggest(), 503, "navigator_disabled")
    _assert_error(nav.grant(), 400, "provider_mismatch")
    client.close()


def test_020_FR_045_navigator_routes_need_a_session(
    anonymous_api_client: TestClient,
) -> None:
    """Authentication comes first: 401 with a correlation id on every route."""

    for method, path in (
        ("get", NAVIGATOR),
        ("post", CONSENT),
        ("delete", CONSENT),
        ("post", SUGGESTIONS),
    ):
        response = anonymous_api_client.request(method, path, json=_body())
        assert response.status_code == 401, (method, path)
        assert response.headers["X-Correlation-ID"]


def _signed_in_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "nav-disabled"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    container: Container = app.state.container
    container.invite_repo.create(Invite(code="invite_nav", created_at=utcnow()))
    client = TestClient(app)
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "navigator@example.com",
            "password": "correct-horse-battery-staple",
            "invite_code": "invite_nav",
        },
    )
    assert response.status_code == 201, response.text
    return client
