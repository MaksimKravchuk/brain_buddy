"""Regression tests for meaningful backend decision branches."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.prompts.validation_prompt import (
    _build_downstream_chain,
    _build_upstream_chain,
    build_validation_prompt,
    summarize_validation_state,
)
from app.ai.providers.base import ProviderContext, ProviderResult
from app.ai.providers.mock import MockValidationProvider
from app.api.errors import register_exception_handlers
from app.api.middleware import CORRELATION_HEADER, CorrelationIdMiddleware
from app.core.rate_limit import InMemoryRateLimiter
from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.main import (
    _maybe_seed_admin,
    _run_voice_sweep,
    _start_voice_sweep_thread,
    create_app,
)
from app.repositories.index import IndexRepository
from app.repositories.tree import TreeRepository
from app.repositories.version import VersionRepository
from app.schemas import (
    AiFeedbackRequest,
    Position,
    TreeCreateRequest,
    TreeMetadata,
    VersionCreateRequest,
)
from app.schemas.common import TimestampMetadata, ValidationState
from app.schemas.domain import (
    NodeDocument,
    RelationDocument,
    RelationMetadata,
    TreeDocument,
)
from app.services.version_service import VersionService
from app.utils.identifiers import ensure_acyclic
from app.utils.time import ensure_utc, from_isoformat, to_isoformat

_TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


def _node(node_id: str) -> NodeDocument:
    return NodeDocument(
        id=node_id,
        label=node_id,
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=_TIMESTAMP, updated_at=_TIMESTAMP),
    )


def _relation(source_id: str, target_id: str) -> RelationDocument:
    return RelationDocument(
        id=f"rel_{source_id}_{target_id}",
        source_id=source_id,
        target_id=target_id,
        question_label="why",
        metadata=RelationMetadata(created_at=_TIMESTAMP, updated_at=_TIMESTAMP),
    )


def _tree(nodes: list[NodeDocument], relations: list[RelationDocument]) -> TreeDocument:
    return TreeDocument(
        id="branch_tree",
        title="Branch tree",
        owner_id="owner",
        created_at=_TIMESTAMP,
        updated_at=_TIMESTAMP,
        nodes=nodes,
        relations=relations,
    )


def test_feedback_cache_metadata_and_legacy_node_branches(tree_service) -> None:
    empty = tree_service.create_tree(TreeCreateRequest(name="Empty"), owner_id="owner")
    feedback = tree_service.generate_ai_feedback(
        empty.id,
        AiFeedbackRequest(consent=True, request_id="request"),
        owner_id="owner",
    )
    assert feedback.recommendations[0].startswith("Add nodes")

    first = tree_service.create_tree(TreeCreateRequest(name="Linked"), owner_id="owner")
    left = _node("left")
    right = _node("right")
    linked = TreeDocument(
        id="linked-branch-tree",
        title="Linked",
        owner_id="owner",
        created_at=first.created_at,
        updated_at=first.updated_at,
        nodes=[left, right],
        relations=[_relation(left.id, right.id)],
    )
    tree_service.tree_repo.create(linked)
    tree_service._sync_index(linked)
    response = tree_service.generate_ai_feedback(
        linked.id, AiFeedbackRequest(consent=True), owner_id="owner"
    )
    assert len(response.recommendations) == 1

    assert tree_service._cache_get("missing") is None
    tree_service._cache_store(linked)
    assert tree_service._cache_get(linked.id) == linked
    metadata = TreeMetadata.from_timestamps(
        created_at=_TIMESTAMP, updated_at=_TIMESTAMP, owner_id="owner"
    )
    assert tree_service._prepare_metadata_block(metadata)["owner_id"] == "owner"

    metadata_without_owner = TreeMetadata.from_timestamps(
        created_at=_TIMESTAMP, updated_at=_TIMESTAMP
    )
    assert "owner_id" not in tree_service._prepare_metadata_block(
        metadata_without_owner
    )

    legacy = linked.model_copy(
        update={"nodes": [left.model_copy(update={"extra": "legacy"})]}
    )
    assert tree_service.node_to_response(legacy, left.id).type == "child"
    none_extra = _tree([_node("none")], [])
    assert tree_service.node_to_response(none_extra, "none").type == "child"


def test_tree_validation_and_repository_callbacks_cover_duplicate_and_hooks(
    data_dir, tree_service
) -> None:
    repository = TreeRepository(data_dir)
    tree = _tree([_node("a"), _node("b")], [])
    repository.create(tree)
    with pytest.raises(ConflictError):
        repository.create(tree)

    loaded_ids: list[str] = []
    deleted: list[str] = []
    assert (
        repository.read(tree.id, after_load=lambda loaded: loaded_ids.append(loaded.id))
        == tree
    )
    repository.delete(tree.id, before_delete=lambda loaded: deleted.append(loaded.id))
    assert loaded_ids == [tree.id]
    assert deleted == [tree.id]

    with pytest.raises(ValidationFailure, match="already exists"):
        tree_service._validate_relation_targets(
            [_relation("a", "b"), _relation("a", "b")], {"a", "b"}
        )


def test_prompt_chain_boundaries_malformed_links_and_cycles() -> None:
    nodes = [_node(f"node_{index}") for index in range(21)]
    long_tree = _tree(
        nodes,
        [_relation(f"node_{index}", f"node_{index + 1}") for index in range(20)],
    )
    assert len(_build_downstream_chain(long_tree, nodes[0])) == 20
    assert len(_build_upstream_chain(long_tree, nodes[-1])) == 20

    malformed = _tree([_node("a")], [_relation("a", "missing")])
    assert _build_downstream_chain(malformed, malformed.nodes[0]) == []
    malformed_upstream = _tree([_node("a")], [_relation("missing", "a")])
    assert _build_upstream_chain(malformed_upstream, malformed_upstream.nodes[0]) == []
    cyclic = _tree([_node("a"), _node("b")], [_relation("a", "b"), _relation("b", "a")])
    assert len(build_validation_prompt(cyclic, "a").steps) == 2
    assert len(_build_upstream_chain(cyclic, cyclic.nodes[0])) == 2
    state = ValidationState(confidence=70, provider="mock", last_checked=_TIMESTAMP)
    assert "70% via mock" in summarize_validation_state(state)


def test_validation_provider_resolution_and_summary_edge_cases(
    validation_service,
) -> None:
    tree = _tree([_node("first"), _node("second")], [])
    assert validation_service._resolve_node(tree, "second")[1] == 1
    with pytest.raises(NotFoundError):
        validation_service._resolve_node(tree, "missing")
    with pytest.raises(ValidationFailure, match="not supported"):
        validation_service._determine_provider("unsupported")

    no_observations = ProviderResult(
        confidence=50, verdict="weak", observations=[], suggested_questions=[], raw={}
    )
    blank_observation = ProviderResult(
        confidence=50,
        verdict="weak",
        observations=[{"assessment": ""}],
        suggested_questions=[],
        raw={},
    )
    assert validation_service._summarize_result(no_observations) == "Weak"
    assert validation_service._summarize_result(blank_observation) == "Weak"


def test_version_restore_comparison_and_repository_missing_directory(
    data_dir, tree_service, version_service, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Versions"), owner_id="owner"
    )
    version = version_service.create_version(tree.id, VersionCreateRequest(label="v1"))
    version_service.restore_version(tree.id, version.id)
    restored = version_service.restore_version(tree.id, version.id)
    assert [ref.id for ref in restored.version_refs].count(version.id) == 1

    previous = _relation("a", "b")
    current = previous.model_copy(
        update={"target_id": "c", "question_label": "because", "notes": "note"}
    )
    assert VersionService._compare_relations(previous, current) == [
        "target_id",
        "question_label",
        "notes",
    ]
    repository = VersionRepository(data_dir)
    missing_dir = data_dir / "absent"
    monkeypatch.setattr(repository, "versions_dir", lambda _tree_id: missing_dir)
    assert repository.list_for_tree("tree") == []


def test_time_identifier_rate_limit_and_auth_branches(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    naive = datetime(2026, 1, 1)
    offset = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=2)
    assert ensure_utc(naive).tzinfo == UTC
    assert to_isoformat(offset).endswith("Z")
    assert from_isoformat("2026-01-01T00:00:00+00:00") == _TIMESTAMP
    with pytest.raises(ValidationFailure, match="same node"):
        ensure_acyclic([("node", "node")])

    limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=5)
    clock = iter([0.0, 6.0])
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: next(clock))
    assert limiter.check("key")
    assert limiter.check("key")
    limiter.reset("key")

    with pytest.raises(ValidationFailure, match="at most"):
        container.auth_service._validate_password_format("x" * 1000)
    container.auth_service.logout("already-missing")


def test_mock_provider_middle_confidence_and_correlation_error_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Digest:
        def hexdigest(self) -> str:
            return "0000000f" + "0" * 56

    monkeypatch.setattr(
        "app.ai.providers.mock.hashlib.sha256", lambda _payload: Digest()
    )
    result = MockValidationProvider().validate(
        "prompt",
        ProviderContext(
            tree_id="tree", node_id="node", prompt_version="v1", chain_length=2
        ),
    )
    assert result.verdict == "uncertain"
    assert len(result.suggested_questions) == 2

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    @app.get("/conflict")
    def conflict() -> None:
        raise ConflictError("Tree", "tree")

    response = TestClient(app).get("/conflict", headers={CORRELATION_HEADER: "trace"})
    assert response.headers[CORRELATION_HEADER] == "trace"


def test_build_diff_skips_relation_diff_entry_when_fields_are_unchanged(
    version_service,
) -> None:
    """An unchanged relation present on both sides of a snapshot diff must not
    produce a conflict entry — only relations whose comparable fields actually
    differ should count toward relations_modified."""

    nodes = [_node("a"), _node("b")]
    unchanged_relation = _relation("a", "b")
    prev_tree = _tree(nodes, [unchanged_relation])
    curr_tree = _tree(nodes, [unchanged_relation])

    diff, conflicts = version_service._build_diff(prev_tree, curr_tree)

    assert diff.relations_modified == 0
    assert conflicts == []


def test_restore_version_merges_missing_refs_then_skips_already_present_refs(
    tree_service, version_service
) -> None:
    """Exercises both merge branches in restore_version: appending a ref that
    is absent from the target tree (the version's own ref, and any ref
    carried on the restored snapshot), and skipping a ref that is already
    present on a subsequent restore of the same version."""

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Ref merge"), owner_id="owner"
    )
    v1 = version_service.create_version(tree.id, VersionCreateRequest(label="v1"))
    v2 = version_service.create_version(tree.id, VersionCreateRequest(label="v2"))

    # Simulate a tree whose version_refs were lost while the version
    # documents themselves still exist, so both the restored-ref and the
    # snapshot's-own-ref-list appends are exercised.
    def strip_refs(current: TreeDocument) -> TreeDocument:
        return current.model_copy(update={"version_refs": []})

    tree_service.mutate_tree(tree.id, strip_refs)

    restored = version_service.restore_version(tree.id, v2.id)
    ref_ids = [ref.id for ref in restored.version_refs]
    assert ref_ids.count(v2.id) == 1
    assert ref_ids.count(v1.id) == 1

    # Restoring the same version again: both refs are already present, so the
    # merge loop's "skip" branch (ref already accounted for) is taken instead.
    restored_again = version_service.restore_version(tree.id, v2.id)
    ref_ids_again = [ref.id for ref in restored_again.version_refs]
    assert ref_ids_again.count(v2.id) == 1
    assert ref_ids_again.count(v1.id) == 1


def test_index_missing_delete_and_configured_admin_seed(
    container, data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(NotFoundError):
        IndexRepository(data_dir).delete("missing")
    monkeypatch.setenv("BRAIN_BUDDY_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BRAIN_BUDDY_ADMIN_PASSWORD", "correct-horse-battery-staple")
    _maybe_seed_admin(container)
    assert container.user_repo.get_by_email("admin@example.com") is not None


def test_voice_sweep_iteration_runs_all_three_duties_and_survives_a_failure(
    container,
) -> None:
    """``_run_voice_sweep`` is the body of both the startup scan and the
    periodic thread; one bad pass (e.g. a transient repository error) must
    log and return rather than propagate and kill the caller/loop."""

    calls: list[str] = []
    real_recover = container.task_service.recover_due_provider_leases
    real_purge_raw = container.task_service.purge_expired_raw_audio

    def recover_due_provider_leases(**kwargs: object) -> int:
        calls.append("recover")
        return real_recover(**kwargs)

    def purge_expired_raw_audio(**kwargs: object) -> int:
        calls.append("raw_audio")
        return real_purge_raw(**kwargs)

    def purge_expired_working_artifacts(**kwargs: object) -> int:
        calls.append("working_artifacts")
        raise RuntimeError("transient repository error")

    container.task_service.recover_due_provider_leases = recover_due_provider_leases
    container.task_service.purge_expired_raw_audio = purge_expired_raw_audio
    container.task_service.purge_expired_working_artifacts = (
        purge_expired_working_artifacts
    )

    # Must not raise even though the third duty fails.
    _run_voice_sweep(container)

    assert calls == ["recover", "raw_audio", "working_artifacts"]


def test_voice_sweep_thread_is_tracked_and_stops_cleanly(container) -> None:
    """The periodic sweep runs on a thread that is referenced (not an
    untracked fire-and-forget task) and stops promptly once signalled."""

    import threading
    import time

    iterations = threading.Event()
    original_recover = container.task_service.recover_due_provider_leases

    def recover_due_provider_leases(**kwargs: object) -> int:
        iterations.set()
        return original_recover(**kwargs)

    container.task_service.recover_due_provider_leases = recover_due_provider_leases

    stop_event = threading.Event()
    from app import main as main_module

    original_interval = main_module._VOICE_SWEEP_INTERVAL_SECONDS
    main_module._VOICE_SWEEP_INTERVAL_SECONDS = 0.01
    try:
        thread = _start_voice_sweep_thread(container, stop_event)
        assert thread.is_alive()
        assert iterations.wait(timeout=2), "sweep loop never ran an iteration"
        stop_event.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        main_module._VOICE_SWEEP_INTERVAL_SECONDS = original_interval
        time.sleep(0)


def test_voice_sweep_logs_completed_recovery_and_retention_work(
    container, caplog: pytest.LogCaptureFixture
) -> None:
    """A completed sweep reports non-zero recovery and retention work without
    exposing any operation content in its observability message."""

    import logging

    caplog.set_level(logging.INFO, logger="app.main")
    container.task_service.recover_due_provider_leases = lambda: 1
    container.task_service.purge_expired_raw_audio = lambda: 2
    container.task_service.purge_expired_working_artifacts = lambda: 3

    _run_voice_sweep(container)

    assert (
        "Voice sweep: recovered 1 lease(s), purged 2 raw-audio, 3 working-artifact"
        in (caplog.text)
    )


def test_development_app_tracks_and_stops_the_periodic_voice_sweep(
    data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-test app owns its periodic sweep thread and signals then joins it
    during shutdown, rather than leaking an untracked background worker."""

    from app import main as main_module
    from app.core import get_config

    class SweepThread:
        def __init__(self) -> None:
            self.join_timeouts: list[float | None] = []

        def join(self, timeout: float | None = None) -> None:
            self.join_timeouts.append(timeout)

    sweep_thread = SweepThread()
    seen_stop_events = []

    def start_sweep(_container, stop_event):
        seen_stop_events.append(stop_event)
        return sweep_thread

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "development")
    monkeypatch.setattr(main_module, "_start_voice_sweep_thread", start_sweep)
    get_config.cache_clear()
    try:
        app = create_app()
        with TestClient(app):
            assert app.state.voice_sweep_thread is sweep_thread

        assert seen_stop_events[0].is_set()
        assert sweep_thread.join_timeouts == [5]

        # Shutdown must also remain safe if startup did not retain a thread
        # reference (for example, after a failed worker handoff).
        app_without_sweep_thread = create_app()
        app_without_sweep_thread.state.voice_sweep_thread = None
        with TestClient(app_without_sweep_thread):
            pass

        assert sweep_thread.join_timeouts == [5]
    finally:
        get_config.cache_clear()


def test_compose_e2e_can_opt_in_to_the_periodic_voice_sweep(
    data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The isolated Compose E2E service can exercise persisted provider runs.

    Unit tests remain thread-free in the ``test`` environment unless this
    explicit opt-in is set.
    """

    from app import main as main_module
    from app.core import get_config

    class SweepThread:
        def join(self, timeout: float | None = None) -> None:
            assert timeout == 5

    sweep_thread = SweepThread()
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST", "1")
    monkeypatch.setattr(
        main_module, "_start_voice_sweep_thread", lambda _container, _stop: sweep_thread
    )
    get_config.cache_clear()
    try:
        app = create_app()
        with TestClient(app):
            assert app.state.voice_sweep_thread is sweep_thread
    finally:
        get_config.cache_clear()
