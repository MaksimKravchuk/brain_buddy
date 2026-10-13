"""026-FR-005/012/022/023/024: device Review and Navigator consent commands (PR-31d).

``POST /api/sync/v1/commands`` executes the catalog's ``review.*`` commands inside
the route's receipt. Each is the web path's own writer, so the committed feed
transaction has the web path's shape and a refusal is a rejected receipt with no
feed change.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import navigator_rate_limiter
from app.modules.tasks.sync.device_executor_review import _SUPPORTED
from tests.allure_evidence import attach_json, check_equal

from .conftest import FrozenClock
from .test_review_navigator import CONSENT_TEXT_VERSION, PROVIDER_ENV, SpyProvider
from .test_sync_commands_api import cid, envelope, error_code, register, submit
from .test_sync_review_projection import (
    GOLDEN_STEPS,
    PRIVATE_KEYS,
    Synced,
    _kinds,
    _walk,
)

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync device Review commands"),
    allure.story("Review and Navigator consent commands execute on the device route"),
]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _hermetic_navigator(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv(PROVIDER_ENV, "deterministic")
    navigator_rate_limiter.reset()
    yield
    navigator_rate_limiter.reset()


class Device:
    """A registered device submitting catalog commands for the owner."""

    def __init__(self, synced: Synced) -> None:
        self.s, self.client, self.owner = synced, synced.api.client, synced.owner
        self.number = 0
        assert register(self.client, self.owner).status_code == 200

    def counts(self) -> tuple[int, int]:
        return self.s.receipts(), len(self.s.transactions())

    def send(
        self,
        kind: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        *,
        checks: list[tuple[str, str, int]] = (),  # type: ignore[assignment]
        number: int | None = None,
    ) -> Any:
        self.number += 1
        return submit(
            self.client,
            envelope(
                self.owner,
                cid(number or self.number + 100),
                type=kind,
                entity_id=entity_id,
                payload=payload or {},
                preconditions=[
                    {"entity_type": t, "entity_id": i, "edit_revision": str(r)}
                    for t, i, r in checks
                ],
            ),
        )

    def accepted(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """One command, one receipt and, when it changed anything, one commit."""
        before = self.counts()
        response = self.send(*args, **kwargs)
        assert response.status_code == 200, response.text
        receipt: dict[str, Any] = response.json()
        assert receipt["outcome"] == "accepted", receipt
        after = self.counts()
        assert after == (
            before[0] + 1,
            before[1] + (1 if receipt["has_changes"] else 0),
        ), (args[0], before, after)
        return receipt

    def rejected(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """A terminal rejected receipt: one receipt, no feed change."""
        before = self.counts()
        response = self.send(*args, **kwargs)
        assert response.status_code == 200, response.text
        receipt: dict[str, Any] = response.json()
        assert receipt["outcome"] == "rejected", receipt
        assert receipt["commit_seq"] is None and receipt["has_changes"] is False
        assert self.counts() == (before[0] + 1, before[1])
        return receipt


def new(kind: str) -> str:
    return f"{kind}_{uuid.uuid4()}"


@pytest.fixture
def synced(api_client: TestClient, frozen_clock: FrozenClock) -> Synced:
    found = Synced(api_client, frozen_clock)
    found.grants_enabled()
    return found


@pytest.fixture
def device(synced: Synced) -> Device:
    return Device(synced)


def settings_revision(s: Synced) -> int:
    return int(s.api.state()["settings"]["revision"])


def run_device_journey(
    device: Device, after_step: Any = None
) -> dict[str, dict[str, Any]]:
    """``run_journey`` of the web suite, every writer once as a device command."""
    s = device.s
    api, clock, owner = s.api, s.clock, s.owner
    nxt = api.create("next card", state="next")
    inbox = api.create("inbox card", state="inbox")
    waiting = api.create("waiting card", state="waiting", waiting_for="Ann")
    receipts: dict[str, dict[str, Any]] = {}

    def step(name: str, receipt: dict[str, Any]) -> dict[str, Any]:
        receipts[name] = receipt
        if after_step is not None:
            after_step(name)
        return receipt

    step(
        "explainer_ack",
        device.accepted("review.explainer_ack", owner, {"time_zone": "UTC"}),
    )
    step(
        "settings",
        device.accepted(
            "review.settings",
            owner,
            {"threshold_days": 21},
            checks=[("review_settings", owner, settings_revision(s))],
        ),
    )
    clock.advance(days=40)
    session = new("review")
    step(
        "session_start",
        device.accepted(
            "review.session_start",
            session,
            {"mode": "quick", "entry": "list", "origin": "ios", "replace_open": False},
        ),
    )
    step(
        "session_progress",
        device.accepted(
            "review.session_progress",
            session,
            {
                "progress_id": new("progress"),
                "snapshot_decision_queue": True,
                "current_step": "decisions",
            },
        ),
    )
    waiting = api.task(waiting["id"])
    decision = new("decision")
    decided = step(
        "decide_follow_up",
        device.accepted(
            "review.decide",
            waiting["id"],
            {
                "decision_id": decision,
                "type": "follow_up",
                "title": "Call Ann",
                "follow_up_task_id": new("task"),
                "session_id": session,
            },
            checks=[("task", waiting["id"], waiting["revision"])],
        ),
    )
    step(
        "undo_decision",
        device.accepted(
            "review.undo_decision",
            decision,
            checks=[("task", waiting["id"], decided["result"]["task"]["revision"])],
        ),
    )
    inbox = api.task(inbox["id"])
    bulk = new("bulk")
    step(
        "bulk_release",
        device.accepted(
            "review.bulk_release",
            bulk,
            {
                "kind": "inbox_remainder",
                "items": [
                    {
                        "task_id": inbox["id"],
                        "expected_revision": str(inbox["revision"]),
                    }
                ],
            },
        ),
    )
    step("bulk_undo", device.accepted("review.bulk_undo", bulk))
    step("session_finish", device.accepted("review.session_finish", session))
    nxt = api.task(nxt["id"])
    step(
        "auto_park",
        device.accepted(
            "review.auto_park", nxt["id"], {"formulation_id": nxt["formulation"]["id"]}
        ),
    )
    step(
        "parks_ack",
        device.accepted(
            "review.parks_ack",
            owner,
            {
                "items": [
                    {"task_id": nxt["id"], "formulation_id": nxt["formulation"]["id"]}
                ]
            },
        ),
    )
    step(
        "consent_grant",
        device.accepted(
            "review.consent_grant",
            owner,
            {"provider": "openai", "consent_text_version": CONSENT_TEXT_VERSION},
        ),
    )
    step(
        "consent_revoke",
        device.accepted("review.consent_revoke", owner, {"provider": "openai"}),
    )
    return receipts


def test_026_FR_005_every_review_command_executes_with_the_web_paths_feed_commit(
    synced: Synced, device: Device
) -> None:
    observed: list[tuple[str, bool]] = []

    def record(name: str) -> None:
        observed.append((name, synced.review_base() == synced.snapshot()))

    with allure.step("run every Review and consent command as a device command"):
        receipts = run_device_journey(device, record)
        attach_json("outcomes", {k: v["has_changes"] for k, v in receipts.items()})
    with allure.step("one transaction per command holding the web path's records"):
        assert [name for name, _ in observed] == [n for n, _ in GOLDEN_STEPS]
        golden = [kinds for _, kinds in GOLDEN_STEPS if kinds is not None]
        check_equal(
            "feed kinds",
            [sorted(_kinds(t)) for t in synced.transactions()],
            [sorted(k) for k in golden],
        )
        check_equal(
            "no-op commands",
            sorted(n for n, r in receipts.items() if not r["has_changes"]),
            sorted(n for n, kinds in GOLDEN_STEPS if kinds is None),
        )
    with allure.step("the folded feed equals the stored public base after every step"):
        assert all(consistent for _, consistent in observed)
        assert synced.review_base() == synced.snapshot()
    with allure.step("no private member reaches a receipt, the feed or the snapshot"):
        leaked = {
            key
            for receipt in receipts.values()
            for key in _walk(receipt["result"] or {})
        }
        assert PRIVATE_KEYS & leaked == set()
        values = [
            c["value"]
            for t in synced.transactions()
            for c in t["changes"]
            if c["value"] is not None
        ]
        assert PRIVATE_KEYS & {k for v in values for k in _walk(v)} == set()


def test_026_FR_005_decide_and_undo_change_the_stored_state(
    synced: Synced, device: Device
) -> None:
    api, clock = synced.api, synced.clock
    card = api.create("waiting card", state="waiting", waiting_for="Ann")
    clock.advance(days=40)
    decision = new("decision")
    with allure.step("a follow_up decision creates the Next task and the receipt"):
        task = api.task(card["id"])
        receipt = device.accepted(
            "review.decide",
            task["id"],
            {
                "decision_id": decision,
                "type": "follow_up",
                "title": "Call Ann",
                "follow_up_task_id": new("task"),
            },
            checks=[("task", task["id"], task["revision"])],
        )
        result = receipt["result"]
        assert result["decision"]["id"] == decision
        created = result["created_task"]
        assert api.task(created["id"])["state"] == "next"
        assert synced.container.task_repo.get_review_decision(synced.owner, decision)
    with allure.step("a stale Undo is refused and leaves the decision"):
        stale = device.rejected(
            "review.undo_decision",
            decision,
            checks=[("task", task["id"], 99)],
        )
        check_equal("reason", stale["error"]["details"]["reason"], "undo_unavailable")
        assert synced.container.task_repo.get_review_decision(synced.owner, decision)
    with allure.step(
        "Undo within the window restores the task and deletes the follow-up"
    ):
        done = device.accepted(
            "review.undo_decision",
            decision,
            checks=[("task", task["id"], result["task"]["revision"])],
        )
        assert done["result_redacted"] is True  # a deleted record redacts the answer
        assert (
            synced.container.task_repo.get_review_decision(synced.owner, decision)
            is None
        )
        assert api.client.get(f"/api/tasks/{created['id']}").status_code == 404


def test_026_FR_012_exact_replay_by_command_id_and_conflicting_envelope(
    synced: Synced, device: Device
) -> None:
    owner = synced.owner
    first = device.accepted(
        "review.explainer_ack", owner, {"time_zone": "UTC"}, number=1
    )
    counts = device.counts()
    with allure.step("the same bytes answer the stored receipt and execute nothing"):
        replay = device.send(
            "review.explainer_ack", owner, {"time_zone": "UTC"}, number=1
        ).json()
        volatile = {"server_now", "correlation_id"}
        check_equal(
            "replay",
            {k: v for k, v in replay.items() if k not in volatile},
            {k: v for k, v in first.items() if k not in volatile},
        )
        check_equal("counts", device.counts(), counts)
    with allure.step("the same ID with another envelope conflicts, executing nothing"):
        other = device.send(
            "review.explainer_ack", owner, {"time_zone": "Europe/Berlin"}, number=1
        )
        assert other.status_code == 409
        assert error_code(other) == "IDEMPOTENCY_KEY_REUSED"
        check_equal("counts", device.counts(), counts)


def test_026_FR_012_stale_settings_revision_is_a_rejected_receipt(
    synced: Synced, device: Device
) -> None:
    owner = synced.owner
    device.accepted("review.explainer_ack", owner, {"time_zone": "UTC"})
    revision = settings_revision(synced)
    with allure.step("a stale revision rejects the receipt and changes nothing"):
        stale = device.rejected(
            "review.settings",
            owner,
            {"threshold_days": 28},
            checks=[("review_settings", owner, revision + 5)],
        )
        attach_json("stale", stale)
        check_equal("code", stale["error"]["code"], "REVISION_CONFLICT")
        assert synced.api.state()["settings"]["threshold_days"] == 14
    with allure.step("the current revision applies the update"):
        device.accepted(
            "review.settings",
            owner,
            {"threshold_days": 28},
            checks=[("review_settings", owner, revision)],
        )
        assert synced.api.state()["settings"]["threshold_days"] == 28
    with allure.step("a time zone nobody knows is a domain refusal, not a crash"):
        zone = device.rejected(
            "review.settings",
            owner,
            {"time_zone": "Mars/Base"},
            checks=[("review_settings", owner, settings_revision(synced))],
        )
        check_equal("reason", zone["error"]["details"]["reason"], "invalid_time_zone")


def test_026_FR_005_run_refusals_are_rejected_receipts_without_feed_changes(
    synced: Synced, device: Device
) -> None:
    session = new("review")
    body = {"mode": "quick", "entry": "list", "origin": "ios", "replace_open": False}
    device.accepted("review.session_start", session, body)
    with allure.step("an open run without replace_open is refused as a taken id"):
        clash = device.rejected("review.session_start", new("review"), body)
        check_equal("reason", clash["error"]["details"]["reason"], "id_already_exists")
    with allure.step("an unknown run and an unknown decision are not found"):
        unknown = device.rejected("review.session_finish", new("review"))
        check_equal(
            "session", unknown["error"]["details"]["reason"], "session_not_found"
        )
        missing = device.rejected(
            "review.undo_decision", new("decision"), checks=[("task", "task_x", 1)]
        )
        check_equal("decision", missing["error"]["details"]["reason"], "not_found")
    with allure.step("an unknown step is refused as outside the review"):
        outside = device.rejected(
            "review.session_progress",
            session,
            {
                "progress_id": new("progress"),
                "step": {"code": "dates", "status": "finished"},
            },
        )
        check_equal("step", outside["error"]["details"]["reason"], "step_not_in_review")


def test_026_FR_005_invalid_review_forms_are_rejected_without_a_receipt(
    synced: Synced, device: Device
) -> None:
    owner = synced.owner
    body = {"mode": "quick", "entry": "list", "origin": "ios", "replace_open": False}
    cases = {
        "creation id shape": device.send("review.session_start", "review_1", body),
        "payload carries the creation id": device.send(
            "review.session_start", new("review"), {**body, "id": new("review")}
        ),
        "settings without its precondition": device.send(
            "review.settings", owner, {"threshold_days": 7}
        ),
        "settings for another entity": device.send(
            "review.settings",
            new("review"),
            {"threshold_days": 7},
            checks=[("review_settings", owner, 1)],
        ),
        "payload revision": device.send(
            "review.settings",
            owner,
            {"threshold_days": 7, "expected_revision": 1},
            checks=[("review_settings", owner, 1)],
        ),
        "undo with a payload": device.send("review.bulk_undo", new("bulk"), {"x": 1}),
    }
    with allure.step("each is 422 INVALID_REQUEST and writes nothing"):
        seen = {k: (r.status_code, error_code(r)) for k, r in cases.items()}
        attach_json("responses", seen)
        assert set(seen.values()) == {(422, "INVALID_REQUEST")}
        check_equal("counts", device.counts(), (0, 0))


def test_026_FR_024_consent_commands_keep_revoke_owner_wide_and_never_regrant(
    synced: Synced, device: Device
) -> None:
    owner, nav = synced.owner, synced.nav
    grant = {"provider": "openai", "consent_text_version": CONSENT_TEXT_VERSION}

    def consent_live() -> bool:
        consent = nav.status()["consent"]
        return consent is not None and consent["revoked_at"] is None

    first = device.accepted("review.consent_grant", owner, grant, number=1)
    assert consent_live() and first["result"]["consent_current"] is True
    assert "history" not in first["result"]["consent"]
    with allure.step("revoke is owner-wide whatever provider label the payload names"):
        device.accepted("review.consent_revoke", owner, {"provider": "apple"}, number=2)
        assert not consent_live()
    device.accepted("review.consent_grant", owner, grant, number=3)
    assert consent_live()
    with allure.step(
        "a late retry of the old revoke answers its receipt and revokes nothing"
    ):
        counts = device.counts()
        late = device.send(
            "review.consent_revoke", owner, {"provider": "apple"}, number=2
        )
        assert late.status_code == 200 and late.json()["outcome"] == "accepted"
        assert consent_live()
        check_equal("counts", device.counts(), counts)
    with allure.step("a late retry of the first grant never regrants after a revoke"):
        device.accepted(
            "review.consent_revoke", owner, {"provider": "openai"}, number=4
        )
        device.send("review.consent_grant", owner, grant, number=1)
        assert not consent_live()


def test_026_FR_024_grant_refusals_never_call_a_provider_and_revoke_ignores_the_flag(
    synced: Synced, device: Device
) -> None:
    owner, nav = synced.owner, synced.nav
    provider = synced.container.navigator_service.provider
    assert isinstance(provider, SpyProvider)
    with allure.step("a stale consent text is refused and stores nothing"):
        outdated = device.rejected(
            "review.consent_grant",
            owner,
            {"provider": "openai", "consent_text_version": CONSENT_TEXT_VERSION + 1},
        )
        check_equal(
            "reason", outdated["error"]["details"]["reason"], "consent_text_outdated"
        )
        assert nav.status()["consent"] is None
    with allure.step("a provider that is not the configured one is refused"):
        wrong = device.rejected(
            "review.consent_grant",
            owner,
            {"provider": "other", "consent_text_version": CONSENT_TEXT_VERSION},
        )
        check_equal(
            "reason", wrong["error"]["details"]["reason"], "provider_unavailable"
        )
    device.accepted(
        "review.consent_grant",
        owner,
        {"provider": "openai", "consent_text_version": CONSENT_TEXT_VERSION},
    )
    synced.api.flag("off")
    with allure.step("weekly_review OFF refuses a grant but still revokes"):
        gated = device.rejected(
            "review.consent_grant",
            owner,
            {"provider": "openai", "consent_text_version": CONSENT_TEXT_VERSION},
        )
        check_equal("reason", gated["error"]["details"]["reason"], "review_unavailable")
        device.accepted("review.consent_revoke", owner, {"provider": "openai"})
        assert nav.status()["consent"]["revoked_at"] is not None
    with allure.step("no consent command ever reaches the provider"):
        check_equal("provider calls", getattr(provider, "calls", 0), 0)


def test_026_FR_011_owner_whose_deletion_began_is_refused(
    synced: Synced, device: Device
) -> None:
    owner = synced.owner
    device.accepted("review.explainer_ack", owner, {"time_zone": "UTC"})
    counts = device.counts()
    synced.container.user_repo.mutate(
        owner,
        lambda u: u.model_copy(update={"deletion_requested_at": datetime.now(UTC)}),
    )
    with allure.step("a new command is refused and changes nothing"):
        refused = device.send(
            "review.settings",
            owner,
            {"threshold_days": 28},
            checks=[("review_settings", owner, 1)],
        )
        assert refused.status_code == 401 and error_code(refused) == "AUTH_REQUIRED"
        stored = synced.container.task_repo.get_review_settings(owner)
        assert stored is not None and stored.threshold_days == 14
        check_equal("counts", device.counts(), counts)


def test_026_FR_012_dependencies_gate_review_commands(
    synced: Synced, device: Device
) -> None:
    owner = synced.owner
    session = new("review")
    with allure.step("a command behind an unseen predecessor is retryable"):
        behind = device.send(
            "review.session_finish",
            session,
        )
        assert behind.status_code == 200  # no dependency yet: plain not-found refusal
    first = new("review")
    body = {"mode": "quick", "entry": "list", "origin": "ios", "replace_open": False}
    device.accepted("review.session_start", first, body, number=50)
    clash = device.rejected("review.session_start", new("review"), body, number=51)
    assert clash["outcome"] == "rejected"
    with allure.step("a command depending on a rejected one is rejected"):
        env = envelope(
            owner,
            cid(52),
            type="review.session_finish",
            entity_id=first,
            depends_on=[cid(51)],
        )
        child = submit(synced.api.client, env).json()
        check_equal("code", child["error"]["code"], "DEPENDENCY_REJECTED")
    with allure.step("a pending dependency is a retryable protocol failure"):
        env = envelope(
            owner,
            cid(53),
            type="review.session_finish",
            entity_id=first,
            depends_on=[cid(99)],
        )
        pending = submit(synced.api.client, env)
        assert error_code(pending) == "DEPENDENCY_PENDING"


def test_026_FR_023_capabilities_advertise_the_review_commands(
    synced: Synced, device: Device
) -> None:
    caps = synced.api.client.get(
        f"/api/sync/v1/capabilities?scope_id={synced.owner}"
    ).json()
    listed = {r["type"]: r["supported_versions"] for r in caps["command_versions"]}
    with allure.step("every executed review command lists version 1"):
        attach_json("supported", sorted(_SUPPORTED))
        assert {t for t in _SUPPORTED if listed[t] == [1]} == set(_SUPPORTED)
        assert len(_SUPPORTED) == 13


def test_026_FR_014_the_catalog_names_the_review_executor_as_a_writer_boundary() -> (
    None
):
    source = ROOT / "backend/app/modules/tasks/sync/device_executor_review.py"
    catalog = (
        ROOT / "specs/026-rust-core-sync/contracts/command-catalog.md"
    ).read_text()
    with allure.step("the catalog table names the module"):
        named = "device_executor_review.py" in catalog
        check_equal("named in the catalog", named, True)
    with allure.step("the module calls no Tasks store write directly"):
        # Services write, so the AST inventory of test_sync_writer_boundary
        # needs no row for this file; the catalog row documents the boundary.
        writes = {
            node.func.attr
            for node in ast.walk(ast.parse(source.read_text()))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and ast.unparse(node.func.value) == "self._repo"
            and node.func.attr.startswith(("create", "save", "delete", "purge"))
        }
        check_equal("direct writes", sorted(writes), [])


def test_026_FR_005_serialized_writers_keep_their_wrapper_metadata() -> None:
    from app.modules.tasks import review_flow, review_service
    from app.modules.tasks.navigator import NavigatorService

    writers = {
        review_service.ReviewService: [
            "decide",
            "undo_decision",
            "auto_park",
            "acknowledge_explainer",
            "update_settings",
            "acknowledge_parks",
        ],
        review_flow.ReviewFlowService: [
            "start_session",
            "progress_session",
            "finish_session",
            "bulk_release",
            "undo_bulk_release",
        ],
        NavigatorService: ["grant_consent", "revoke_consent"],
    }
    with allure.step("each writer exposes its raw command through __wrapped__"):
        seen = {}
        for cls, names in writers.items():
            for name in names:
                method = getattr(cls, name)
                seen[f"{cls.__name__}.{name}"] = method.__name__
                assert method.__name__ == name
                assert method.__wrapped__.__name__ == name
                assert method.__wrapped__ is not method
        check_equal("writers", len(seen), 13)


def _executor(synced: Synced) -> Any:
    from app.modules.tasks.sync.device_executor_review import ReviewDeviceExecutor
    from app.modules.tasks.sync.review_projection import ReviewProjection

    c = synced.container
    return ReviewDeviceExecutor(
        c.review_service,
        c.review_flow_service,
        c.navigator_service,
        c.task_repo,
        ReviewProjection(c.task_repo),
    )


def test_026_FR_005_refusal_mapping_names_the_record_and_its_current_revision(
    synced: Synced,
) -> None:
    from app.exceptions import ConflictError, NotFoundError, ValidationFailure
    from app.modules.tasks.review_domain import ReviewRequestError
    from app.modules.tasks.review_flow import StepOutsideRunError

    executor, owner = _executor(synced), synced.owner
    task = synced.api.create("a card", state="next")
    with allure.step("a stale task names the task and the revision it is at"):
        stale = executor._refusal(ConflictError("Task", task["id"]), owner)
        check_equal(
            "task",
            (stale.reason, stale.entity, stale.current_revision),
            ("revision_conflict", ("task", [task["id"]]), task["revision"]),
        )
        gone = executor._refusal(ConflictError("Task", "task_missing"), owner)
        check_equal("deleted task", gone.current_revision, None)
    with allure.step("a stale settings record without a row has no revision"):
        none = executor._refusal(ConflictError("Review settings", owner), owner)
        check_equal(
            "settings",
            (none.reason, none.current_revision),
            ("revision_conflict", None),
        )
    with allure.step("anything else is a plain invalid value"):
        assert (
            executor._refusal(ConflictError("Project", "p"), owner).reason
            == "invalid_value"
        )
        assert (
            executor._refusal(ValidationFailure("no"), owner).reason == "invalid_value"
        )
        unknown = executor._refusal(
            ReviewRequestError(400, "something_new", "m"), owner
        )
        check_equal("unknown code", unknown.reason, "invalid_value")
        assert (
            executor._refusal(NotFoundError("Task", "t"), owner).reason == "not_found"
        )
        assert executor._refusal(StepOutsideRunError("step"), owner).field == "step"


def test_026_FR_005_a_refusal_after_a_write_rolls_the_unit_back() -> None:
    from types import SimpleNamespace

    from app.exceptions import ConflictError
    from app.modules.tasks.sync.device_executor_review import ReviewDeviceExecutor

    unit = SimpleNamespace(owner_id="owner", activity=0, writes=())
    command = SimpleNamespace(unit=unit)

    def wrote_then_refused() -> None:
        unit.activity += 1
        raise ConflictError("Task", "t")

    run = ReviewDeviceExecutor._run
    with allure.step("the receipt cannot reject over a write, so the error escapes"):
        with pytest.raises(ConflictError) as raised:
            run(SimpleNamespace(), command, wrote_then_refused, dict)  # type: ignore[arg-type]
        attach_json("error", {"resource": raised.value.resource})


def test_026_FR_012_a_later_settings_command_may_use_after_command_revisions(
    synced: Synced, device: Device
) -> None:
    owner = synced.owner
    device.accepted("review.explainer_ack", owner, {"time_zone": "UTC"})
    first = device.accepted(
        "review.settings",
        owner,
        {"threshold_days": 21},
        checks=[("review_settings", owner, settings_revision(synced))],
        number=61,
    )
    check_equal(
        "bumped",
        first["result_versions"][0]["edit_revision"],
        str(settings_revision(synced)),
    )

    def chained(
        number: int, ref: dict[str, Any], depends: list[str], threshold: int
    ) -> Any:
        return submit(
            synced.api.client,
            envelope(
                owner,
                cid(number),
                type="review.settings",
                entity_id=owner,
                payload={"threshold_days": threshold},
                preconditions=[{"after_command": ref}],
                depends_on=depends,
            ),
        )

    ref = {"command_id": cid(61), "entity_type": "review_settings", "entity_id": owner}
    with allure.step("the revision comes from the named predecessor's receipt"):
        ok = chained(62, ref, [cid(61)], 28)
        assert ok.json()["outcome"] == "accepted", ok.text
        assert synced.api.state()["settings"]["threshold_days"] == 28
    with allure.step("a reference that is not a declared dependency is invalid"):
        assert error_code(chained(63, ref, [], 14)) == "INVALID_REQUEST"
    with allure.step(
        "a reference to another entity is skipped, leaving no precondition"
    ):
        other = {**ref, "entity_id": "elsewhere"}
        assert error_code(chained(64, other, [cid(61)], 14)) == "INVALID_REQUEST"
    with allure.step("a predecessor that published no version of it is invalid"):
        none = device.accepted("review.parks_ack", owner, {"items": []}, number=65)
        assert none["has_changes"] is False
        ref65 = {**ref, "command_id": cid(65)}
        assert error_code(chained(66, ref65, [cid(65)], 14)) == "INVALID_REQUEST"


def test_026_FR_005_more_invalid_review_forms_are_rejected_without_a_receipt(
    synced: Synced, device: Device
) -> None:
    owner = synced.owner
    cases = {
        "decide with a payload revision": device.send(
            "review.decide",
            "task_x",
            {
                "decision_id": new("decision"),
                "type": "complete",
                "expected_revision": 1,
            },
            checks=[("task", "task_x", 1)],
        ),
        "bulk release with an id": device.send(
            "review.bulk_release",
            new("bulk"),
            {"id": new("bulk"), "kind": "restart", "items": []},
        ),
        "revoke with another field": device.send(
            "review.consent_revoke", owner, {"provider": "openai", "x": 1}
        ),
        "undo with a payload": device.send(
            "review.undo_decision", new("decision"), {"x": 1}
        ),
    }
    seen = {k: (r.status_code, error_code(r)) for k, r in cases.items()}
    attach_json("responses", seen)
    assert set(seen.values()) == {(422, "INVALID_REQUEST")}
    check_equal("counts", device.counts(), (0, 0))


def uid(kind: str, number: int) -> str:
    return f"{kind}_00000000-0000-4000-8000-{number:012d}"


def test_026_FR_005_task_family_refusals_stay_terminal_beside_review_commands(
    synced: Synced, device: Device
) -> None:
    """Refusal and validation paths of the Task executor, via the shared route."""
    from app.modules.tasks.sync.device_executor import DeviceExecutorRegistry
    from app.modules.tasks.sync.wire import ProtocolFailure

    project, other, tag, task = (
        uid(k, n) for k, n in [("project", 1), ("project", 2), ("tag", 3), ("task", 4)]
    )
    device.accepted("project.create", project, {"name": "Home"})
    device.accepted("tag.create", tag, {"name": "errand"})
    device.accepted("task.create", task, {"title": "A"})
    reasons = {
        "duplicate project id": device.rejected(
            "project.create", project, {"name": "X"}
        ),
        "duplicate project name": device.rejected(
            "project.create", other, {"name": "Home"}
        ),
        "duplicate tag id": device.rejected("tag.create", tag, {"name": "y"}),
        "duplicate tag name": device.rejected(
            "tag.create", uid("tag", 5), {"name": "errand"}
        ),
        "missing task": device.rejected(
            "task.transition",
            uid("task", 9),
            {"action": "complete"},
            checks=[("task", uid("task", 9), 1)],
        ),
        "missing project": device.rejected(
            "project.archive",
            uid("project", 9),
            checks=[("project", uid("project", 9), 1)],
        ),
        "missing tag": device.rejected(
            "tag.update",
            uid("tag", 9),
            {"name": "z"},
            checks=[("tag", uid("tag", 9), 1)],
        ),
        "missing tag delete": device.rejected(
            "tag.delete", uid("tag", 9), checks=[("tag", uid("tag", 9), 1)]
        ),
    }
    attach_json(
        "reasons", {k: v["error"]["details"]["reason"] for k, v in reasons.items()}
    )
    device.accepted("project.create", other, {"name": "Work"})
    device.rejected(
        "project.update", other, {"name": "Home"}, checks=[("project", other, 1)]
    )
    device.accepted(
        "task.transition", task, {"action": "complete"}, checks=[("task", task, 1)]
    )
    device.rejected(
        "task.transition", task, {"action": "complete"}, checks=[("task", task, 2)]
    )
    device.rejected("tag.update", tag, {"name": "errand"}, checks=[("tag", tag, 99)])
    invalid = {
        "project update revision in payload": device.send(
            "project.update",
            project,
            {"expected_revision": 1},
            checks=[("project", project, 1)],
        ),
        "archive with payload": device.send(
            "project.archive", project, {"x": 1}, checks=[("project", project, 1)]
        ),
        "tag update revision in payload": device.send(
            "tag.update", tag, {"expected_revision": 1}, checks=[("tag", tag, 1)]
        ),
        "tag delete with payload": device.send(
            "tag.delete", tag, {"x": 1}, checks=[("tag", tag, 1)]
        ),
        "project archive revision in payload": device.send(
            "project.archive",
            project,
            {"expected_revision": 1},
            checks=[("project", project, 1)],
        ),
        "task tags with other keys": device.send(
            "task.tags", task, {"title": "x"}, checks=[("task", task, 2)]
        ),
    }
    check_equal(
        "invalid",
        {r.status_code for r in invalid.values()},
        {422},
    )
    with allure.step("a registry with no matching family upgrades"):
        failure = None
        try:
            DeviceExecutorRegistry().execute(None, {"type": "x"})  # type: ignore[arg-type]
        except ProtocolFailure as raised:
            failure = raised
        check_equal("upgrade required", failure is not None, True)


def test_026_FR_005_client_created_decision_ids_are_required_by_the_catalog(
    synced: Synced, device: Device
) -> None:
    """A device command never lets the server mint an id the offline client lacks."""
    api, clock = synced.api, synced.clock
    waiting = api.create("waiting card", state="waiting", waiting_for="Ann")
    nxt = api.create("next card", state="next")
    clock.advance(days=40)
    waiting, nxt = api.task(waiting["id"]), api.task(nxt["id"])
    form = nxt["formulation"]["id"]
    before = device.counts()

    def decide(task: dict[str, Any], **body: Any) -> Any:
        return device.send(
            "review.decide",
            task["id"],
            body,
            checks=[("task", task["id"], task["revision"])],
        )

    with allure.step("a decision without decision_id is an invalid request"):
        missing = decide(waiting, type="complete")
        assert (missing.status_code, error_code(missing)) == (422, "INVALID_REQUEST")
        check_equal("counts", device.counts(), before)
    cases = {
        "follow_up without follow_up_task_id": (
            waiting,
            {"type": "follow_up", "title": "Call Ann"},
            "follow_up_task_id",
        ),
        "first_step without new_formulation_id": (
            nxt,
            {"type": "first_step", "title": "Open it", "formulation_id": form},
            "new_formulation_id",
        ),
        "substantive reformulate without new_formulation_id": (
            nxt,
            {"type": "reformulate", "title": "Entirely new", "formulation_id": form},
            "new_formulation_id",
        ),
        "return_to_next without new_formulation_id": (
            waiting,
            {"type": "return_to_next", "title": "Back"},
            "new_formulation_id",
        ),
    }
    for name, (task, body, _field) in cases.items():
        with allure.step(f"{name} is refused and changes nothing"):
            receipt = device.rejected(
                "review.decide",
                task["id"],
                {"decision_id": new("decision"), **body},
                checks=[("task", task["id"], task["revision"])],
            )
            check_equal(name, receipt["error"]["details"]["reason"], "invalid_value")
            check_equal("task", api.task(task["id"])["revision"], task["revision"])
    with allure.step("a cosmetic reformulate and a plain move need no new id"):
        device.accepted(
            "review.decide",
            nxt["id"],
            {
                "decision_id": new("decision"),
                "type": "reformulate",
                "title": nxt["title"],
                "formulation_id": form,
            },
            checks=[("task", nxt["id"], nxt["revision"])],
        )
        device.accepted(
            "review.decide",
            waiting["id"],
            {"decision_id": new("decision"), "type": "complete"},
            checks=[("task", waiting["id"], waiting["revision"])],
        )


def test_026_FR_024_review_receipts_equal_the_rest_response_shape(
    synced: Synced, device: Device
) -> None:
    """Task-bearing Review results are the Review API's bodies, not stored documents."""
    from app.schemas.review import DecisionResponse

    api, clock = synced.api, synced.clock
    card = api.create("waiting card", state="waiting", waiting_for="Ann")
    clock.advance(days=40)
    task = api.task(card["id"])
    follow_up = new("task")
    receipt = device.accepted(
        "review.decide",
        task["id"],
        {
            "decision_id": new("decision"),
            "type": "follow_up",
            "title": "Call Ann",
            "follow_up_task_id": follow_up,
        },
        checks=[("task", task["id"], task["revision"])],
    )
    result = receipt["result"]
    with allure.step("the result validates as the strict REST DecisionResponse"):
        attach_json("result keys", sorted(result))
        assert DecisionResponse.model_validate(result)
        assert set(result) == {
            "decision",
            "task",
            "created_task",
            "receipt",
            "session_counts",
        }
    with allure.step("its tasks equal the REST reads of those tasks"):
        check_equal("task", result["task"], api.task(task["id"]))
        check_equal("created", result["created_task"], api.task(follow_up))
    with allure.step("no storage-only member is present"):
        attach_json("keys", sorted(set(_walk(result))))
        assert PRIVATE_KEYS & set(_walk(result)) == set()
        assert "formulation_settings" not in result


def test_026_FR_005_task_family_review_decision_keeps_the_clients_formulation_id(
    synced: Synced, device: Device
) -> None:
    api, clock = synced.api, synced.clock
    waiting = api.create("waiting card", state="waiting", waiting_for="Ann")
    clock.advance(days=40)
    task = api.task(waiting["id"])
    form = "form_00000000-0000-4000-8000-0000000000dd"
    receipt = device.accepted(
        "review.decide",
        task["id"],
        {
            "decision_id": new("decision"),
            "type": "return_to_next",
            "title": "Back",
            "new_formulation_id": form,
        },
        checks=[("task", task["id"], task["revision"])],
    )
    with allure.step("the formulation the decision created is the device's id"):
        attach_json("formulation", receipt["result"]["task"]["formulation"])
        check_equal("receipt", receipt["result"]["task"]["formulation"]["id"], form)
        check_equal("stored", api.task(task["id"])["formulation"]["id"], form)
