"""SQLite runtime feature-flag store: round-trip, atomicity, migration, degradation.

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it.

ADR-0019 (2026-08-15) replaced the original JSON-overlay-plus-environment
design with SQLite as the sole source of truth for three managed flags. The
tests below target that contract directly; there is no more "absence is
healthy" branch, no `clear()`, and no forward-compatibility preservation to
test (DD-2, DD-3, DD-8, DD-15 all retire those concerns).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from app.core.config import FeatureFlagState, ManagedFlagMigrationSeed
from app.exceptions import RepositoryError
from app.repositories.feature_flag import (
    MANAGED_FLAGS,
    MIGRATION_COMPLETE_MARKER_PARTS,
    DegradedRuntimeFlagsError,
    FeatureFlagOverrideRepository,
    FlagMode,
    FlagOverride,
    ManagedFlagMigrationError,
)

REPOSITORY_LOGGER = "app.repositories.feature_flag"

#: Planted in mutation inputs so a privacy assertion fails loudly if member
#: content ever reaches the store (010-SC-007).
EMAIL_SENTINEL = "zzsentinel@example.com"


def _repo(tmp_path: Path) -> FeatureFlagOverrideRepository:
    return FeatureFlagOverrideRepository(tmp_path / "data")


def _sqlite_db_path(tmp_path: Path) -> Path:
    """Where plan.md's Storage section says the database lives (Storage row)."""

    return tmp_path / "data" / "feature_flags.sqlite3"


def _set_mode(
    repo: FeatureFlagOverrideRepository,
    flag: str,
    mode: FlagMode,
    *,
    selected_users: tuple[str, ...] = (),
) -> None:
    def _apply(current: dict[str, FlagOverride]) -> dict[str, FlagOverride]:
        existing = current.get(flag)
        updated = dict(current)
        updated[flag] = FlagOverride(
            mode=mode,
            selected_users=(
                (selected_users if selected_users else existing.selected_users)
                if existing is not None
                else selected_users
            ),
        )
        return updated

    repo.mutate(_apply)


def _add_user(repo: FeatureFlagOverrideRepository, flag: str, account_id: str) -> None:
    def _apply(current: dict[str, FlagOverride]) -> dict[str, FlagOverride]:
        entry = current.get(flag, FlagOverride(mode=FlagMode.SELECTED_USERS))
        updated = dict(current)
        updated[flag] = FlagOverride(
            mode=entry.mode,
            selected_users=tuple(sorted({*entry.selected_users, account_id})),
        )
        return updated

    repo.mutate(_apply)


# ---------------------------------------------------------------------------
# A1 — round trip, storage location, and the post-migration invariant (DD-2)
# ---------------------------------------------------------------------------


def test_010_FR_001_rows_round_trip_modes_and_cohorts(tmp_path: Path) -> None:
    """A written row round-trips its mode and cohort."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    _add_user(repo, "voice_brain_dump", "user_beta")
    _set_mode(repo, "mobile_task_classification", FlagMode.ON)

    overlay = FeatureFlagOverrideRepository(tmp_path / "data").read()

    assert overlay.degraded is False
    assert overlay.flags["voice_brain_dump"].mode is FlagMode.SELECTED_USERS
    assert overlay.flags["voice_brain_dump"].selected_users == (
        "user_alpha",
        "user_beta",
    )
    assert overlay.flags["mobile_task_classification"].mode is FlagMode.ON
    assert overlay.flags["external_agent_relay"].mode is FlagMode.OFF


def test_010_FR_001_database_lands_at_feature_flags_sqlite3(tmp_path: Path) -> None:
    """The database lands at `{data_dir}/feature_flags.sqlite3` (plan.md Storage)."""

    repo = _repo(tmp_path)
    expected = tmp_path / "data" / "feature_flags.sqlite3"
    assert repo.db_path == expected
    assert expected.is_file()


def test_010_FR_004_a_fresh_data_directory_reads_healthy_with_all_three_rows(
    tmp_path: Path,
) -> None:
    """A never-yet-touched data directory migrates on first construction and
    reads healthy with all three managed flags present (DD-2: there is no
    more "absence is healthy" branch)."""

    overlay = _repo(tmp_path).read()

    assert overlay.degraded is False
    assert set(overlay.flags) == set(MANAGED_FLAGS)
    for flag in MANAGED_FLAGS:
        assert overlay.flags[flag].mode is FlagMode.OFF
        assert overlay.flags[flag].selected_users == ()


# ---------------------------------------------------------------------------
# A2 — atomicity and idempotence
# ---------------------------------------------------------------------------


def test_010_SC_005_a_failed_commit_during_mutate_leaves_the_previous_row_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash during a mutation's commit leaves the prior committed row."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.ON)

    class _ExplodingCommitConnection:
        """Wraps a real connection; every `commit()` fails, everything else
        delegates untouched — `sqlite3.Connection` itself cannot be patched,
        it is an immutable C type."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._real = sqlite3.Connection(*args, **kwargs)

        def commit(self) -> None:
            raise sqlite3.OperationalError("disk gave up mid-write")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

    monkeypatch.setattr(sqlite3, "connect", _ExplodingCommitConnection)
    try:
        with pytest.raises(Exception):  # noqa: B017 - implementation-defined type
            _set_mode(repo, "voice_brain_dump", FlagMode.OFF)
    finally:
        monkeypatch.undo()

    assert repo.read().flags["voice_brain_dump"].mode is FlagMode.ON


