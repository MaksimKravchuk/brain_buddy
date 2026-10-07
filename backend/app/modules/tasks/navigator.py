"""The weekly-review AI navigator (spec 020 US3, contracts/navigator.md).

This module owns the navigator's rules and holds **no HTTP client** (ADR-0001
rule 9; the import-linter contract forbids ``httpx`` and ``app.ai`` here):

- the ``NavigatorProvider`` port that the concrete adapter in
  ``app.ai.review_navigator`` implements, and the one ``NavigatorInput`` type
  (FR-019: exactly the task's title, notes and stall reason, the project's name
  and up to 20 open sibling titles, plus the kind of suggestion);
- the versioned prompt (``navigator-prompt/v1``, §3);
- ``reduce_notes`` (§1) and ``validate_navigator_output`` (§2 rules 1–4), the
  same rules the Swift core and the web run;
- the consent rules with ``CONSENT_TEXT_VERSION`` (data-model E8);
- ``NavigatorService``: consent, rate limit, cost admission outside the task
  command lock, the provider call and one content-free log line (http §7).
"""

from __future__ import annotations

import logging
import math
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import uuid4

from app.schemas.review import NavigatorSuggestionRequest

from .formulation import formulation_key
from .review_domain import (
    NavigatorConsentDocument,
    NavigatorUsageDocument,
    ReviewRequestError,
)
from .review_rules import drop_duplicate_proposals

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .repository import TaskRepository

logger = logging.getLogger("app.modules.tasks.review")

NavigatorKind = Literal["first_step", "reformulate", "project_next_action"]

PROMPT_VERSION = "navigator-prompt/v1"
CHARS_PER_TOKEN = 3
"""The server's conservative token estimate (contracts/navigator.md §1)."""


# ----------------------------------------------------------------- the port
@dataclass(frozen=True, slots=True)
class NavigatorInput:
    """FR-019: the only data any model receives. No ids, dates or language."""

    kind: NavigatorKind
    task_title: str | None
    task_notes: str | None
    stall_reason: str | None
    project_name: str | None
    open_task_titles: tuple[str, ...]
    notes_truncated: bool = False


@dataclass(frozen=True, slots=True)
class NavigatorProviderResult:
    """What a provider returned, before the §2 validation.

    ``input_tokens`` / ``output_tokens`` are the provider's own usage figures
    when it reports them, used to settle the cost reservation.
    """

    proposals: tuple[str, ...]
    clarifying_question: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None


class NavigatorProviderTimeout(Exception):
    """The provider did not answer within the configured timeout."""


class NavigatorProviderFailure(Exception):
    """Transport or provider error; carries no request or response content."""


class NavigatorInternalError(RuntimeError):
    """An undeclared exception from a provider, re-raised without its text.

    The message is the original class name only, and it is raised outside
    the handling ``except`` block, so it has no ``__cause__`` and no
    ``__context__``: no logger, and no framework that re-chains, can reach
    input or model output echoed in the original (FR-044).
    """


class NavigatorProvider(Protocol):
    """The cloud provider port (contracts/http.md §7 "Adapter location")."""

    @property
    def category(self) -> str | None:
        """The provider name shown in consent copy; ``None`` when disabled."""

    def estimate_cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        """The cost of one call with these token counts, in US dollars."""

    def suggest(self, navigator_input: NavigatorInput) -> NavigatorProviderResult:
        """One provider call; raises ``NavigatorProviderTimeout`` or
        ``NavigatorProviderFailure``; never retries."""


# ----------------------------------------------------------------- prompt §3
_INSTRUCTIONS = """\
You help a person get unstuck on a task they keep postponing.
{opening} Each proposal is one short imperative line.
Rules:
- Write in the same language as the task text.
- Use only facts present in the input. Never invent people, places, amounts,
  dates, brands or organisations.
- Do not repeat the current wording or any listed open task.
- If the input is too vague to propose a grounded step, ask exactly one short
  clarifying question instead of proposing.
- Stall reason guidance: unclear → a step that clarifies the outcome; too_big →
  the smallest first slice; missing_info → a step that obtains the information;
  waiting_on_someone → a step that contacts or follows up; no_energy → a
  2-minute starter step; no_longer_matters → a step that decides to drop or
  delegate it."""

