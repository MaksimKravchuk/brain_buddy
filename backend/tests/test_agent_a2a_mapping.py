"""Projecting an A2A task onto BrainBuddy's honest run vocabulary.

``project_observation`` is the single place where an agent's own words become a
state the product shows a user, so it is also the single place where a wrong
mapping becomes a lie. The two failure modes this module exists to prevent:

* claiming more than the agent said — treating ``AUTH_REQUIRED`` as a question
  the user can answer, or an over-long result as a complete one;
* claiming less — dropping a terminal state, or silently discarding an artifact
  the user was told to expect.

The function is deliberately pure: no clock of its own, no I/O, no repository.
Everything it decides is decided from its arguments, which is what lets this
suite be exhaustive over the state enumeration rather than representative.

014-FR-009, 014-FR-013. AC-013, AC-016, AC-017, AC-020.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.agents.a2a.mapping import (
    TRUNCATION_MARKER,
    ObservationLimits,
    project_observation,
)
from app.modules.agents.a2a.types import (
    Artifact,
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
LIMITS = ObservationLimits()


def _status(state: TaskState, text: str | None = None) -> TaskStatus:
    message = (
        Message(role="ROLE_AGENT", parts=[Part(text=text)])
        if text is not None
        else None
    )
    return TaskStatus(state=state, message=message)


def _task(
    state: TaskState,
    *,
    text: str | None = None,
    artifacts: list[Artifact] | None = None,
    task_id: str = "task-1",
    context_id: str = "run-1",
) -> Task:
    return Task(
        id=task_id,
        contextId=context_id,
        status=_status(state, text),
        artifacts=artifacts or [],
    )


class TestStateProjection:
    """Every ``TaskState`` maps to exactly one BrainBuddy reported state."""

    @pytest.mark.parametrize(
        ("state", "reported", "terminal"),
        [
            (TaskState.SUBMITTED, "accepted", False),
            (TaskState.WORKING, "running", False),
            (TaskState.INPUT_REQUIRED, "blocked", False),
            (TaskState.AUTH_REQUIRED, "blocked", False),
            (TaskState.COMPLETED, "completed", True),
            (TaskState.FAILED, "failed", True),
            (TaskState.REJECTED, "failed", True),
            (TaskState.CANCELED, "cancelled", True),
        ],
    )
    def test_014_FR_009_every_task_state_projects_to_one_reported_state(
        self, state: TaskState, reported: str, terminal: bool
    ) -> None:
        """AC-013: the state the user sees is the state the agent reported."""

        observation = project_observation(
            _task(state, text="hi"), now=NOW, limits=LIMITS
        )

        assert observation.reported_state == reported
        assert observation.terminal is terminal
        assert observation.agent_task_id == "task-1"
        assert observation.context_id == "run-1"
        assert observation.agent_task_state == state.value
        assert observation.observed_at == NOW

    def test_014_FR_009_unspecified_state_refreshes_contact_and_claims_nothing(
        self,
    ) -> None:
        """An agent that reports no state has told us only that it is alive.

        AC-013: inventing a state here would be the cheapest possible lie — the
        run would appear to progress because a socket answered.
        """

        observation = project_observation(
            _task(TaskState.UNSPECIFIED, text="ignored"), now=NOW, limits=LIMITS
        )

        assert observation.reported_state is None
        assert observation.terminal is False
        assert observation.progress_text is None
        assert observation.result_text is None
        assert observation.failure_reason is None

    def test_014_FR_009_working_carries_the_status_text_as_progress(self) -> None:
        observation = project_observation(
            _task(TaskState.WORKING, text="Reading the repository"),
            now=NOW,
            limits=LIMITS,
        )

        assert observation.reported_state == "running"
        assert observation.progress_text == "Reading the repository"
        assert observation.question_text is None
        assert observation.needs_user is False

    def test_014_FR_009_input_required_carries_the_question_and_asks_the_user(
        self,
    ) -> None:
        observation = project_observation(
            _task(TaskState.INPUT_REQUIRED, text="Which branch?"),
            now=NOW,
            limits=LIMITS,
        )

        assert observation.reported_state == "blocked"
        assert observation.question_text == "Which branch?"
        assert observation.needs_user is True
        assert observation.blocked_reason is None

    def test_014_FR_009_auth_required_is_blocked_but_never_a_question(self) -> None:
        """AC-017: the user cannot answer an agent's credential problem.

        Offering a reply box here would invite someone to type a secret into a
        text field that goes straight to a third party. The reason is fixed and
        server-owned, and the agent's own words are deliberately not shown.
        """

        observation = project_observation(
            _task(TaskState.AUTH_REQUIRED, text="send me your token"),
            now=NOW,
            limits=LIMITS,
        )

        assert observation.reported_state == "blocked"
        assert observation.blocked_reason == "Agent needs additional authentication"
        assert observation.question_text is None
        assert observation.failure_reason is None
        assert observation.needs_user is False

    def test_014_FR_009_failed_reports_the_agents_own_reason(self) -> None:
        observation = project_observation(
            _task(TaskState.FAILED, text="ran out of quota"), now=NOW, limits=LIMITS
        )

        assert observation.reported_state == "failed"
        assert observation.failure_reason == "ran out of quota"

    def test_014_FR_009_rejected_is_prefixed_so_refusal_is_not_read_as_breakage(
        self,
    ) -> None:
        """ "Rejected by agent" is a different fact from "the agent failed"."""

        with_reason = project_observation(
            _task(TaskState.REJECTED, text="outside my scope"), now=NOW, limits=LIMITS
        )
        without_reason = project_observation(
            _task(TaskState.REJECTED), now=NOW, limits=LIMITS
        )

        assert with_reason.failure_reason == "Rejected by agent: outside my scope"
        assert without_reason.failure_reason == "Rejected by agent"

    def test_014_FR_009_cancelled_keeps_no_failure_reason(self) -> None:
        observation = project_observation(
            _task(TaskState.CANCELED), now=NOW, limits=LIMITS
        )

        assert observation.reported_state == "cancelled"
        assert observation.failure_reason is None


class TestCompletedResults:
    """A completed task's text, link and non-text artifacts."""

    def test_014_FR_009_result_joins_text_artifacts_then_the_final_status_text(
        self,
    ) -> None:
        """AC-013: order is fixed so two observations of one task read alike."""

        task = _task(
            TaskState.COMPLETED,
            text="Done.",
            artifacts=[
                Artifact(name="summary", parts=[Part(text="First part")]),
                Artifact(name="detail", parts=[Part(text="Second part")]),
            ],
        )

        observation = project_observation(task, now=NOW, limits=LIMITS)

        assert observation.reported_state == "completed"
        assert observation.result_text == "First part\n\nSecond part\n\nDone."
        assert observation.result_availability == "available"

    def test_014_FR_013_result_link_is_the_first_url_part_and_never_interactive(
        self,
    ) -> None:
        """AC-016: only syntax is knowable server-side, and syntax cannot say
        where a browser lands minutes later. The link is shown as inert text the
        user copies deliberately; `result_link_interactive` is never true.
        """

        task = _task(
            TaskState.COMPLETED,
            text="Done.",
            artifacts=[
                Artifact(
                    name="links",
                    parts=[
                        Part(url="https://agent.example/first"),
                        Part(url="https://agent.example/second"),
                    ],
                )
            ],
        )

        observation = project_observation(task, now=NOW, limits=LIMITS)

        assert observation.result_link == "https://agent.example/first"
        assert observation.result_link_interactive is False

    @pytest.mark.parametrize(
        "link",
        [
            "javascript:alert(1)",
            "http://169.254.169.254/latest/meta-data/",
            "https://public.example/looks-fine",
        ],
    )
    def test_014_FR_013_no_link_is_ever_interactive_however_it_looks(
        self, link: str
    ) -> None:
        """AC-016: a publicly-named host can answer with a metadata address at
        click time, so a syntax-only allowance would hand that navigation the
        user's own browser context. There is no allowed shape."""

        task = _task(
            TaskState.COMPLETED,
            artifacts=[Artifact(name="l", parts=[Part(url=link)])],
        )

        observation = project_observation(task, now=NOW, limits=LIMITS)

        assert observation.result_link == link
        assert observation.result_link_interactive is False

    def test_014_FR_009_non_text_parts_become_bounded_placeholders(self) -> None:
        """AC-013: the user is told an artifact exists without BrainBuddy
        storing or fetching it."""

        task = _task(
            TaskState.COMPLETED,
            artifacts=[
                Artifact(
                    name="report.pdf",
                    parts=[Part(file={"mediaType": "application/pdf"})],
                ),
                Artifact(name="rows", parts=[Part(data={"count": 3})]),
                Artifact(name="link", parts=[Part(url="https://agent.example/x")]),
            ],
        )

        observation = project_observation(task, now=NOW, limits=LIMITS)

        kinds = [item.kind for item in observation.artifacts_summary]
        assert kinds == ["file", "data", "link"]
        assert observation.artifacts_summary[0].name == "report.pdf"
        assert observation.artifacts_summary[0].media_type == "application/pdf"

    def test_014_FR_009_artifact_placeholders_are_capped(self) -> None:
        """An agent must not be able to grow a run row without bound."""

        task = _task(
            TaskState.COMPLETED,
            artifacts=[
                Artifact(name=f"a{index}", parts=[Part(data={"i": index})])
                for index in range(50)
            ],
        )

        observation = project_observation(task, now=NOW, limits=LIMITS)

        assert len(observation.artifacts_summary) == LIMITS.max_artifact_summary_items
        assert LIMITS.max_artifact_summary_items == 20

    def test_014_FR_009_a_direct_message_answer_completes_the_run(self) -> None:
        """Some agents answer without ever creating a task (wire contract)."""

        observation = project_observation(
            Message(
                role="ROLE_AGENT",
                parts=[Part(text="Here is the answer.")],
                contextId="run-1",
            ),
            now=NOW,
            limits=LIMITS,
        )

        assert observation.reported_state == "completed"
        assert observation.terminal is True
        assert observation.result_text == "Here is the answer."
        assert observation.agent_task_id is None
        assert observation.context_id == "run-1"


