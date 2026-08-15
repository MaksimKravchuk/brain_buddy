"""Durable runtime feature-flag store: round-trip, atomicity, degradation.

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from app.repositories.feature_flag import (
    MANAGED_FLAGS,
    DegradedRuntimeFlagsError,
    FeatureFlagOverrideRepository,
    FlagMode,
    FlagOverride,
)

REPOSITORY_LOGGER = "app.repositories.feature_flag"

#: Planted in the document and in mutation inputs so a privacy assertion fails
#: loudly if member content ever reaches the file (010-SC-007).
EMAIL_SENTINEL = "zzsentinel@example.com"


def _repo(tmp_path: Path) -> FeatureFlagOverrideRepository:
    return FeatureFlagOverrideRepository(tmp_path / "data")


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


def _write_raw(repo: FeatureFlagOverrideRepository, text: str) -> None:
    repo.document_path.parent.mkdir(parents=True, exist_ok=True)
    repo.document_path.write_text(text, encoding="utf-8")


def _raw(repo: FeatureFlagOverrideRepository) -> Any:
    return json.loads(repo.document_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# A1 — round trip and healthy absence
# ---------------------------------------------------------------------------


def test_010_FR_001_document_round_trips_modes_and_cohorts(tmp_path: Path) -> None:
    """A written document round-trips its modes and cohorts."""

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
    assert overlay.flags["mobile_task_classification"].selected_users == ()


def test_010_FR_001_document_lands_under_feature_flags_runtime_json(
    tmp_path: Path,
) -> None:
    """The document lands at `{data_dir}/feature-flags/runtime.json`."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.ON)

    expected = tmp_path / "data" / "feature-flags" / "runtime.json"
    assert repo.document_path == expected
    assert expected.is_file()


def test_010_FR_005_never_written_directory_reads_healthy_empty_overlay(
    tmp_path: Path,
) -> None:
    """A never-yet-written data directory reads as the healthy empty overlay."""

    overlay = _repo(tmp_path).read()

    assert overlay.degraded is False
    assert dict(overlay.flags) == {}


# ---------------------------------------------------------------------------
# A2 — atomicity and idempotence
# ---------------------------------------------------------------------------


def test_010_FR_005_failure_between_write_and_rename_keeps_previous_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash between the temporary write and the rename keeps the old bytes."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.ON)
    before = repo.document_path.read_bytes()

    original_replace = Path.replace

    def _explode(self: Path, target: Any) -> Path:
        if Path(target) == repo.document_path:
            raise OSError("disk gave up between write and rename")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _explode)

    with pytest.raises(OSError):
        _set_mode(repo, "voice_brain_dump", FlagMode.OFF)

    monkeypatch.undo()
    assert repo.document_path.read_bytes() == before
    assert repo.read().flags["voice_brain_dump"].mode is FlagMode.ON


def test_010_SC_005_repeating_a_mutation_leaves_the_document_byte_identical(
    tmp_path: Path,
) -> None:
    """Repeating any targeted mutation is a byte-identical no-op that succeeds."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    once = repo.document_path.read_bytes()

    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")

    assert repo.document_path.read_bytes() == once


def test_010_SC_005_no_partially_written_document_is_observable(
    tmp_path: Path,
) -> None:
    """Every observable document version parses; no partial write is visible."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.ON)
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
    """Threads mutating different flags all land in the document on disk."""

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

    document = _raw(repo)
    for flag in MANAGED_FLAGS:
        assert document[flag]["mode"] == "on"


def test_010_SC_005_concurrent_adds_to_one_flag_all_survive(tmp_path: Path) -> None:
    """Threads adding different accounts to one flag all land on disk."""

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

    stored = _raw(repo)["voice_brain_dump"]["selected_users"]
    assert sorted(stored) == sorted(account_ids)


# ---------------------------------------------------------------------------
# A4 — healthy absence vs degraded corruption, and forward compatibility
# ---------------------------------------------------------------------------


def test_010_FR_004_first_mutation_against_an_absent_document_creates_it(
    tmp_path: Path,
) -> None:
    """A mutation against an absent document succeeds and creates the file."""

    repo = _repo(tmp_path)
    assert repo.document_path.exists() is False

    _set_mode(repo, "voice_brain_dump", FlagMode.ON)

    assert repo.document_path.is_file()
    assert repo.read().flags["voice_brain_dump"].mode is FlagMode.ON


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("truncated", '{"voice_brain_dump": {"mode": "o'),
        ("invalid_syntax", "{not json at all}"),
        ("top_level_not_an_object", '["voice_brain_dump"]'),
        ("unknown_mode_in_managed_entry", '{"voice_brain_dump": {"mode": "maybe"}}'),
        ("managed_entry_not_an_object", '{"voice_brain_dump": 7}'),
        (
            "cohort_not_a_string_array",
            '{"voice_brain_dump": {"mode": "selected_users", "selected_users": 3}}',
        ),
    ],
)
def test_010_FR_004_malformed_document_reads_degraded_and_refuses_mutation(
    tmp_path: Path, label: str, payload: str
) -> None:
    """A malformed document reads degraded and refuses every mutation."""

    repo = _repo(tmp_path)
    _write_raw(repo, payload)
    before = repo.document_path.read_bytes()

    overlay = repo.read()
    assert overlay.degraded is True, label
    assert dict(overlay.flags) == {}

    with pytest.raises(DegradedRuntimeFlagsError):
        _set_mode(repo, "voice_brain_dump", FlagMode.ON)

    assert repo.document_path.read_bytes() == before