_TASK_OPENING = (
    "Propose 1 to 3 concrete next physical actions that would take under 30 "
    "minutes\neach and could be started today."
)
_PROJECT_OPENING = "Propose 1 to 3 first next actions for this project."


def system_prompt(kind: NavigatorKind) -> str:
    """The instruction role of ``navigator-prompt/v1`` (contracts/navigator.md §3)."""

    opening = _PROJECT_OPENING if kind == "project_next_action" else _TASK_OPENING
    return _INSTRUCTIONS.format(opening=opening)


def _data(value: str) -> str:
    """User text for the data role: every ``<`` is sent as ``&lt;``, so
    content can neither end its own field nor forge another (§3). Runs after
    ``reduce_notes``; the 6 003-scalar notes limit counts the text before."""

    return value.replace("<", "&lt;")


def user_prompt(navigator_input: NavigatorInput) -> str:
    """The data role: delimited input, never interpolated into instructions."""

    lines: list[str] = []
    if navigator_input.task_title is not None:
        lines.append(f"<task_title>{_data(navigator_input.task_title)}</task_title>")
    if navigator_input.task_notes:
        lines.append(f"<task_notes>{_data(navigator_input.task_notes)}</task_notes>")
    if navigator_input.stall_reason is not None:
        lines.append(f"<stall_reason>{navigator_input.stall_reason}</stall_reason>")
    if navigator_input.project_name is not None:
        project = _data(navigator_input.project_name)
        lines.append(f"<project_name>{project}</project_name>")
    lines.append("<open_tasks>")
    lines.extend(f"- {_data(title)}" for title in navigator_input.open_task_titles)
    lines.append("</open_tasks>")
    lines.append(f"<kind>{navigator_input.kind}</kind>")
    return "\n".join(lines)


def estimate_input_tokens(navigator_input: NavigatorInput) -> int:
    """Instructions plus data at 3 characters per token (a guard, §1)."""

    characters = len(system_prompt(navigator_input.kind)) + len(
        user_prompt(navigator_input)
    )
    return math.ceil(characters / CHARS_PER_TOKEN)


# ------------------------------------------------------- reduce_notes §1
NOTES_BUDGET_CHARS = 6_000
NOTES_HEAD_CHARS = 2_000
NOTES_TAIL_CHARS = 4_000
NOTES_SEPARATOR = "\n…\n"
"""U+000A U+2026 U+000A: the one line put between the kept head and tail."""


def _fitting_count(lines: list[str], budget: int) -> int:
    """How many leading ``lines``, joined by U+000A, fit ``budget`` scalars."""

    used = 0
    for count, line in enumerate(lines):
        cost = len(line) + (1 if count else 0)
        if used + cost > budget:
            return count
        used += cost
    return len(lines)


def reduce_notes(notes: str) -> tuple[str, bool]:
    """The one shared reduction (contracts/navigator.md §1, owner decision NC-3).

    Notes of at most 6 000 scalars are unchanged. Longer notes keep the first
    whole lines up to 2 000 scalars and the last whole lines up to 4 000,
    joined by ``NOTES_SEPARATOR``; lines are split on U+000A with a preceding
    U+000D dropped. The second value is ``True`` when a line was dropped; when
    every line fits, the lines come back rejoined with U+000A only. Notes that
    already hold a ``…`` line get no special case. The result is at most 6 003
    scalars, the request limit, and reducing it again returns the same text.
    """

    if len(notes) <= NOTES_BUDGET_CHARS:
        return notes, False
    lines = [line.removesuffix("\r") for line in notes.split("\n")]
    head = _fitting_count(lines, NOTES_HEAD_CHARS)
    tail = _fitting_count(lines[head:][::-1], NOTES_TAIL_CHARS)
    if head + tail == len(lines):
        return "\n".join(lines), False
    kept_head = "\n".join(lines[:head])
    kept_tail = "\n".join(lines[len(lines) - tail :])
    return kept_head + NOTES_SEPARATOR + kept_tail, True