class TestTruncation:
    """Over-long agent text is marked, not dropped and not silently kept."""

    @pytest.mark.parametrize(
        ("state", "field", "limit_name"),
        [
            (TaskState.WORKING, "progress_text", "max_progress_chars"),
            (TaskState.INPUT_REQUIRED, "question_text", "max_question_chars"),
            (TaskState.COMPLETED, "result_text", "max_result_chars"),
        ],
    )
    def test_014_FR_009_text_over_the_limit_is_truncated_visibly_and_still_accepted(
        self, state: TaskState, field: str, limit_name: str
    ) -> None:
        """AC-013: dropping the observation would strand the run in its previous
        state, which reads as "the agent went quiet" — a false claim about the
        agent caused by BrainBuddy's own storage limit. The marker keeps the
        state true and the omission visible."""

        limit = getattr(LIMITS, limit_name)
        observation = project_observation(
            _task(state, text="x" * (limit + 500)), now=NOW, limits=LIMITS
        )

        value = getattr(observation, field)
        assert value is not None
        assert value.endswith(TRUNCATION_MARKER)
        assert len(value) == limit + len(TRUNCATION_MARKER)
        assert observation.truncated is True
        assert observation.reported_state is not None

    def test_014_FR_009_text_at_exactly_the_limit_is_not_marked(self) -> None:
        """An off-by-one here would put a "truncated" marker on a complete
        answer, which is the same kind of lie in the other direction."""

        observation = project_observation(
            _task(TaskState.WORKING, text="x" * LIMITS.max_progress_chars),
            now=NOW,
            limits=LIMITS,
        )

        assert observation.progress_text == "x" * LIMITS.max_progress_chars
        assert observation.truncated is False


