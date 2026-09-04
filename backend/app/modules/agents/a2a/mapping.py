"""Project one A2A answer onto BrainBuddy's run vocabulary. Pure, no I/O.

This is the only place an agent's own words become a state a user reads, so it
is the only place a mapping error becomes a false claim about someone else's
system. Everything it decides comes from its arguments — no clock, no
repository, no network — which is what makes the state enumeration exhaustively
testable rather than merely sampled.

Three rules the module keeps, in the order they matter:

1. **Never claim more than the agent said.** An unknown state, an absent status
   message and an over-cap response all degrade to "we heard from it", not to
   progress. ``AUTH_REQUIRED`` is blocked but is never a question, because a
   reply box there invites a user to type a secret to a third party.
2. **Never claim less.** Over-long text is truncated with a visible marker and
   the observation is still accepted; dropping it would strand the run in its
   previous state, which the surfaces would render as the agent going quiet —
   BrainBuddy's byte cap reported as the agent's silence.
3. **Decide terminality here.** Exactly one place may say a run is closed, or a
   late observation could reopen one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.modules.agents.a2a.types import (
    TERMINAL_TASK_STATES,
    Message,
    Part,
    Task,
    TaskState,
)
from app.modules.agents.domain import (
    MAX_PROGRESS_CHARS,
    MAX_QUESTION_CHARS,
    MAX_RESULT_CHARS,
    AgentReportedState,
)

TRUNCATION_MARKER = " … [truncated]"
"""Appended to any text the limits cut. Visible on purpose."""

AUTH_REQUIRED_REASON = "Agent needs additional authentication"
"""Server-owned. The agent's own words are deliberately not shown here."""

REJECTED_PREFIX = "Rejected by agent"

MAX_ARTIFACT_SUMMARY_ITEMS = 20
MAX_ARTIFACT_NAME_CHARS = 200
MAX_ARTIFACT_MEDIA_TYPE_CHARS = 128

ResultAvailability = Literal["available", "too_large"]
ArtifactKind = Literal["text", "file", "data", "link"]
# Keyed by the wire part kind; the value is the summary kind it maps to. A
# lookup (rather than a membership test plus a cast) narrows the type the
# same way under every mypy version the project accepts.
_SUMMARISED_PART_KINDS: dict[str, ArtifactKind] = {
    "file": "file",
    "data": "data",
    "link": "link",
}


@dataclass(frozen=True)
class ObservationLimits:
    """Bounds on how much agent text one observation may write."""

    max_progress_chars: int = MAX_PROGRESS_CHARS
    max_question_chars: int = MAX_QUESTION_CHARS
    max_result_chars: int = MAX_RESULT_CHARS
    max_artifact_summary_items: int = MAX_ARTIFACT_SUMMARY_ITEMS


@dataclass(frozen=True)
class ArtifactSummary:
    """A placeholder for a non-text artifact BrainBuddy never fetches."""

    name: str | None
    media_type: str | None
    kind: ArtifactKind


@dataclass(frozen=True)
class Observation:
    """What one authenticated read of an agent task established.

    Carries no ``run_version``: versions are BrainBuddy-assigned under
    compare-and-set in the service, and a projection that carried one would let
    an agent's answer choose which of two concurrent writes wins.
    """

    observed_at: datetime
    agent_task_state: str
    reported_state: AgentReportedState | None = None
    terminal: bool = False
    agent_task_id: str | None = None
    context_id: str | None = None
    progress_text: str | None = None
    question_text: str | None = None
    result_text: str | None = None
    result_link: str | None = None
    result_link_interactive: bool = False
    failure_reason: str | None = None
    blocked_reason: str | None = None
    needs_user: bool = False
    artifacts_summary: tuple[ArtifactSummary, ...] = field(default_factory=tuple)
    result_availability: ResultAvailability | None = None
    truncated: bool = False


#: State -> (reported state, whether the user is being asked for something).
#: ``UNSPECIFIED`` is absent on purpose: it maps to no reported state at all.
_REPORTED_STATE: dict[TaskState, AgentReportedState] = {
    TaskState.SUBMITTED: "accepted",
    TaskState.WORKING: "running",
    TaskState.INPUT_REQUIRED: "blocked",
    TaskState.AUTH_REQUIRED: "blocked",
    TaskState.COMPLETED: "completed",
    TaskState.FAILED: "failed",
    TaskState.REJECTED: "failed",
    TaskState.CANCELED: "cancelled",
}


class _Truncator:
    """Applies a bound and remembers whether it ever had to cut.

    The flag is what lets the caller mark the observation truncated without
    each call site re-deriving it — and re-deriving it in five places is how
    one of them ends up disagreeing.
    """

    def __init__(self) -> None:
        self.truncated = False

    def __call__(self, value: str | None, limit: int) -> str | None:
        if not value:
            return None
        if len(value) <= limit:
            return value
        self.truncated = True
        return value[:limit] + TRUNCATION_MARKER


def _artifact_summaries(task: Task, *, limit: int) -> tuple[ArtifactSummary, ...]:
    """Placeholders for the non-text parts, bounded.

    Text parts are excluded because they are already carried in the result;
    listing them twice would inflate the row and tell the user nothing. The cap
    exists because the artifact list is agent-controlled and a run row must not
    be able to grow without bound.
    """

    summaries: list[ArtifactSummary] = []
    for artifact in task.artifacts:
        for part in artifact.parts:
            # "text" is already in the result; "unknown" means the agent sent a
            # shape the spec does not name, and a placeholder that cannot say
            # what it stands for tells the user nothing.
            summarised_kind = _SUMMARISED_PART_KINDS.get(part.kind)
            if summarised_kind is None:
                continue
            raw_name = artifact.name or part.name
            raw_media_type = part.effective_media_type
            summaries.append(
                ArtifactSummary(
                    name=raw_name[:MAX_ARTIFACT_NAME_CHARS] if raw_name else None,
                    media_type=(
                        raw_media_type[:MAX_ARTIFACT_MEDIA_TYPE_CHARS]
                        if raw_media_type
                        else None
                    ),
                    kind=summarised_kind,
                )
            )
            if len(summaries) >= limit:
                return tuple(summaries)
    return tuple(summaries)