# ------------------------------------------------------------ output §2
MAX_PROPOSALS = 3
MAX_PROPOSAL_CHARS = 200
MAX_QUESTION_CHARS = 500
_SMART_ADD_LEFT_WRAPPERS = "([{"

_EN_DATE_WORDS = frozenset(
    {
        "january",
        "february",
        "march",
        "april",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "tonight",
        "tomorrow",
    }
)
"""Lower-case English date words; "may" is left to the capital-letter rule
because the lower-case word is the common verb."""

_RU_DATE_STEMS = (
    "январ",
    "феврал",
    "март",
    "апрел",
    "июн",
    "июл",
    "август",
    "сентябр",
    "октябр",
    "ноябр",
    "декабр",
    "понедельник",
    "вторник",
    "четверг",
    "пятниц",
    "суббот",
    "воскресень",
)
_RU_DATE_WORDS = frozenset(
    {
        "май",
        "мая",
        "мае",
        "маю",
        "маем",
        "среда",
        "среду",
        "среды",
        "среде",
        "средой",
        "завтра",
        "послезавтра",
    }
)
_DATE_PHRASES = ("next week", "next month", "this weekend", "на следующей неделе")
"""Relative date expressions of several words, as ``formulation_key`` words;
each must occur as a whole in one input field (§2 rule 3)."""

MAX_EXEMPT_DURATION_MINUTES = 30
"""§2 rule 3: the prompt asks for steps that "would take under 30 minutes" and
for "a 2-minute starter step", so such a duration needs no grounding."""

_PROMPT_SOURCED_WORDS = frozenset({"today", "сегодня"})
"""§2 rule 3: the prompt asks for actions that "could be started today", so
"today" needs no grounding, in either language and in any case."""

_MINUTE_WORDS = frozenset({"min", "mins", "minute", "minutes", "мин"})
_MINUTE_STEM = "минут"


@dataclass(frozen=True, slots=True)
class NavigatorOutput:
    """Exactly one of ``proposals`` (1..3) and ``clarifying_question``."""

    proposals: tuple[str, ...] | None
    clarifying_question: str | None


def _single_line(value: str, limit: int) -> str | None:
    """Rule 1 shape: trimmed, non-empty, one line, at most ``limit`` scalars."""

    text = value.strip()
    if not text or len(text.splitlines()) != 1 or len(text) > limit:
        return None
    return text


def _is_name_char(char: str) -> bool:
    return char == "_" or unicodedata.category(char)[0] in {"L", "M", "N"}


def _has_smart_add_token(text: str) -> bool:
    """A ``#``/``@`` tag or a ``!`` priority marker the task parser would read.

    The sigil must start a word (string start, whitespace or an opening
    bracket), as in the Smart Add grammar; a ``!`` ending a word is kept.
    """

    for index, sigil in enumerate(text):
        if sigil not in "#@!":
            continue
        if index and not (
            text[index - 1].isspace() or text[index - 1] in _SMART_ADD_LEFT_WRAPPERS
        ):
            continue
        following = text[index + 1 : index + 2]
        if not following:
            continue
        if sigil == "!":
            if not following.isspace():
                return True
        elif following == '"' or _is_name_char(following):
            return True
    return False


def is_date_word(key: str) -> bool:
    """A month, weekday or relative day word (``formulation_key`` form, §2
    rule 3), English or Russian, in any case once keyed."""

    return (
        key in _EN_DATE_WORDS or key in _RU_DATE_WORDS or key.startswith(_RU_DATE_STEMS)
    )


def _needs_grounding(token: str, *, first: bool, key: str) -> bool:
    """Rule 3 triggers: a capitalised word after the first, a number, a
    currency amount or a date expression."""

    letters = [char for char in token if char.isalpha()]
    capitalised = bool(letters) and letters[0].isupper()
    return (
        (capitalised and not first)
        or any(char.isdecimal() for char in token)
        or any(unicodedata.category(char) == "Sc" for char in token)
        or is_date_word(key)
    )


def _is_minute_word(word: str) -> bool:
    return word in _MINUTE_WORDS or word.startswith(_MINUTE_STEM)