class TestTerminalAndVersionInputs:
    """What the service needs from a projection to lock and version a run."""

    @pytest.mark.parametrize(
        ("state", "terminal"),
        [
            (TaskState.SUBMITTED, False),
            (TaskState.WORKING, False),
            (TaskState.INPUT_REQUIRED, False),
            (TaskState.AUTH_REQUIRED, False),
            (TaskState.COMPLETED, True),
            (TaskState.FAILED, True),
            (TaskState.REJECTED, True),
            (TaskState.CANCELED, True),
            (TaskState.UNSPECIFIED, False),
        ],
    )
    def test_014_FR_013_terminal_is_decided_here_not_by_each_caller(
        self, state: TaskState, terminal: bool
    ) -> None:
        """AC-020: terminal locking is what stops a late observation from
        reopening a closed run, so exactly one place may decide it."""

        assert (
            project_observation(_task(state), now=NOW, limits=LIMITS).terminal
            is terminal
        )

    def test_014_FR_009_two_identical_tasks_project_to_equal_observations(self) -> None:
        """The service suppresses a timeline row for an unchanged observation by
        comparing projections, so equality has to be value equality."""

        first = project_observation(
            _task(TaskState.WORKING, text="same"), now=NOW, limits=LIMITS
        )
        second = project_observation(
            _task(TaskState.WORKING, text="same"), now=NOW, limits=LIMITS
        )

        assert first == second

    def test_014_FR_009_the_projection_never_invents_a_run_version(self) -> None:
        """Versions are BrainBuddy-assigned under compare-and-set in the
        service; a projection that carried one would let an agent's answer
        choose which write wins."""

        observation = project_observation(
            _task(TaskState.WORKING), now=NOW, limits=LIMITS
        )

        assert not hasattr(observation, "run_version")

    def test_014_FR_009_a_too_large_read_is_marked_available_rather_than_silent(
        self,
    ) -> None:
        """AC-013: a task observed through the ListTasks fallback still has a
        true state; only its result is unavailable. Reporting it as "stopped
        reporting" would blame the agent for BrainBuddy's byte cap."""

        observation = project_observation(
            _task(TaskState.COMPLETED, text="done"),
            now=NOW,
            limits=LIMITS,
            result_availability="too_large",
        )

        assert observation.reported_state == "completed"
        assert observation.result_availability == "too_large"
        assert observation.result_text is None