def _all_parts(task: Task) -> list[Part]:
    """Artifact parts first, then the status message's — result order."""

    parts = [part for artifact in task.artifacts for part in artifact.parts]
    if task.status.message is not None:
        parts.extend(task.status.message.parts)
    return parts


def _completed_result_text(task: Task) -> str | None:
    """Text artifacts joined by a blank line, then the final status text.

    The order is fixed so two observations of one task read alike; a set-based
    or dict-ordered join would make an unchanged task look changed and append a
    spurious timeline row on every pass.
    """

    blocks = [
        part.text for artifact in task.artifacts for part in artifact.parts if part.text
    ]
    status_text = task.status.text
    if status_text:
        blocks.append(status_text)
    return "\n\n".join(blocks) or None


def _first_link(task: Task) -> str | None:
    for part in _all_parts(task):
        if part.url:
            return part.url
    return None


def _project_message(
    message: Message,
    *,
    now: datetime,
    limits: ObservationLimits,
    result_availability: ResultAvailability | None,
) -> Observation:
    """A direct ``Message`` answer: the agent finished without a task."""

    truncate = _Truncator()
    result_text = (
        None
        if result_availability == "too_large"
        else truncate(message.text or None, limits.max_result_chars)
    )
    return Observation(
        observed_at=now,
        agent_task_state=TaskState.COMPLETED.value,
        reported_state="completed",
        terminal=True,
        agent_task_id=None,
        context_id=message.context_id,
        result_text=result_text,
        result_availability=result_availability or "available",
        truncated=truncate.truncated,
    )


def project_observation(
    task_or_message: Task | Message,
    *,
    now: datetime,
    limits: ObservationLimits,
    result_availability: ResultAvailability | None = None,
) -> Observation:
    """Project one A2A answer onto a BrainBuddy observation.

    ``result_availability='too_large'`` is passed by the client when a task
    record exceeded the read cap and the state had to be recovered through the
    ``ListTasks`` fallback. The state is still true; only the result is
    missing, and saying so is the difference between an honest marker and
    blaming the agent for BrainBuddy's byte budget.
    """

    if isinstance(task_or_message, Message):
        return _project_message(
            task_or_message,
            now=now,
            limits=limits,
            result_availability=result_availability,
        )

    task = task_or_message
    state = task.status.state
    status_text = task.status.text or None
    truncate = _Truncator()

    reported = _REPORTED_STATE.get(state)
    observation = Observation(
        observed_at=now,
        agent_task_state=state.value,
        reported_state=reported,
        terminal=state in TERMINAL_TASK_STATES,
        agent_task_id=task.id,
        context_id=task.context_id,
    )

    if reported is None:
        # UNSPECIFIED: contact refreshed, nothing claimed. Deliberately returns
        # before any text is read, so an agent cannot smuggle a progress line
        # into a run it has said nothing about.
        return observation

    progress = question = result = link = failure = blocked = None
    needs_user = False
    artifacts: tuple[ArtifactSummary, ...] = ()
    availability: ResultAvailability | None = None

    if state is TaskState.WORKING:
        progress = truncate(status_text, limits.max_progress_chars)
    elif state is TaskState.INPUT_REQUIRED:
        question = truncate(status_text, limits.max_question_chars)
        needs_user = True
    elif state is TaskState.AUTH_REQUIRED:
        # No question, no failure reason, and none of the agent's own words: a
        # credential problem at the agent is not something the user can answer
        # here, and rendering the agent's prose beside a reply box is how a
        # secret ends up typed into a field that forwards it.
        blocked = AUTH_REQUIRED_REASON
    elif state is TaskState.COMPLETED:
        availability = result_availability or "available"
        if availability != "too_large":
            result = truncate(_completed_result_text(task), limits.max_result_chars)
        link = _first_link(task)
        artifacts = _artifact_summaries(task, limit=limits.max_artifact_summary_items)
    elif state is TaskState.FAILED:
        failure = truncate(status_text, limits.max_result_chars)
    elif state is TaskState.REJECTED:
        # A refusal is a different fact from a breakage, and the surfaces show
        # this string verbatim, so the distinction is made here rather than
        # left to each client to infer.
        detail = truncate(status_text, limits.max_result_chars)
        failure = f"{REJECTED_PREFIX}: {detail}" if detail else REJECTED_PREFIX

    return Observation(
        observed_at=observation.observed_at,
        agent_task_state=observation.agent_task_state,
        reported_state=reported,
        terminal=observation.terminal,
        agent_task_id=observation.agent_task_id,
        context_id=observation.context_id,
        progress_text=progress,
        question_text=question,
        result_text=result,
        result_link=link,
        # Never true. Only syntax is knowable server-side, and syntax cannot
        # answer where the browser lands when the user clicks minutes later.
        result_link_interactive=False,
        failure_reason=failure,
        blocked_reason=blocked,
        needs_user=needs_user,
        artifacts_summary=artifacts,
        result_availability=availability,
        truncated=truncate.truncated,
    )


__all__ = [
    "AUTH_REQUIRED_REASON",
    "MAX_ARTIFACT_SUMMARY_ITEMS",
    "REJECTED_PREFIX",
    "TRUNCATION_MARKER",
    "ArtifactSummary",
    "Observation",
    "ObservationLimits",
    "project_observation",
]