def _is_short_minutes(word: str) -> bool:
    """ASCII digits only, at most ``MAX_EXEMPT_DURATION_MINUTES``."""

    return (
        word.isascii() and word.isdigit() and int(word) <= MAX_EXEMPT_DURATION_MINUTES
    )


def _duration_tokens(keys: Sequence[str]) -> set[int]:
    """Indexes of the tokens of a duration of at most 30 minutes: a number
    joined to its minute word ("2-minute", "10-минутный") or followed by one
    ("10 minutes", "5 мин", "2 минуты")."""

    exempt: set[int] = set()
    for index, key in enumerate(keys):
        words = key.split()
        if not words or not _is_short_minutes(words[0]):
            continue
        if len(words) == 2 and _is_minute_word(words[1]):
            exempt.add(index)
        elif len(words) == 1 and index + 1 < len(keys):
            following = keys[index + 1].split()
            if following and _is_minute_word(following[0]):
                exempt.update((index, index + 1))
    return exempt


def grounding_terms(text: str) -> tuple[str, ...]:
    """What rule 3 must find in the input, as ``formulation_key`` text: each
    trigger token (a short duration and "today" excepted) and each relative
    date phrase."""

    tokens = text.split()
    keys = [formulation_key(token) for token in tokens]
    exempt = _duration_tokens(keys)
    exempt.update(i for i, key in enumerate(keys) if key in _PROMPT_SOURCED_WORDS)
    terms = [
        key
        for index, (token, key) in enumerate(zip(tokens, keys, strict=True))
        if key
        and index not in exempt
        and _needs_grounding(token, first=index == 0, key=key)
    ]
    keyed = f" {formulation_key(text)} "
    terms.extend(phrase for phrase in _DATE_PHRASES if f" {phrase} " in keyed)
    return tuple(terms)


def _input_keys(navigator_input: NavigatorInput) -> tuple[str, ...]:
    fields = (
        navigator_input.task_title,
        navigator_input.task_notes,
        navigator_input.project_name,
        *navigator_input.open_task_titles,
    )
    return tuple(f" {formulation_key(value)} " for value in fields if value)


def _is_grounded(text: str, input_keys: tuple[str, ...]) -> bool:
    """Rule 3 (FR-021): every grounding term occurs, after ``formulation_key``,
    as whole words in one input field (case-insensitively)."""

    return all(
        any(f" {term} " in field for field in input_keys)
        for term in grounding_terms(text)
    )


def validate_navigator_output(
    navigator_input: NavigatorInput,
    *,
    proposals: Sequence[str],
    clarifying_question: str | None,
) -> NavigatorOutput | None:
    """Rules 1–4 of contracts/navigator.md §2; ``None`` means ``malformed``.

    Identical on the server and in the Swift and web validators; rule 5 (the
    project-wide duplicate filter beyond the 20 sent titles) is the clients'.
    """

    shaped = [
        text
        for text in (_single_line(value, MAX_PROPOSAL_CHARS) for value in proposals)
        if text is not None and not _has_smart_add_token(text)
    ]
    unique = drop_duplicate_proposals(
        shaped,
        current_title=navigator_input.task_title or "",
        open_titles=navigator_input.open_task_titles,
    )
    input_keys = _input_keys(navigator_input)
    grounded = [text for text in unique if _is_grounded(text, input_keys)]
    if grounded:
        return NavigatorOutput(
            proposals=tuple(grounded[:MAX_PROPOSALS]), clarifying_question=None
        )
    question = (
        None
        if clarifying_question is None
        else _single_line(clarifying_question, MAX_QUESTION_CHARS)
    )
    if question is not None and _is_grounded(question, input_keys):
        return NavigatorOutput(proposals=None, clarifying_question=question)
    return None


# ------------------------------------------------------------- consent E8
CONSENT_TEXT_VERSION = 1
"""The version of the consent text (the FR-019 data list and the provider).

Bump it whenever either changes: every stored grant of a lower version then
counts as absent and the consent screen appears again (FR-024, data-model E8).
"""


def consent_is_current(
    consent: NavigatorConsentDocument | None,
    *,
    provider: str | None,
    version: int = CONSENT_TEXT_VERSION,
) -> bool:
    """A grant for the configured provider and the current text, not revoked."""

    return (
        provider is not None
        and consent is not None
        and consent.provider == provider
        and consent.revoked_at is None
        and consent.consent_text_version == version
    )