def test_010_SC_005_repeating_a_mutation_is_a_no_op_that_still_succeeds(
    tmp_path: Path,
) -> None:
    """Repeating any targeted mutation changes nothing and still succeeds."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    once = repo.read().flags["voice_brain_dump"]

    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")

    assert repo.read().flags["voice_brain_dump"] == once


def test_010_SC_005_concurrent_reads_never_observe_degraded_during_mutation(
    tmp_path: Path,
) -> None:
    """A concurrent reader never observes a torn/degraded state mid-write."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    observed: list[bool] = []
    stop = threading.Event()

    def _reader() -> None:
        while not stop.is_set():
            observed.append(repo.read().degraded)

    watcher = threading.Thread(target=_reader)
    watcher.start()
    try:
        for index in range(30):
            _add_user(repo, "voice_brain_dump", f"user_{index:03d}")
    finally:
        stop.set()
        watcher.join()

    assert observed
    assert not any(observed)


# ---------------------------------------------------------------------------
# A3 — concurrency
# ---------------------------------------------------------------------------


def test_010_SC_005_concurrent_mutations_to_different_flags_all_survive(
    tmp_path: Path,
) -> None:
    """Threads mutating different flags all land in the store."""

    repo = _repo(tmp_path)
    barrier = threading.Barrier(len(MANAGED_FLAGS))

    def _worker(flag: str) -> None:
        barrier.wait()
        _set_mode(repo, flag, FlagMode.ON)

    threads = [threading.Thread(target=_worker, args=(flag,)) for flag in MANAGED_FLAGS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    overlay = repo.read()
    for flag in MANAGED_FLAGS:
        assert overlay.flags[flag].mode is FlagMode.ON


def test_010_SC_005_concurrent_adds_to_one_flag_all_survive(tmp_path: Path) -> None:
    """Threads adding different accounts to one flag's cohort all survive."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    account_ids = [f"user_{index:02d}" for index in range(12)]
    barrier = threading.Barrier(len(account_ids))

    def _worker(account_id: str) -> None:
        barrier.wait()
        _add_user(repo, "voice_brain_dump", account_id)

    threads = [threading.Thread(target=_worker, args=(a,)) for a in account_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stored = repo.read().flags["voice_brain_dump"].selected_users
    assert sorted(stored) == sorted(account_ids)


# ---------------------------------------------------------------------------
# A4 — degraded-transition warning (FR-004)
# ---------------------------------------------------------------------------


def test_010_SC_008_degraded_transition_warns_exactly_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The healthy-to-degraded transition emits exactly one coarse WARNING."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    assert repo.read().degraded is False

    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        conn.execute(
            "UPDATE feature_flags SET mode = ? WHERE flag = ?",
            ("sideways", "voice_brain_dump"),
        )
        conn.commit()

    with caplog.at_level(logging.WARNING, logger=REPOSITORY_LOGGER):
        repo.read()
        repo.read()
        repo.read()

    warnings = [
        record
        for record in caplog.records
        if record.name == REPOSITORY_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "correlation=" in message
    assert "reason=" in message
    for forbidden in ("user_alpha", EMAIL_SENTINEL, "@", "display"):
        assert forbidden not in message


def test_010_SC_008_first_read_after_startup_degraded_still_warns_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A process whose very first read is degraded still warns exactly once."""

    repo = _repo(tmp_path)
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        conn.execute("DELETE FROM feature_flags WHERE flag = ?", ("voice_brain_dump",))
        conn.commit()

    with caplog.at_level(logging.WARNING, logger=REPOSITORY_LOGGER):
        repo.read()
        repo.read()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_010_SC_008_warning_repeats_only_after_a_healthy_read_resets_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The WARNING repeats only after one healthy read resets the transition."""

    repo = _repo(tmp_path)
    db_path = _sqlite_db_path(tmp_path)
    with caplog.at_level(logging.WARNING, logger=REPOSITORY_LOGGER):
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "DELETE FROM feature_flags WHERE flag = ?", ("voice_brain_dump",)
            )
            conn.commit()
        repo.read()

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO feature_flags (flag, mode, selected_users) "
                "VALUES (?, 'off', '[]')",
                ("voice_brain_dump",),
            )
            conn.commit()
        repo.read()

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "DELETE FROM feature_flags WHERE flag = ?",
                ("mobile_task_classification",),
            )
            conn.commit()
        repo.read()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


# ---------------------------------------------------------------------------
# A5 — purge scrub (DD-9, DD-13)
# ---------------------------------------------------------------------------


def test_010_FR_007_scrub_user_reaches_every_managed_flags_cohort(
    tmp_path: Path,
) -> None:
    """`scrub_user` removes the ID from every one of the three managed flags."""

    repo = _repo(tmp_path)
    for flag in MANAGED_FLAGS:
        _set_mode(repo, flag, FlagMode.SELECTED_USERS)
        _add_user(repo, flag, "user_alpha")
        _add_user(repo, flag, "user_beta")

    scrubbed = repo.scrub_user("user_alpha")

    assert scrubbed == len(MANAGED_FLAGS)
    overlay = repo.read()
    for flag in MANAGED_FLAGS:
        assert overlay.flags[flag].selected_users == ("user_beta",)


def test_010_FR_007_scrub_user_is_idempotent_and_leaves_other_ids_untouched(
    tmp_path: Path,
) -> None:
    """Scrubbing twice, or an ID never present, succeeds and changes nothing."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    _add_user(repo, "voice_brain_dump", "user_beta")

    assert repo.scrub_user("user_alpha") == 1
    assert repo.scrub_user("user_alpha") == 0
    assert repo.scrub_user("user_never_here") == 0
    assert repo.read().flags["voice_brain_dump"].selected_users == ("user_beta",)


def test_010_FR_007_scrub_user_raises_against_a_degraded_store(tmp_path: Path) -> None:
    """A degraded store makes `scrub_user` raise rather than silently skip."""

    repo = _repo(tmp_path)
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        conn.execute(
            "UPDATE feature_flags SET mode = ? WHERE flag = ?",
            ("sideways", "voice_brain_dump"),
        )
        conn.commit()

    with pytest.raises(DegradedRuntimeFlagsError):
        repo.scrub_user("user_alpha")


def test_010_FR_007_scrub_user_with_no_matching_id_is_a_no_op(tmp_path: Path) -> None:
    """A healthy store with no matching ID anywhere scrubs nothing."""

    repo = _repo(tmp_path)

    assert repo.scrub_user("user_alpha") == 0


# ---------------------------------------------------------------------------
# A6 — store-shape privacy
# ---------------------------------------------------------------------------


def test_010_SC_007_stored_rows_admit_only_flag_names_modes_and_account_ids(
    tmp_path: Path,
) -> None:
    """The on-disk row set admits only flag names, modes and account-ID arrays."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")

    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        rows = conn.execute(
            "SELECT flag, mode, selected_users FROM feature_flags"
        ).fetchall()

    assert {row[0] for row in rows} == set(MANAGED_FLAGS)
    for _flag, mode, selected_users_json in rows:
        assert mode in {"off", "on", "selected_users"}
        cohort = json.loads(selected_users_json)
        assert all(isinstance(item, str) for item in cohort)


def test_010_FR_001_mutation_signature_cannot_carry_member_content(
    tmp_path: Path,
) -> None:
    """The pure mutation function's own type admits no email or display name."""

    repo = _repo(tmp_path)
    # `FlagOverride` is the only value the mutation function may return, and it
    # has exactly two fields: a mode from a closed vocabulary and account IDs.
    assert set(FlagOverride.__dataclass_fields__) == {"mode", "selected_users"}
    assert set(FlagMode) == {FlagMode.OFF, FlagMode.ON, FlagMode.SELECTED_USERS}

    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")

    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        raw = "".join(str(row) for row in conn.execute("SELECT * FROM feature_flags"))
    assert EMAIL_SENTINEL not in raw


# ---------------------------------------------------------------------------
# ADR-0019 correction (2026-08-15): SQLite is the sole runtime store; the
# JSON-overlay-plus-environment design above is superseded. These tests target
# the migration contract directly (DD-15, DD-2).
#
# Constructor contract asserted here follows plan.md's Changed Surfaces table
# and "Migration is one-time, transactional, and isolated inside the
# repository" paragraph: `FeatureFlagOverrideRepository(root, *,
# legacy_states=None, legacy_internal_users=None, resolve_account_id=None)`,
# with the legacy JSON path still implicit under `root` (unchanged from the
# pre-correction repository's own `{root}/feature-flags/runtime.json`).
# ---------------------------------------------------------------------------


def _sqlite_repo(
    tmp_path: Path,
    *,
    legacy_states: dict[str, FeatureFlagState] | None = None,
    legacy_internal_users: frozenset[str] = frozenset(),
    resolve_account_id: Any = None,
) -> FeatureFlagOverrideRepository:
    """Construct the SQLite-backed repository per plan.md's migration contract."""

    return FeatureFlagOverrideRepository(
        tmp_path / "data",
        legacy_states=legacy_states or {},
        legacy_internal_users=legacy_internal_users,
        resolve_account_id=resolve_account_id or (lambda email: None),
    )


def _write_legacy_json(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "data" / "feature-flags" / "runtime.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Migration preference rule, per flag (010-FR-001, DD-15)
# ---------------------------------------------------------------------------


def test_010_FR_001_migration_prefers_a_well_formed_legacy_json_entry_over_env(
    tmp_path: Path,
) -> None:
    """The legacy JSON overlay's entry wins for a flag it ever covered (DD-15)."""

    _write_legacy_json(
        tmp_path, {"voice_brain_dump": {"mode": "on", "selected_users": []}}
    )

    repo = _sqlite_repo(
        tmp_path,
        legacy_states={"voice_brain_dump": FeatureFlagState.OFF},
    )

    assert repo.read().flags["voice_brain_dump"].mode is FlagMode.ON


def test_010_FR_001_migration_seeds_from_env_when_no_legacy_entry_exists(
    tmp_path: Path,
) -> None:
    """With no legacy JSON entry for a flag, the environment baseline supplies it."""

    repo = _sqlite_repo(
        tmp_path,
        legacy_states={"mobile_task_classification": FeatureFlagState.ON},
    )

    assert repo.read().flags["mobile_task_classification"].mode is FlagMode.ON


def test_010_FR_001_migration_resolves_internal_stage_and_skips_unresolved_emails(
    tmp_path: Path,
) -> None:
    """`internal` resolves to `selected_users`; an unresolved email is skipped,
    never substituted, so migration can only narrow the old cohort (DD-15)."""

    resolved = {"resolvable@example.com": "acct_resolvable"}

    repo = _sqlite_repo(
        tmp_path,
        legacy_states={"mobile_task_classification": FeatureFlagState.INTERNAL},
        legacy_internal_users=frozenset(
            {"resolvable@example.com", "ghost@example.com"}
        ),
        resolve_account_id=lambda email: resolved.get(email),
    )

    entry = repo.read().flags["mobile_task_classification"]
    assert entry.mode is FlagMode.SELECTED_USERS
    assert entry.selected_users == ("acct_resolvable",)


def test_010_FR_001_external_agent_relay_always_seeds_from_env_never_legacy_json(
    tmp_path: Path,
) -> None:
    """`external_agent_relay` always comes from the environment baseline: the
    pre-correction overlay never wrote it, so a key present in a legacy
    document under that name must not be read by migration (DD-15)."""

    _write_legacy_json(
        tmp_path, {"external_agent_relay": {"mode": "on", "selected_users": []}}
    )

    repo = _sqlite_repo(
        tmp_path,
        legacy_states={"external_agent_relay": FeatureFlagState.OFF},
    )

    assert repo.read().flags["external_agent_relay"].mode is FlagMode.OFF


def test_010_FR_001_a_malformed_legacy_entry_falls_back_to_the_env_baseline(
    tmp_path: Path,
) -> None:
    """A present-but-malformed legacy entry does not win: DD-15 requires it to
    be well-formed, not merely present, before it beats the env baseline."""

    _write_legacy_json(tmp_path, {"voice_brain_dump": {"mode": "not-a-real-mode"}})

    repo = _sqlite_repo(
        tmp_path,
        legacy_states={"voice_brain_dump": FeatureFlagState.ON},
    )

    assert repo.read().flags["voice_brain_dump"].mode is FlagMode.ON


# ---------------------------------------------------------------------------
# Atomic three-row-plus-ledger seed, transactionality, restart-idempotence
# (010-FR-001, 004, DD-15)
# ---------------------------------------------------------------------------


def test_010_DD_15_migration_seeds_exactly_the_three_managed_flags_plus_a_ledger_row(
    tmp_path: Path,
) -> None:
    """A fresh data directory ends up with one SQLite row per managed flag —
    now three, including `external_agent_relay` — plus a migration-ledger
    marker, all inside one `feature_flags.sqlite3` database on the volume."""

    assert set(MANAGED_FLAGS) == {
        "voice_brain_dump",
        "mobile_task_classification",
        "external_agent_relay",
    }

    _sqlite_repo(tmp_path)

    db_path = _sqlite_db_path(tmp_path)
    assert db_path.is_file()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT flag FROM feature_flags").fetchall()
        assert {row[0] for row in rows} == set(MANAGED_FLAGS)
        ledger_count = conn.execute("SELECT COUNT(*) FROM migration_ledger").fetchone()[
            0
        ]
        assert ledger_count == 1


def test_010_FR_004_a_second_construction_is_a_no_op_even_when_legacy_inputs_change(
    tmp_path: Path,
) -> None:
    """Migration is restart-idempotent: a second construction over an
    already-migrated data directory does not re-run, even when the legacy
    JSON/environment inputs are edited afterward (DD-15)."""

    _sqlite_repo(tmp_path, legacy_states={"voice_brain_dump": FeatureFlagState.OFF})
    assert (
        FeatureFlagOverrideRepository(tmp_path / "data")
        .read()
        .flags["voice_brain_dump"]
        .mode
        is FlagMode.OFF
    )

    _write_legacy_json(
        tmp_path, {"voice_brain_dump": {"mode": "on", "selected_users": []}}
    )
    repo_after_edit = _sqlite_repo(
        tmp_path, legacy_states={"voice_brain_dump": FeatureFlagState.ON}
    )

    assert repo_after_edit.read().flags["voice_brain_dump"].mode is FlagMode.OFF
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM migration_ledger").fetchone()[0] == 1


def test_010_FR_001_a_pre_commit_migration_failure_leaves_no_rows_no_marker_and_json_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure before the migration transaction commits leaves neither a
    ledger row nor partial flag rows, and never mutates the legacy JSON file;
    a retried construction then migrates cleanly exactly once (DD-15, SC-003)."""

    legacy_path = _write_legacy_json(
        tmp_path, {"voice_brain_dump": {"mode": "on", "selected_users": []}}
    )
    before = legacy_path.read_bytes()

    class _ExplodingCommitConnection:
        """Wraps a real connection; every `commit()` fails, everything else
        delegates untouched — `sqlite3.Connection` itself cannot be patched,
        it is an immutable C type (`TypeError: cannot set 'commit' attribute
        of immutable type 'sqlite3.Connection'`)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._real = sqlite3.Connection(*args, **kwargs)

        def commit(self) -> None:
            raise sqlite3.OperationalError("disk gave up mid-migration")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

    monkeypatch.setattr(sqlite3, "connect", _ExplodingCommitConnection)
    try:
        # The constructor itself no longer propagates a storage failure — an
        # unusable store degrades the repository rather than killing startup
        # (010-FR-004) — but the transaction is still all-or-nothing, which is
        # what this test exists to prove.
        degraded = _sqlite_repo(
            tmp_path, legacy_states={"voice_brain_dump": FeatureFlagState.OFF}
        )
        assert degraded.read().degraded is True
    finally:
        monkeypatch.undo()

    assert legacy_path.read_bytes() == before
    assert not (tmp_path / "data" / Path(*MIGRATION_COMPLETE_MARKER_PARTS)).exists()
    db_path = _sqlite_db_path(tmp_path)
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "feature_flags" in tables:
                assert (
                    conn.execute("SELECT COUNT(*) FROM feature_flags").fetchone()[0]
                    == 0
                )
            if "migration_ledger" in tables:
                assert (
                    conn.execute("SELECT COUNT(*) FROM migration_ledger").fetchone()[0]
                    == 0
                )

    retried = _sqlite_repo(
        tmp_path, legacy_states={"voice_brain_dump": FeatureFlagState.OFF}
    )
    assert retried.read().flags["voice_brain_dump"].mode is FlagMode.ON
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM migration_ledger").fetchone()[0] == 1


def test_010_DD_15_concurrent_first_start_construction_does_not_duplicate_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two constructors racing over one empty DB / one legacy JSON seed — each
    modeling a separate process with its own `_process_lock` rather than the
    in-process `ClassVar` all instances would otherwise share — must both
    succeed, leave exactly one migration-ledger marker, and migrate the three
    managed rows correctly (DD-15).

    The barrier gates entry to `_migrate_once` itself, not a specific SQL
    statement inside it. `__init__` always runs `_initialize_database()`
    before `_migrate_once()`, so both workers finish schema creation — the
    DDL that a connection-level barrier could otherwise strand mid-statement
    while the other worker waits at `BEGIN IMMEDIATE` — before either one is
    allowed to start migrating. That ordering deterministically guarantees
    both workers have entered their migration attempt before either can
    finish it, without depending on where inside `_migrate_once` the ledger
    check itself happens to sit.
    """

    _write_legacy_json(
        tmp_path, {"voice_brain_dump": {"mode": "on", "selected_users": []}}
    )

    barrier = threading.Barrier(2)
    original_migrate_once = FeatureFlagOverrideRepository._migrate_once

    def _barrier_gated_migrate_once(self: FeatureFlagOverrideRepository) -> None:
        barrier.wait(timeout=30)
        original_migrate_once(self)

    monkeypatch.setattr(
        FeatureFlagOverrideRepository, "_migrate_once", _barrier_gated_migrate_once
    )

    results: dict[str, FeatureFlagOverrideRepository] = {}
    errors: dict[str, BaseException] = {}
    results_lock = threading.Lock()

    def _construct(name: str) -> None:
        repo = object.__new__(FeatureFlagOverrideRepository)
        repo._process_lock = threading.RLock()  # isolate from the other "process"
        try:
            repo.__init__(
                tmp_path / "data",
                legacy_states={"mobile_task_classification": FeatureFlagState.ON},
            )
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            with results_lock:
                errors[name] = exc
            return
        with results_lock:
            results[name] = repo

    workers = [threading.Thread(target=_construct, args=(f"w{i}",)) for i in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert not errors, f"expected both constructors to succeed, got: {errors}"
    assert len(results) == 2

    db_path = _sqlite_db_path(tmp_path)
    with sqlite3.connect(db_path) as conn:
        ledger_count = conn.execute("SELECT COUNT(*) FROM migration_ledger").fetchone()[
            0
        ]
        flag_rows = conn.execute("SELECT flag FROM feature_flags").fetchall()

    assert ledger_count == 1
    assert {row[0] for row in flag_rows} == set(MANAGED_FLAGS)

    overlay = next(iter(results.values())).read()
    assert overlay.degraded is False
    assert overlay.flags["voice_brain_dump"].mode is FlagMode.ON
    assert overlay.flags["mobile_task_classification"].mode is FlagMode.ON
    assert overlay.flags["external_agent_relay"].mode is FlagMode.OFF


# ---------------------------------------------------------------------------
# SQLite is the sole runtime truth after migration: no env/JSON fallback,
# degraded means unreadable/missing-row/out-of-vocabulary — not "absence is
# healthy" (010-FR-003, 004; DD-2, DD-15)
# ---------------------------------------------------------------------------


def test_010_FR_003_after_migration_changed_env_and_json_have_no_further_effect(
    tmp_path: Path,
) -> None:
    """After the one-time migration, normal reads never consult the legacy
    JSON or the environment again — only the SQLite row (DD-15)."""

    repo = _sqlite_repo(
        tmp_path, legacy_states={"voice_brain_dump": FeatureFlagState.OFF}
    )
    _set_mode(repo, "voice_brain_dump", FlagMode.ON)

    _write_legacy_json(
        tmp_path, {"voice_brain_dump": {"mode": "off", "selected_users": []}}
    )
    reopened = _sqlite_repo(
        tmp_path, legacy_states={"voice_brain_dump": FeatureFlagState.OFF}
    )

    assert reopened.read().flags["voice_brain_dump"].mode is FlagMode.ON


def test_010_FR_004_a_missing_managed_flag_row_reads_degraded_not_healthy_absence(
    tmp_path: Path,
) -> None:
    """Post-migration, a missing managed-flag row is a storage failure
    (degraded), never the old "absence is healthy" starting state (DD-2)."""

    repo = _sqlite_repo(tmp_path)
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        conn.execute("DELETE FROM feature_flags WHERE flag = ?", ("voice_brain_dump",))
        conn.commit()

    overlay = repo.read()
    assert overlay.degraded is True
    with pytest.raises(DegradedRuntimeFlagsError):
        _set_mode(repo, "mobile_task_classification", FlagMode.ON)


def test_010_FR_004_an_out_of_vocabulary_stored_mode_reads_degraded(
    tmp_path: Path,
) -> None:
    """A row whose stored `mode` is outside the known vocabulary is degraded,
    not silently coerced or ignored (DD-2)."""

    repo = _sqlite_repo(tmp_path)
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        conn.execute(
            "UPDATE feature_flags SET mode = ? WHERE flag = ?",
            ("sideways", "voice_brain_dump"),
        )
        conn.commit()

    assert repo.read().degraded is True
    with pytest.raises(DegradedRuntimeFlagsError):
        _set_mode(repo, "voice_brain_dump", FlagMode.OFF)


def test_010_FR_004_an_unreadable_database_reads_degraded_and_refuses_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `sqlite3.Error`/`OSError` on the read itself reads as degraded and
    refuses every mutation, exactly like a missing row or a bad mode (DD-2)."""

    repo = _sqlite_repo(tmp_path)

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sqlite3, "connect", _explode)
    try:
        overlay = repo.read()
        assert overlay.degraded is True
        with pytest.raises(DegradedRuntimeFlagsError):
            _set_mode(repo, "voice_brain_dump", FlagMode.ON)
    finally:
        monkeypatch.undo()


# ---------------------------------------------------------------------------
# A7 — data-review blockers: legacy-email privacy leak (010-SC-007) and the
# degraded-transition double-warning race (010-FR-004)
# ---------------------------------------------------------------------------


def test_010_SC_007_legacy_entry_with_an_email_member_falls_back_to_env_baseline(
    tmp_path: Path,
) -> None:
    """A legacy `selected_users` member that doesn't match the exact account-ID
    grammar `[A-Za-z0-9_-]{1,128}` (an email, here) invalidates the *whole*
    legacy entry — migration must not persist any value from it, not merely
    drop the bad member — falling back to the already-defined environment
    baseline for that flag. No email sentinel reaches the database bytes."""

    _write_legacy_json(
        tmp_path,
        {
            "voice_brain_dump": {
                "mode": "selected_users",
                "selected_users": ["private@example.com"],
            }
        },
    )

    repo = _sqlite_repo(
        tmp_path, legacy_states={"voice_brain_dump": FeatureFlagState.OFF}
    )

    overlay = repo.read()
    assert overlay.flags["voice_brain_dump"].mode is FlagMode.OFF
    assert overlay.flags["voice_brain_dump"].selected_users == ()

    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        raw = "".join(str(row) for row in conn.execute("SELECT * FROM feature_flags"))
    assert "private@example.com" not in raw
    assert "@" not in raw


def test_010_SC_007_legacy_valid_duplicates_canonicalize_to_sorted_unique(
    tmp_path: Path,
) -> None:
    """Valid duplicate account IDs in a legacy cohort canonicalize to one
    entry per ID, in deterministic sorted order — a SQLite row like
    `["user_a", "user_a"]` must never be what migration produces."""

    _write_legacy_json(
        tmp_path,
        {
            "voice_brain_dump": {
                "mode": "selected_users",
                "selected_users": ["user_b", "user_a", "user_a"],
            }
        },
    )

    repo = _sqlite_repo(tmp_path)

    assert repo.read().flags["voice_brain_dump"].selected_users == (
        "user_a",
        "user_b",
    )


def test_010_SC_007_a_stored_row_with_an_invalid_id_reads_degraded(
    tmp_path: Path,
) -> None:
    """A post-migration SQLite row whose `selected_users` JSON contains a
    value outside the account-ID grammar (an email) is degraded/fail-closed,
    never trusted verbatim."""

    repo = _repo(tmp_path)
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        conn.execute(
            "UPDATE feature_flags SET mode = 'selected_users', selected_users = ? "
            "WHERE flag = ?",
            (json.dumps(["private@example.com"]), "voice_brain_dump"),
        )
        conn.commit()

    assert repo.read().degraded is True


def test_010_SC_007_a_stored_row_with_duplicate_ids_reads_degraded(
    tmp_path: Path,
) -> None:
    """A post-migration SQLite row whose `selected_users` JSON contains a
    duplicate account ID — e.g. `["user_a", "user_a"]` — is degraded/
    fail-closed rather than read as healthy with exposed duplicates."""

    repo = _repo(tmp_path)
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        conn.execute(
            "UPDATE feature_flags SET mode = 'selected_users', selected_users = ? "
            "WHERE flag = ?",
            (json.dumps(["user_a", "user_a"]), "voice_brain_dump"),
        )
        conn.commit()

    assert repo.read().degraded is True


def test_010_SC_007_mutate_with_an_invalid_id_rolls_back_and_persists_nothing(
    tmp_path: Path,
) -> None:
    """The write path itself enforces the account-ID privacy invariant, not
    only migration/read: a `mutate` whose apply result contains an invalid
    (email) member rolls back the whole transaction, and the sentinel value
    never reaches disk."""

    repo = _repo(tmp_path)

    def _apply(current: dict[str, FlagOverride]) -> dict[str, FlagOverride]:
        updated = dict(current)
        updated["voice_brain_dump"] = FlagOverride(
            mode=FlagMode.SELECTED_USERS, selected_users=(EMAIL_SENTINEL,)
        )
        return updated

    with pytest.raises(RepositoryError):
        repo.mutate(_apply)

    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        raw = "".join(str(row) for row in conn.execute("SELECT * FROM feature_flags"))
    assert EMAIL_SENTINEL not in raw

    overlay = repo.read()
    assert overlay.degraded is False
    assert overlay.flags["voice_brain_dump"].mode is FlagMode.OFF
    assert overlay.flags["voice_brain_dump"].selected_users == ()


def test_010_FR_004_two_concurrent_degraded_reads_log_exactly_one_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two threads racing into the healthy-to-degraded transition together —
    deterministically synchronized via a barrier so both reach the
    check/set/log step at the same time — still log exactly one coarse
    WARNING for this process. Cross-process global uniqueness is out of
    scope; this asserts per-repository/per-process behavior only."""

    repo = _repo(tmp_path)
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        conn.execute(
            "UPDATE feature_flags SET mode = ? WHERE flag = ?",
            ("sideways", "voice_brain_dump"),
        )
        conn.commit()

    barrier = threading.Barrier(2)
    original_load = FeatureFlagOverrideRepository._load

    def _barrier_gated_load(
        self: FeatureFlagOverrideRepository, conn: sqlite3.Connection
    ) -> Any:
        result = original_load(self, conn)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(FeatureFlagOverrideRepository, "_load", _barrier_gated_load)

    results: list[Any] = []

    def _reader() -> None:
        results.append(repo.read())

    threads = [threading.Thread(target=_reader) for _ in range(2)]
    try:
        with caplog.at_level(logging.WARNING, logger=REPOSITORY_LOGGER):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
    finally:
        monkeypatch.undo()

    assert len(results) == 2
    assert all(overlay.degraded for overlay in results)

    warnings = [
        record
        for record in caplog.records
        if record.name == REPOSITORY_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Release blocker A (2026-08-15) — the durable migration-complete marker.
#
# The migration ledger lives *inside* `feature_flags.sqlite3`, so deleting or
# recreating that file used to look exactly like a first start: migration
# re-ran, and the legacy JSON overlay re-seeded cohorts that GDPR erasure had
# already scrubbed. A non-PII marker beside the legacy document records that
# the one-time migration happened, durably and independently of the database
# file (010-FR-001, 010-FR-007, DD-9, DD-15).
# ---------------------------------------------------------------------------

PURGED_ACCOUNT_ID = "user_purged"


def _marker_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / Path(*MIGRATION_COMPLETE_MARKER_PARTS)


def _legacy_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "feature-flags" / "runtime.json"


def _exploding_seed_loader() -> ManagedFlagMigrationSeed:
    """A migration seed loader that fails if it is consulted at all.

    Stands in for the real deploy-staged environment input: once the marker
    exists, construction must never reach the loader, whatever the
    environment currently says (DD-15).
    """

    raise AssertionError("the migration seed loader must not be consulted")


def test_010_FR_001_a_successful_migration_writes_the_durable_marker(
    tmp_path: Path,
) -> None:
    """A ledgered migration leaves a marker beside the legacy document."""

    _sqlite_repo(tmp_path)

    marker = _marker_path(tmp_path)
    assert marker.is_file()
    assert json.loads(marker.read_text(encoding="utf-8"))["migration_id"]


def test_010_FR_001_an_existing_ledger_backfills_a_missing_marker(
    tmp_path: Path,
) -> None:
    """The commit-then-marker crash window self-heals: a store that already
    carries a migration-ledger row backfills the marker on the next
    construction, rather than staying one `rm` away from re-migrating."""

    _sqlite_repo(tmp_path)
    _marker_path(tmp_path).unlink()

    FeatureFlagOverrideRepository(tmp_path / "data")

    assert _marker_path(tmp_path).is_file()


def test_010_SC_007_the_migration_marker_carries_no_account_ids_or_emails(
    tmp_path: Path,
) -> None:
    """The marker records *that* migration happened, never *what* it moved:
    no account ID, no email, no environment value (010-SC-007)."""

    _write_legacy_json(
        tmp_path,
        {
            "voice_brain_dump": {
                "mode": "selected_users",
                "selected_users": ["user_cohort_member"],
            }
        },
    )

    _sqlite_repo(
        tmp_path,
        legacy_states={"mobile_task_classification": FeatureFlagState.INTERNAL},
        legacy_internal_users=frozenset({EMAIL_SENTINEL}),
        resolve_account_id=lambda email: "acct_internal",
    )

    text = _marker_path(tmp_path).read_text(encoding="utf-8")
    assert "user_cohort_member" not in text
    assert "acct_internal" not in text
    assert EMAIL_SENTINEL not in text
    assert "@" not in text
    assert "internal" not in text


def test_010_FR_007_scrub_removes_the_id_from_sqlite_and_the_retained_legacy_json(
    tmp_path: Path,
) -> None:
    """Erasure reaches the retained legacy artifact too: after `scrub_user`,
    the purged account ID is gone from the SQLite cohort *and* from the
    rollback-compatibility JSON document (DD-9, DD-13)."""

    legacy_path = _write_legacy_json(
        tmp_path,
        {
            "voice_brain_dump": {
                "mode": "selected_users",
                "selected_users": [PURGED_ACCOUNT_ID, "user_kept"],
            }
        },
    )

    repo = _sqlite_repo(tmp_path)
    assert repo.read().flags["voice_brain_dump"].selected_users == (
        "user_kept",
        PURGED_ACCOUNT_ID,
    )

    repo.scrub_user(PURGED_ACCOUNT_ID)

    assert repo.read().flags["voice_brain_dump"].selected_users == ("user_kept",)
    assert PURGED_ACCOUNT_ID not in legacy_path.read_text(encoding="utf-8")
    assert "user_kept" in legacy_path.read_text(encoding="utf-8")


def test_010_FR_007_a_recreated_database_after_the_marker_never_resurrects_a_purged_id(
    tmp_path: Path,
) -> None:
    """Deleting the database after migration is not a first start: the marker
    means the legacy document and the deploy-staged environment are never read
    again, and the missing rows initialize fail-closed OFF (DD-9, DD-15)."""

    _write_legacy_json(
        tmp_path,
        {
            "voice_brain_dump": {
                "mode": "selected_users",
                "selected_users": [PURGED_ACCOUNT_ID],
            }
        },
    )
    repo = _sqlite_repo(tmp_path)
    repo.scrub_user(PURGED_ACCOUNT_ID)

    # An operator-restored older copy of the artifact re-plants the ID; the
    # marker, not the artifact's contents, is what keeps it out.
    _write_legacy_json(
        tmp_path,
        {
            "voice_brain_dump": {
                "mode": "selected_users",
                "selected_users": [PURGED_ACCOUNT_ID],
            }
        },
    )
    _sqlite_db_path(tmp_path).unlink()

    reopened = FeatureFlagOverrideRepository(
        tmp_path / "data",
        load_migration_seed=_exploding_seed_loader,
    )

    overlay = reopened.read()
    assert overlay.degraded is False
    for flag in MANAGED_FLAGS:
        assert overlay.flags[flag].mode is FlagMode.OFF
        assert overlay.flags[flag].selected_users == ()

    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        raw = "".join(str(row) for row in conn.execute("SELECT * FROM feature_flags"))
    assert PURGED_ACCOUNT_ID not in raw


def test_010_FR_007_a_malformed_legacy_artifact_still_holding_the_id_is_removed(
    tmp_path: Path,
) -> None:
    """A degraded legacy artifact must not become a privacy leak: if it cannot
    be parsed and rewritten but still names the purged account, erasure
    removes the artifact outright rather than leaving the ID on the volume
    (DD-9). It is no longer a migration or runtime source by then."""

    legacy_path = _legacy_path(tmp_path)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    _sqlite_repo(tmp_path)
    legacy_path.write_text(
        '{"voice_brain_dump": {"selected_users": ["user_purged"',
        encoding="utf-8",
    )

    repo = FeatureFlagOverrideRepository(tmp_path / "data")
    repo.scrub_user(PURGED_ACCOUNT_ID)

    assert not legacy_path.exists()


def test_010_FR_007_scrub_leaves_an_unrelated_legacy_artifact_untouched(
    tmp_path: Path,
) -> None:
    """Erasure is surgical: an artifact that never named the purged account is
    preserved verbatim for rollback."""

    legacy_path = _write_legacy_json(
        tmp_path,
        {
            "voice_brain_dump": {
                "mode": "selected_users",
                "selected_users": ["user_kept"],
            }
        },
    )
    before = legacy_path.read_bytes()

    repo = _sqlite_repo(tmp_path)
    repo.scrub_user(PURGED_ACCOUNT_ID)

    assert legacy_path.read_bytes() == before


# ---------------------------------------------------------------------------
# Release blocker B (2026-08-15) — a corrupt or unreadable database file at
# construction. `sqlite3.connect` succeeds lazily; the `DatabaseError` lands
# on the first statement, i.e. inside `__init__`, which used to abort process
# startup entirely. Startup must instead survive into the already-specified
# degraded state: every flag ineffective, every mutation refused, exactly one
# warning (010-FR-004).
# ---------------------------------------------------------------------------

CORRUPT_DB_BYTES = b"not a sqlite database"


def _corrupt_store(tmp_path: Path) -> Path:
    db_path = _sqlite_db_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(CORRUPT_DB_BYTES)
    return db_path


def test_010_FR_004_a_corrupt_database_constructs_degraded_instead_of_raising(
    tmp_path: Path,
) -> None:
    """Construction over a corrupt file yields a usable, degraded repository."""

    _corrupt_store(tmp_path)

    repo = FeatureFlagOverrideRepository(tmp_path / "data")

    overlay = repo.read()
    assert overlay.degraded is True
    assert overlay.flags == {}


def test_010_FR_004_a_corrupt_database_refuses_every_mutation_without_writing(
    tmp_path: Path,
) -> None:
    """Mutations and erasure fail closed with the existing degraded error, and
    the corrupt file is never overwritten, quarantined or deleted."""

    db_path = _corrupt_store(tmp_path)
    repo = FeatureFlagOverrideRepository(tmp_path / "data")

    with pytest.raises(DegradedRuntimeFlagsError):
        _set_mode(repo, "voice_brain_dump", FlagMode.ON)
    with pytest.raises(DegradedRuntimeFlagsError):
        repo.scrub_user(PURGED_ACCOUNT_ID)

    assert db_path.read_bytes() == CORRUPT_DB_BYTES
    assert not _marker_path(tmp_path).exists()


def test_010_FR_004_a_corrupt_database_warns_once_across_concurrent_reads(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two threads whose first read of a corrupt store races still log exactly
    one coarse WARNING for the transition (010-FR-004)."""

    _corrupt_store(tmp_path)
    repo = FeatureFlagOverrideRepository(tmp_path / "data")

    barrier = threading.Barrier(2)
    original_ensure_ready = FeatureFlagOverrideRepository._ensure_ready

    def _barrier_gated_ensure_ready(self: FeatureFlagOverrideRepository) -> Any:
        result = original_ensure_ready(self)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(
        FeatureFlagOverrideRepository, "_ensure_ready", _barrier_gated_ensure_ready
    )

    results: list[Any] = []

    def _reader() -> None:
        results.append(repo.read())

    threads = [threading.Thread(target=_reader) for _ in range(2)]
    try:
        with caplog.at_level(logging.WARNING, logger=REPOSITORY_LOGGER):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
    finally:
        monkeypatch.undo()

    assert len(results) == 2
    assert all(overlay.degraded for overlay in results)

    warnings = [
        record
        for record in caplog.records
        if record.name == REPOSITORY_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1


def test_010_FR_004_replacing_a_corrupt_store_with_a_valid_one_recovers(
    tmp_path: Path,
) -> None:
    """Recovery is supported without any permissive fallback: once an operator
    puts a readable store back in place, the same repository instance reads it
    healthily again."""

    healthy_root = tmp_path / "healthy"
    _sqlite_repo(healthy_root, legacy_states={"voice_brain_dump": FeatureFlagState.ON})

    db_path = _corrupt_store(tmp_path)
    repo = FeatureFlagOverrideRepository(tmp_path / "data")
    assert repo.read().degraded is True

    db_path.write_bytes(_sqlite_db_path(healthy_root).read_bytes())

    overlay = repo.read()
    assert overlay.degraded is False
    assert overlay.flags["voice_brain_dump"].mode is FlagMode.ON


# ---------------------------------------------------------------------------
# Release blocker C (2026-08-15) — the deploy-staged managed-flag environment
# input is parsed only inside the serialized first-migration path, and only
# when neither the SQLite ledger nor the durable marker already says migration
# happened (DD-15).
# ---------------------------------------------------------------------------


def test_010_DD_15_an_invalid_pre_migration_seed_fails_closed_without_writing(
    tmp_path: Path,
) -> None:
    """Deferring the parse does not soften it: on a genuine first start an
    invalid managed input fails closed, leaving no rows, no ledger and no
    marker for a later construction to mistake for a completed migration."""

    def _invalid_seed() -> ManagedFlagMigrationSeed:
        raise ValueError(
            "Feature flag 'voice_brain_dump' has invalid state 'sideways'."
        )

    with pytest.raises(ManagedFlagMigrationError):
        FeatureFlagOverrideRepository(
            tmp_path / "data", load_migration_seed=_invalid_seed
        )

    assert not _marker_path(tmp_path).exists()
    with sqlite3.connect(_sqlite_db_path(tmp_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM feature_flags").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM migration_ledger").fetchone()[0] == 0


def test_010_DD_15_the_seed_loader_is_consulted_exactly_once_on_first_start(
    tmp_path: Path,
) -> None:
    """The loader runs on the first start and never again — not on the next
    construction, and not when the database is later recreated."""

    calls: list[int] = []

    def _seed() -> ManagedFlagMigrationSeed:
        calls.append(1)
        return ManagedFlagMigrationSeed(
            states={"voice_brain_dump": FeatureFlagState.ON},
            internal_users=frozenset(),
        )

    repo = FeatureFlagOverrideRepository(tmp_path / "data", load_migration_seed=_seed)
    assert repo.read().flags["voice_brain_dump"].mode is FlagMode.ON

    FeatureFlagOverrideRepository(tmp_path / "data", load_migration_seed=_seed)
    _sqlite_db_path(tmp_path).unlink()
    FeatureFlagOverrideRepository(tmp_path / "data", load_migration_seed=_seed)

    assert len(calls) == 1