@pytest.mark.parametrize("error", [OSError("io"), PermissionError("denied")])
def test_010_FR_004_unreadable_document_reads_degraded_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    """An I/O failure on the read itself reads degraded, never crashing callers."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.ON)
    before = repo.document_path.read_bytes()

    original_read_text = Path.read_text

    def _explode(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == repo.document_path:
            raise error
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _explode)

    overlay = repo.read()
    assert overlay.degraded is True
    assert dict(overlay.flags) == {}
    with pytest.raises(DegradedRuntimeFlagsError):
        _set_mode(repo, "voice_brain_dump", FlagMode.OFF)

    monkeypatch.undo()
    assert repo.document_path.read_bytes() == before


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("malformed_content", "{not json at all}"),
        ("unknown_mode", '{"voice_brain_dump": {"mode": "maybe"}}'),
    ],
)
def test_010_SC_008_degraded_transition_warns_exactly_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, label: str, payload: str
) -> None:
    """The healthy-to-degraded transition emits exactly one coarse WARNING."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    assert repo.read().degraded is False

    _write_raw(repo, payload)
    with caplog.at_level(logging.WARNING, logger=REPOSITORY_LOGGER):
        repo.read()
        repo.read()
        repo.read()

    warnings = [
        record
        for record in caplog.records
        if record.name == REPOSITORY_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, label
    message = warnings[0].getMessage()
    assert "correlation=" in message
    assert "reason=" in message
    assert "overrides_inactive=1" in message
    for forbidden in ("user_alpha", EMAIL_SENTINEL, "@", "display"):
        assert forbidden not in message


def test_010_SC_008_first_read_after_startup_degraded_still_warns_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A process whose very first read is degraded still warns exactly once."""

    repo = _repo(tmp_path)
    _write_raw(repo, "{broken")

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
    _write_raw(repo, "{broken")
    with caplog.at_level(logging.WARNING, logger=REPOSITORY_LOGGER):
        repo.read()
        repo.document_path.unlink()
        repo.read()
        _write_raw(repo, "{broken again")
        repo.read()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


def test_010_FR_004_unknown_entries_are_ignored_and_preserved_across_mutation(
    tmp_path: Path,
) -> None:
    """Unrecognized names, unmanaged flags and unknown fields survive a mutation."""

    repo = _repo(tmp_path)
    _write_raw(
        repo,
        json.dumps(
            {
                "future_flag": {"mode": "selected_users", "selected_users": ["user_x"]},
                "delivery_canary": {"mode": "on"},
                "voice_brain_dump": {
                    "mode": "on",
                    "selected_users": [],
                    "future_field": {"nested": True},
                },
            },
            indent=2,
        )
        + "\n",
    )

    overlay = repo.read()
    assert overlay.degraded is False
    assert set(overlay.flags) == {"voice_brain_dump"}

    _set_mode(repo, "mobile_task_classification", FlagMode.OFF)

    document = _raw(repo)
    assert document["future_flag"] == {
        "mode": "selected_users",
        "selected_users": ["user_x"],
    }
    assert document["delivery_canary"] == {"mode": "on"}
    assert document["voice_brain_dump"]["future_field"] == {"nested": True}
    assert document["mobile_task_classification"]["mode"] == "off"


# ---------------------------------------------------------------------------
# A5 — clearing an override
# ---------------------------------------------------------------------------


def test_010_FR_003_clear_removes_the_entire_entry_including_its_cohort(
    tmp_path: Path,
) -> None:
    """`clear(flag)` deletes the flag's whole runtime entry, cohort included."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    _set_mode(repo, "mobile_task_classification", FlagMode.ON)

    repo.clear("voice_brain_dump")

    overlay = repo.read()
    assert "voice_brain_dump" not in overlay.flags
    assert overlay.flags["mobile_task_classification"].mode is FlagMode.ON
    assert "voice_brain_dump" not in _raw(repo)


def test_010_FR_005_clearing_a_flag_with_no_entry_is_a_successful_no_op(
    tmp_path: Path,
) -> None:
    """Clearing a flag that has no entry succeeds and changes nothing."""

    repo = _repo(tmp_path)
    _set_mode(repo, "mobile_task_classification", FlagMode.ON)
    before = repo.document_path.read_bytes()

    overlay = repo.clear("voice_brain_dump")

    assert "voice_brain_dump" not in overlay.flags
    assert repo.document_path.read_bytes() == before


def test_010_FR_003_clearing_preserves_unknown_entries(tmp_path: Path) -> None:
    """Clearing one flag leaves an unknown entry preserved under DD-8."""

    repo = _repo(tmp_path)
    _write_raw(
        repo,
        json.dumps(
            {
                "future_flag": {"mode": "on"},
                "voice_brain_dump": {"mode": "on", "selected_users": []},
            },
            indent=2,
        )
        + "\n",
    )

    repo.clear("voice_brain_dump")

    document = _raw(repo)
    assert document == {"future_flag": {"mode": "on"}}


def test_010_FR_004_clear_is_refused_while_the_document_is_degraded(
    tmp_path: Path,
) -> None:
    """A clear against a degraded document is refused and writes nothing."""

    repo = _repo(tmp_path)
    _write_raw(repo, "{broken")
    before = repo.document_path.read_bytes()

    with pytest.raises(DegradedRuntimeFlagsError):
        repo.clear("voice_brain_dump")

    assert repo.document_path.read_bytes() == before


# ---------------------------------------------------------------------------
# A6 — purge scrub
# ---------------------------------------------------------------------------


def test_010_FR_007_scrub_user_reaches_every_parseable_cohort(tmp_path: Path) -> None:
    """`scrub_user` removes the ID from managed, unmanaged and undeclared entries."""

    repo = _repo(tmp_path)
    _write_raw(
        repo,
        json.dumps(
            {
                "voice_brain_dump": {
                    "mode": "selected_users",
                    "selected_users": ["user_alpha", "user_beta"],
                },
                "mobile_task_classification": {
                    "mode": "off",
                    "selected_users": ["user_beta"],
                },
                "delivery_canary": {
                    "mode": "on",
                    "selected_users": ["user_alpha", "user_beta"],
                    "note": "unmanaged but parseable",
                },
                "future_flag": {
                    "selected_users": ["user_alpha"],
                    "future_field": {"kept": True},
                },
            },
            indent=2,
        )
        + "\n",
    )

    scrubbed = repo.scrub_user("user_alpha")

    document = _raw(repo)
    assert scrubbed == 3
    assert document["voice_brain_dump"]["selected_users"] == ["user_beta"]
    assert document["mobile_task_classification"]["selected_users"] == ["user_beta"]
    assert document["delivery_canary"]["selected_users"] == ["user_beta"]
    assert document["delivery_canary"]["note"] == "unmanaged but parseable"
    assert document["future_flag"]["selected_users"] == []
    assert document["future_flag"]["future_field"] == {"kept": True}


def test_010_FR_001_scrub_user_is_idempotent_and_leaves_other_ids_untouched(
    tmp_path: Path,
) -> None:
    """Scrubbing twice, or an ID never present, succeeds and changes nothing."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    _add_user(repo, "voice_brain_dump", "user_beta")

    assert repo.scrub_user("user_alpha") == 1
    after_first = repo.document_path.read_bytes()

    assert repo.scrub_user("user_alpha") == 0
    assert repo.scrub_user("user_never_here") == 0

    assert repo.document_path.read_bytes() == after_first
    assert repo.read().flags["voice_brain_dump"].selected_users == ("user_beta",)


def test_010_FR_007_scrub_user_raises_against_a_degraded_document(
    tmp_path: Path,
) -> None:
    """A degraded document makes `scrub_user` raise rather than silently skip."""

    repo = _repo(tmp_path)
    _write_raw(repo, '{"voice_brain_dump": {"mode": "sideways"}}')
    before = repo.document_path.read_bytes()

    with pytest.raises(DegradedRuntimeFlagsError):
        repo.scrub_user("user_alpha")

    assert repo.document_path.read_bytes() == before


def test_010_FR_007_scrub_user_on_an_absent_document_is_a_no_op(
    tmp_path: Path,
) -> None:
    """An absent document is healthy, so a scrub succeeds and writes nothing."""

    repo = _repo(tmp_path)

    assert repo.scrub_user("user_alpha") == 0
    assert repo.document_path.exists() is False


# ---------------------------------------------------------------------------
# A7 — document-shape privacy
# ---------------------------------------------------------------------------


def test_010_SC_007_document_shape_admits_only_flag_names_modes_and_ids(
    tmp_path: Path,
) -> None:
    """The on-disk key set admits only flag names, modes and account-ID arrays."""

    repo = _repo(tmp_path)
    _set_mode(repo, "voice_brain_dump", FlagMode.SELECTED_USERS)
    _add_user(repo, "voice_brain_dump", "user_alpha")
    _set_mode(repo, "mobile_task_classification", FlagMode.OFF)

    document = _raw(repo)
    assert set(document) <= set(MANAGED_FLAGS)
    for entry in document.values():
        assert set(entry) == {"mode", "selected_users"}
        assert entry["mode"] in {"off", "on", "selected_users"}
        assert all(isinstance(value, str) for value in entry["selected_users"])


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

    raw_text = repo.document_path.read_text(encoding="utf-8")
    assert EMAIL_SENTINEL not in raw_text
    assert "@" not in raw_text