def granted_consent(
    existing: NavigatorConsentDocument | None,
    *,
    owner_id: str,
    provider: str,
    now: datetime,
    version: int = CONSENT_TEXT_VERSION,
) -> NavigatorConsentDocument:
    """Grant (idempotent by state); a re-grant keeps the old one in history."""

    if existing is None:
        return NavigatorConsentDocument(
            owner_id=owner_id,
            provider=provider,
            granted_at=now,
            consent_text_version=version,
        )
    if consent_is_current(existing, provider=provider, version=version):
        return existing
    previous = {
        "granted_at": existing.granted_at.isoformat(),
        "revoked_at": (
            None if existing.revoked_at is None else existing.revoked_at.isoformat()
        ),
        "consent_text_version": existing.consent_text_version,
    }
    return existing.model_copy(
        update={
            "granted_at": now,
            "revoked_at": None,
            "consent_text_version": version,
            "history": [*existing.history, previous],
        }
    )


def revoked_consent(
    existing: NavigatorConsentDocument, *, now: datetime
) -> NavigatorConsentDocument:
    """Revoke (idempotent by state: an already revoked grant is unchanged)."""

    if existing.revoked_at is not None:
        return existing
    return existing.model_copy(update={"revoked_at": now})


# ------------------------------------------------------------- the service
_COPY = {
    "navigator_disabled": "Suggestions aren't available right now.",
    "navigator_consent_required": "Cloud suggestions need your consent first.",
    "navigator_input_too_large": "These notes are too long for suggestions.",
    "navigator_rate_limited": "Too many suggestions right now; try again later.",
    "navigator_cost_cap": "The suggestion usage limit is reached.",
    "navigator_timeout": "The suggestion took too long.",
    "navigator_provider_error": "The suggestion provider failed.",
    "navigator_malformed_output": "No usable suggestion came back.",
    "provider_mismatch": "That provider is not the configured one.",
    "consent_text_outdated": "The consent text has changed.",
}
"""Fixed copy per reason; an error message never echoes request content."""

_STATUS = {
    "navigator_disabled": 503,
    "navigator_consent_required": 400,
    "navigator_input_too_large": 400,
    "navigator_rate_limited": 429,
    "navigator_cost_cap": 429,
    "navigator_timeout": 503,
    "navigator_provider_error": 503,
    "navigator_malformed_output": 503,
    "provider_mismatch": 400,
    "consent_text_outdated": 400,
}


def navigator_error(reason: str) -> ReviewRequestError:
    """The http §7 error for ``reason`` (status, reason code, fixed copy)."""

    return ReviewRequestError(_STATUS[reason], reason, _COPY[reason])


class NavigatorRateLimited(ReviewRequestError):
    """429 ``navigator_rate_limited``; the route adds ``Retry-After``."""

    def __init__(self, retry_after_seconds: int) -> None:
        reason = "navigator_rate_limited"
        super().__init__(_STATUS[reason], reason, _COPY[reason])
        self.retry_after_seconds = retry_after_seconds


class NavigatorRateLimiter(Protocol):
    """The per-owner limiter (``app.core.rate_limit.navigator_rate_limiter``)."""

    def check(self, key: str) -> bool: ...

    def retry_after_seconds(self, key: str) -> int: ...


@dataclass(frozen=True, slots=True)
class NavigatorLimits:
    """The ``BRAIN_BUDDY_REVIEW_NAVIGATOR_*`` admission limits (research R13)."""

    max_input_tokens: int = 6_000
    max_output_tokens: int = 300
    max_cost_usd: float = 0.01
    max_daily_cost_usd: float = 0.20


@dataclass(frozen=True, slots=True)
class NavigatorStatus:
    """``GET /review/navigator``."""

    provider: str | None
    consent: NavigatorConsentDocument | None
    consent_current: bool
    consent_text_version: int
    available: bool


@dataclass(frozen=True, slots=True)
class NavigatorSuggestion:
    """``POST /review/navigator/suggestions`` → 200; never persisted."""

    request_id: str
    provider: str
    notes_truncated: bool
    proposals: tuple[str, ...] | None
    clarifying_question: str | None


@dataclass(slots=True)
class _Outcome:
    """The one content-free log line of a suggestion request (navigator §6)."""

    request_id: str
    owner_id: str
    provider: str | None
    kind: str
    outcome: str = "error"
    input_tokens: int | None = None
    output_tokens: int | None = None
    proposals: int = 0
    notes_truncated: bool = False


def build_navigator_input(request: NavigatorSuggestionRequest) -> NavigatorInput:
    """FR-019 from the strict request, with the server's ``reduce_notes`` backstop."""

    task = request.task
    project = request.project
    notes, truncated = (None, False)
    if task is not None and task.notes is not None:
        notes, truncated = reduce_notes(task.notes)
    return NavigatorInput(
        kind=request.kind,
        task_title=None if task is None else task.title,
        task_notes=notes,
        stall_reason=None if task is None else task.stall_reason,
        project_name=None if project is None else project.name,
        open_task_titles=() if project is None else tuple(project.open_task_titles),
        notes_truncated=truncated,
    )


def _round_usd(value: float) -> float:
    return max(0.0, round(value, 10))


class NavigatorService:
    """Consent, admission and suggestions of the cloud navigator (http §7).

    The provider call never runs under ``command_lock`` (one process-wide
    ``RLock``): the cost is reserved under the lock, the provider is called
    with no lock held, and the reservation is settled (or released) under the
    lock again. Nothing a person wrote is stored or logged: the only writes
    are the consent rows and the content-free ``navigator_usage`` counters.
    """

    def __init__(
        self,
        task_repo: TaskRepository,
        *,
        provider: NavigatorProvider,
        limits: NavigatorLimits,
        clock: Callable[[], datetime],
        rate_limiter: NavigatorRateLimiter,
        consent_text_version: int = CONSENT_TEXT_VERSION,
        request_ids: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self.task_repo = task_repo
        self.provider = provider
        self.limits = limits
        self.clock = clock
        self.rate_limiter = rate_limiter
        self.consent_text_version = consent_text_version
        self.request_ids = request_ids

    # ------------------------------------------------------------ consent
    def _consent(
        self, owner_id: str, provider: str | None
    ) -> NavigatorConsentDocument | None:
        consents = self.task_repo.list_navigator_consents(owner_id)
        if provider is not None:
            return next((c for c in consents if c.provider == provider), None)
        # Disabled: still show the latest stored grant, so it can be revoked.
        return max(consents, key=lambda c: c.granted_at, default=None)

    def status(self, owner_id: str) -> NavigatorStatus:
        """Never gated: a stored consent can always be seen (FR-024)."""

        provider = self.provider.category
        consent = self._consent(owner_id, provider)
        return NavigatorStatus(
            provider=provider,
            consent=consent,
            consent_current=consent_is_current(
                consent, provider=provider, version=self.consent_text_version
            ),
            consent_text_version=self.consent_text_version,
            available=provider is not None,
        )

    def grant_consent(
        self, owner_id: str, *, provider: str, consent_text_version: int
    ) -> NavigatorStatus:
        """One-time consent for the configured provider and the current text."""

        configured = self.provider.category
        if configured is None or provider != configured:
            raise navigator_error("provider_mismatch")
        if consent_text_version != self.consent_text_version:
            raise navigator_error("consent_text_outdated")
        with self.task_repo.command_lock(owner_id):
            existing = self._consent(owner_id, configured)
            updated = granted_consent(
                existing,
                owner_id=owner_id,
                provider=configured,
                now=self.clock(),
                version=self.consent_text_version,
            )
            if updated != existing:
                self.task_repo.save_navigator_consent(updated)
        logger.info(
            "navigator_consent outcome=granted owner_id=%s provider=%s "
            "consent_text_version=%d changed=%s",
            owner_id,
            configured,
            self.consent_text_version,
            updated != existing,
        )
        return self.status(owner_id)

    def revoke_consent(self, owner_id: str) -> None:
        """Revoke every stored grant; takes effect for the next request.

        Never gated, also while the feature or the provider is switched off.
        """

        revoked = 0
        with self.task_repo.command_lock(owner_id):
            now = self.clock()
            for consent in self.task_repo.list_navigator_consents(owner_id):
                updated = revoked_consent(consent, now=now)
                if updated != consent:
                    self.task_repo.save_navigator_consent(updated)
                    revoked += 1
        logger.info(
            "navigator_consent outcome=revoked owner_id=%s revoked=%d",
            owner_id,
            revoked,
        )

    # ---------------------------------------------------------- suggestions
    def suggest(
        self, owner_id: str, request: NavigatorSuggestionRequest
    ) -> NavigatorSuggestion:
        """1–3 grounded proposals or one question; one log line, codes only."""

        started = time.monotonic()
        record = _Outcome(
            request_id=self.request_ids(),
            owner_id=owner_id,
            provider=self.provider.category,
            kind=request.kind,
        )
        try:
            return self._suggest(owner_id, request, record)
        finally:
            logger.info(
                "navigator outcome=%s request_id=%s owner_id=%s provider=%s kind=%s "
                "duration_ms=%d input_tokens=%s output_tokens=%s proposals=%d "
                "notes_truncated=%s",
                record.outcome,
                record.request_id,
                record.owner_id,
                record.provider,
                record.kind,
                int((time.monotonic() - started) * 1000),
                record.input_tokens,
                record.output_tokens,
                record.proposals,
                record.notes_truncated,
            )

    def _fail(self, record: _Outcome, reason: str) -> ReviewRequestError:
        record.outcome = reason
        return navigator_error(reason)

    def _admit(
        self, owner_id: str, request: NavigatorSuggestionRequest, record: _Outcome
    ) -> tuple[str, NavigatorInput]:
        """Everything decided before any cost: provider, consent, input size."""

        provider = self.provider.category
        if provider is None:
            raise self._fail(record, "navigator_disabled")
        echoed = request.consent
        if not echoed.external_processing_allowed or echoed.provider != provider:
            raise self._fail(record, "navigator_consent_required")
        if not consent_is_current(
            self._consent(owner_id, provider),
            provider=provider,
            version=self.consent_text_version,
        ):
            raise self._fail(record, "navigator_consent_required")
        navigator_input = build_navigator_input(request)
        record.notes_truncated = navigator_input.notes_truncated
        record.input_tokens = estimate_input_tokens(navigator_input)
        if record.input_tokens > self.limits.max_input_tokens:
            raise self._fail(record, "navigator_input_too_large")
        if not self.rate_limiter.check(owner_id):
            record.outcome = "navigator_rate_limited"
            raise NavigatorRateLimited(self.rate_limiter.retry_after_seconds(owner_id))
        return provider, navigator_input

    def _suggest(
        self, owner_id: str, request: NavigatorSuggestionRequest, record: _Outcome
    ) -> NavigatorSuggestion:
        provider, navigator_input = self._admit(owner_id, request, record)
        estimate = self.provider.estimate_cost_usd(
            input_tokens=record.input_tokens or 0,
            output_tokens=self.limits.max_output_tokens,
        )
        day = self.clock().astimezone(UTC).date()
        if estimate > self.limits.max_cost_usd or not self._reserve(
            owner_id, day, estimate
        ):
            raise self._fail(record, "navigator_cost_cap")
        bug: str | None = None
        try:
            result = self.provider.suggest(navigator_input)  # (2) no lock held
        except NavigatorProviderTimeout:
            self._settle(owner_id, day, estimate, actual=0.0, shown=False)
            raise self._fail(record, "navigator_timeout") from None
        except NavigatorProviderFailure:
            self._settle(owner_id, day, estimate, actual=0.0, shown=False)
            raise self._fail(record, "navigator_provider_error") from None
        except Exception as error:
            # Not a declared port failure but a bug: release the reservation
            # and keep only the class name; the wrapper is raised below.
            self._settle(owner_id, day, estimate, actual=0.0, shown=False)
            bug = type(error).__name__
        if bug is not None:
            # Raised outside the ``except`` block, so it has no __context__ at
            # all: ``from None`` only hides one, and a framework that re-chains
            # (``raise exc from exc.__cause__ or exc.__context__``) would bring
            # input or model output echoed in the original back (FR-044).
            raise NavigatorInternalError(f"navigator provider raised {bug}")
        record.output_tokens = result.output_tokens
        output = validate_navigator_output(
            navigator_input,
            proposals=result.proposals,
            clarifying_question=result.clarifying_question,
        )
        actual = self.provider.estimate_cost_usd(
            input_tokens=(
                record.input_tokens
                if result.input_tokens is None
                else result.input_tokens
            )
            or 0,
            output_tokens=(
                self.limits.max_output_tokens
                if result.output_tokens is None
                else result.output_tokens
            ),
        )
        shown = output is not None and output.proposals is not None
        self._settle(owner_id, day, estimate, actual=actual, shown=shown)
        if output is None:
            raise self._fail(record, "navigator_malformed_output")
        record.proposals = len(output.proposals or ())
        record.outcome = "success" if shown else "question"
        return NavigatorSuggestion(
            request_id=record.request_id,
            provider=provider,
            notes_truncated=navigator_input.notes_truncated,
            proposals=output.proposals,
            clarifying_question=output.clarifying_question,
        )

    # ------------------------------------------------------ cost admission
    def _usage(self, owner_id: str, day: date) -> NavigatorUsageDocument:
        return next(
            (u for u in self.task_repo.list_navigator_usage(owner_id) if u.day == day),
            NavigatorUsageDocument(owner_id=owner_id, day=day),
        )

    def _reserve(self, owner_id: str, day: date, estimate: float) -> bool:
        """(1) Under the owner lock: admit against the daily cap and reserve."""

        with self.task_repo.command_lock(owner_id):
            usage = self._usage(owner_id, day)
            committed = usage.estimated_cost_usd + usage.reserved_cost_usd
            if committed + estimate > self.limits.max_daily_cost_usd:
                return False
            self.task_repo.save_navigator_usage(
                usage.model_copy(
                    update={
                        "calls": usage.calls + 1,
                        "reserved_cost_usd": _round_usd(
                            usage.reserved_cost_usd + estimate
                        ),
                    }
                )
            )
        return True

    def _settle(
        self,
        owner_id: str,
        day: date,
        estimate: float,
        *,
        actual: float,
        shown: bool,
    ) -> None:
        """(3) Under the lock again: replace the reservation with the actual
        cost, or release it (``actual`` 0) after a timeout or a failure."""

        with self.task_repo.command_lock(owner_id):
            usage = self._usage(owner_id, day)
            self.task_repo.save_navigator_usage(
                usage.model_copy(
                    update={
                        "reserved_cost_usd": _round_usd(
                            usage.reserved_cost_usd - estimate
                        ),
                        "estimated_cost_usd": _round_usd(
                            usage.estimated_cost_usd + actual
                        ),
                        "shown": usage.shown + (1 if shown else 0),
                    }
                )
            )


__all__ = [
    "CHARS_PER_TOKEN",
    "CONSENT_TEXT_VERSION",
    "MAX_EXEMPT_DURATION_MINUTES",
    "MAX_PROPOSALS",
    "MAX_PROPOSAL_CHARS",
    "NOTES_BUDGET_CHARS",
    "NOTES_HEAD_CHARS",
    "NOTES_SEPARATOR",
    "NOTES_TAIL_CHARS",
    "PROMPT_VERSION",
    "NavigatorInput",
    "NavigatorInternalError",
    "NavigatorKind",
    "NavigatorLimits",
    "NavigatorOutput",
    "NavigatorProvider",
    "NavigatorProviderFailure",
    "NavigatorProviderResult",
    "NavigatorProviderTimeout",
    "NavigatorRateLimited",
    "NavigatorRateLimiter",
    "NavigatorService",
    "NavigatorStatus",
    "NavigatorSuggestion",
    "build_navigator_input",
    "consent_is_current",
    "estimate_input_tokens",
    "granted_consent",
    "grounding_terms",
    "is_date_word",
    "navigator_error",
    "reduce_notes",
    "revoked_consent",
    "system_prompt",
    "user_prompt",
    "validate_navigator_output",
]
