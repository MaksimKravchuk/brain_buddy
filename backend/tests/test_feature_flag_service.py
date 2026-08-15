"""The runtime SQLite resolver: exclusive authority, per-flag semantics, refusals.

ADR-0019 (2026-08-15) replaced the original JSON-overlay-plus-environment
design with SQLite as the sole source of truth for three managed flags. The
tests below target that contract directly: there is no more per-request
fallback to the environment baseline, no "deploy default" to inherit or
clear, and no `clear_override` mutation (DD-2, DD-3, DD-15; see
`test_feature_flag_repository.py` for the migration contract itself).

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core.config import (
    KNOWN_FEATURE_FLAGS,
    AppConfig,
    FeatureFlagSettings,
    ManagedFlagMigrationSeed,
    get_config,
)
from app.exceptions import StorageUnavailableError, ValidationFailure
from app.main import create_app
from app.repositories import SessionRepository, UserRepository
from app.repositories.feature_flag import (
    MANAGED_FLAGS,
    DegradedRuntimeFlagsError,
    FeatureFlagOverrideRepository,
    FlagMode,
    FlagOverride,
)
from app.schemas.auth import Invite, User
from app.services import AdminService
from app.services.feature_flag_service import (
    FeatureFlagService,
    SelectedUserNotFoundError,
)
from app.utils.time import utcnow

SERVICE_LOGGER = "app.services.feature_flag_service"

COHORT_EMAIL = "cohort@example.com"
OUTSIDER_EMAIL = "outsider@example.com"
PASSWORD = "correct-horse-battery-staple"

_CONSENT_BODY = {
    "consent": {
        "microphone": True,
        "external_processing_allowed": False,
        "provider": None,
        "language_hints": [],
        "vocabulary": [],
    }
}


@pytest.fixture(autouse=True)
def _reset_config_cache() -> Generator[None, None, None]:
    get_config.cache_clear()  # type: ignore[attr-defined]
    yield
    get_config.cache_clear()  # type: ignore[attr-defined]


def _config(
    monkeypatch: pytest.MonkeyPatch,
    data_dir: Path,
    *,
    flags: str,
    internal_users: str | None = None,
) -> AppConfig:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", flags)
    if internal_users is None:
        monkeypatch.delenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", raising=False)
    else:
        monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", internal_users)
    get_config.cache_clear()  # type: ignore[attr-defined]
    return get_config()


def _user(user_id: str, email: str) -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="argon2-not-used-here",
        created_at=utcnow(),
    )


def _service(
    config: AppConfig,
    data_dir: Path,
    *,
    relay_capability_available: bool = True,
    load_migration_seed: Callable[[], ManagedFlagMigrationSeed] | None = None,
) -> FeatureFlagService:
    """Build a service wired the way `build_container` wires production: the
    repository's one-time migration seeds from the same config the service
    resolves `delivery_canary` from, so `flags=`/`internal_users=` in `_config`
    are visible to both (ADR-0019 §3).

    `load_migration_seed` overrides that seed callback, so a test can build a
    service over an *already-migrated* directory whose only parser of managed
    environment text refuses to run.
    """

    user_repo = UserRepository(data_dir)

    def _resolve_account_id(email: str) -> str | None:
        account = user_repo.get_by_email(email)
        return account.id if account is not None else None

    repository = FeatureFlagOverrideRepository(
        data_dir,
        load_migration_seed=(
            load_migration_seed
            if load_migration_seed is not None
            else config.feature_flags.load_managed_migration_seed
        ),
        resolve_account_id=_resolve_account_id,
    )
    return FeatureFlagService(
        repository=repository,
        config=config,
        user_repo=user_repo,
        admin_service=AdminService(
            user_repo=user_repo,
            session_repo=SessionRepository(data_dir),
            operator_emails=frozenset(),
        ),
        relay_capability_available=relay_capability_available,
    )


# ---------------------------------------------------------------------------
# B1 — the key set, and the one flag that stays environment-owned
# ---------------------------------------------------------------------------


def test_010_FR_008_delivery_canary_always_matches_the_environment_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`delivery_canary` is the only flag ADR-0019 leaves environment-owned; a
    managed-flag mutation elsewhere never changes its effective value."""

    config = _config(
        monkeypatch,
        tmp_path,
        flags="delivery_canary=internal,external_agent_relay=on,voice_brain_dump=off",
        internal_users=COHORT_EMAIL,
    )
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.ON, operator_id="user_op")

    for user in (
        _user("user_cohort", COHORT_EMAIL),
        _user("user_outsider", OUTSIDER_EMAIL),
    ):
        resolved = service.effective_flags(user)
        environment = config.feature_flags.delivery_canary_effective(user.email)
        assert resolved["delivery_canary"] == environment
        assert resolved["voice_brain_dump"] is True


@pytest.mark.parametrize(
    "delivery_canary_state,cohort_expected,outsider_expected",
    [
        ("off", False, False),
        ("internal", True, False),
        ("on", True, True),
    ],
)
def test_010_DD_15_effective_flags_never_consults_the_retired_env_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delivery_canary_state: str,
    cohort_expected: bool,
    outsider_expected: bool,
) -> None:
    """`effective_flags`/`is_effective`/`describe` must resolve every managed
    flag exclusively from a healthy SQLite store, never from the environment
    baseline ADR-0019 retired for those three (DD-15).

    Two halves, because the retirement has two parts. The aggregate resolver
    `FeatureFlagSettings.effective_flags` is *gone*, so its absence is asserted
    structurally rather than by trapping a call to it. What is left of the
    managed environment input — the raw text — has exactly one parser,
    `load_managed_migration_seed`, so a second service reading the same
    already-migrated directory with a seed loader that raises on any call
    proves runtime resolution never reaches for it.

    `delivery_canary` alone still resolves from config, through a narrower
    method, and must keep resolving OFF/INTERNAL/ON correctly for both a
    cohort and a non-cohort user."""

    config = _config(
        monkeypatch,
        tmp_path,
        flags=f"delivery_canary={delivery_canary_state}",
        internal_users=COHORT_EMAIL,
    )
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.ON, operator_id="user_op")

    assert not hasattr(FeatureFlagSettings, "effective_flags")
    assert not hasattr(config.feature_flags, "effective_flags")

    def _raiser() -> ManagedFlagMigrationSeed:
        raise AssertionError(
            "runtime resolution must never parse the managed environment input"
        )

    sealed = _service(config, tmp_path, load_migration_seed=_raiser)

    cohort_user = _user("user_cohort", COHORT_EMAIL)
    outsider = _user("user_outsider", OUTSIDER_EMAIL)

    cohort_result = sealed.effective_flags(cohort_user)
    outsider_result = sealed.effective_flags(outsider)

    assert set(cohort_result) == set(KNOWN_FEATURE_FLAGS)
    assert cohort_result["delivery_canary"] is cohort_expected
    assert outsider_result["delivery_canary"] is outsider_expected
    assert cohort_result["voice_brain_dump"] is True
    assert outsider_result["voice_brain_dump"] is True

    assert sealed.is_effective("voice_brain_dump", outsider) is True
    assert sealed.describe(operator_id="user_op").degraded is False


def test_010_FR_003_key_set_is_exactly_known_feature_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolver never adds or removes a key from the member-facing payload."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.ON, operator_id="user_op")

    assert set(service.effective_flags(_user("user_a", OUTSIDER_EMAIL))) == set(
        KNOWN_FEATURE_FLAGS
    )


def test_010_FR_003_effective_flags_never_blend_sqlite_with_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A managed flag's effective value is exclusively its SQLite row — there
    is no per-flag fallback to the environment baseline after migration
    (DD-15). Every one of the three managed flags exhibits this, including
    `external_agent_relay`."""

    config = _config(
        monkeypatch,
        tmp_path,
        flags=(
            "voice_brain_dump=on,mobile_task_classification=on,"
            "external_agent_relay=on"
        ),
    )
    service = _service(config, tmp_path, relay_capability_available=True)
    user = _user("user_env_only", OUTSIDER_EMAIL)

    for flag in MANAGED_FLAGS:
        service.set_mode(flag, FlagMode.OFF, operator_id="user_op")

    # Every managed flag's environment baseline says ON; SQLite alone says
    # OFF. If the resolver still blended the two, at least one would read
    # True here — DD-15 requires none to.
    for flag in MANAGED_FLAGS:
        assert service.is_effective(flag, user) is False


# ---------------------------------------------------------------------------
# B3 — per-flag semantics: the stored mode is the whole answer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", MANAGED_FLAGS)
def test_010_FR_003_a_stored_off_is_effective_for_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """A stored OFF is effective for nobody, whatever the deploy-staged
    baseline said before migration."""

    config = _config(monkeypatch, tmp_path, flags=f"{flag}=on")
    service = _service(config, tmp_path)
    service.set_mode(flag, FlagMode.OFF, operator_id="user_op")

    assert service.effective_flags(_user("user_a", OUTSIDER_EMAIL))[flag] is False
    assert service.effective_flags(_user("user_b", COHORT_EMAIL))[flag] is False


@pytest.mark.parametrize("flag", MANAGED_FLAGS)
def test_010_FR_003_a_stored_on_is_effective_for_every_authenticated_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """A stored ON is effective for every authenticated user."""

    config = _config(monkeypatch, tmp_path, flags=f"{flag}=off")
    service = _service(config, tmp_path)
    service.set_mode(flag, FlagMode.ON, operator_id="user_op")

    assert service.effective_flags(_user("user_a", OUTSIDER_EMAIL))[flag] is True


@pytest.mark.parametrize("flag", MANAGED_FLAGS)
def test_010_FR_007_selected_users_admits_exactly_the_stored_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """SELECTED_USERS admits its own IDs and nobody else, cohort user included."""

    config = _config(
        monkeypatch, tmp_path, flags=f"{flag}=internal", internal_users=COHORT_EMAIL
    )
    service = _service(config, tmp_path)
    service.set_mode(flag, FlagMode.SELECTED_USERS, operator_id="user_op")
    service.repository.mutate(
        lambda current: {
            **current,
            flag: FlagOverride(
                mode=FlagMode.SELECTED_USERS, selected_users=("user_chosen",)
            ),
        }
    )

    assert service.effective_flags(_user("user_chosen", OUTSIDER_EMAIL))[flag] is True
    # In the environment INTERNAL cohort, but not in the runtime set: the
    # SQLite row answers alone.
    assert service.effective_flags(_user("user_cohort", COHORT_EMAIL))[flag] is False


@pytest.mark.parametrize("flag", MANAGED_FLAGS)
def test_010_FR_007_a_stored_id_belonging_to_no_account_grants_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """An ID in a set that belongs to no account makes the flag effective for nobody."""

    config = _config(monkeypatch, tmp_path, flags=f"{flag}=off")
    service = _service(config, tmp_path)
    service.repository.mutate(
        lambda current: {
            **current,
            flag: FlagOverride(
                mode=FlagMode.SELECTED_USERS, selected_users=("user_ghost",)
            ),
        }
    )

    assert service.effective_flags(_user("user_real", OUTSIDER_EMAIL))[flag] is False


# ---------------------------------------------------------------------------
# B4 — scope refusal
# ---------------------------------------------------------------------------


_REFUSED_FLAGS = ("delivery_canary", "not_a_flag_at_all")
"""`admin_portal` no longer exists as a flag at all (ADR-0019, DD-14) — it is
not part of this refused set because it cannot even be configured any more."""


@pytest.mark.parametrize("flag", _REFUSED_FLAGS)
def test_010_FR_002_every_mutation_refuses_an_unmanaged_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """Every mutation refuses a flag outside the three-flag managed set."""

    config = _config(monkeypatch, tmp_path, flags="delivery_canary=on")
    service = _service(config, tmp_path)

    with pytest.raises(ValidationFailure):
        service.set_mode(flag, FlagMode.ON, operator_id="user_op")
    with pytest.raises(ValidationFailure):
        service.add_selected_user(flag, operator_id="user_op", account_id="user_a")
    with pytest.raises(ValidationFailure):
        service.remove_selected_user(flag, "user_a", operator_id="user_op")


def test_010_SC_006_delivery_canary_keeps_its_environment_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`delivery_canary`'s effective value stays exactly the environment
    answer: a mutation naming it is refused and never changes it."""

    config = _config(monkeypatch, tmp_path, flags="delivery_canary=on")
    service = _service(config, tmp_path)
    with pytest.raises(ValidationFailure):
        service.set_mode("delivery_canary", FlagMode.OFF, operator_id="user_op")

    user = _user("user_a", OUTSIDER_EMAIL)
    resolved = service.effective_flags(user)
    environment = config.feature_flags.delivery_canary_effective(user.email)
    assert resolved["delivery_canary"] == environment is True


def test_010_FR_002_an_unknown_mode_value_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mode outside the closed vocabulary is refused with no partial write."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)

    with pytest.raises(ValidationFailure):
        service.set_mode("voice_brain_dump", "sideways", operator_id="user_op")

    assert service.repository.read().flags["voice_brain_dump"].mode is FlagMode.OFF


# ---------------------------------------------------------------------------
# B5 — cohort retention across mode changes (DD-6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("inactive_mode", [FlagMode.OFF, FlagMode.ON])
def test_010_FR_005_a_cohort_survives_a_mode_change_and_is_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inactive_mode: FlagMode
) -> None:
    """A cohort is retained through OFF/ON and reactivated exactly on return."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.add_selected_user(
        "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
    )

    service.set_mode("voice_brain_dump", inactive_mode, operator_id="user_op")
    view = service.describe(operator_id="user_op")
    retained = next(f for f in view.flags if f.name == "voice_brain_dump")
    assert [u.account_id for u in retained.selected_users] == ["user_chosen"]

    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    assert (
        service.effective_flags(_user("user_chosen", "chosen@example.com"))[
            "voice_brain_dump"
        ]
        is True
    )


@pytest.mark.parametrize("inactive_mode", [FlagMode.OFF, FlagMode.ON])
def test_010_FR_010_cohort_mutations_are_refused_outside_selected_users_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inactive_mode: FlagMode
) -> None:
    """Add and remove are accepted only while the flag's mode is SELECTED_USERS."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.add_selected_user(
        "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
    )
    service.set_mode("voice_brain_dump", inactive_mode, operator_id="user_op")
    before = service.repository.read().flags

    with pytest.raises(ValidationFailure):
        service.add_selected_user(
            "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
        )
    with pytest.raises(ValidationFailure):
        service.remove_selected_user(
            "voice_brain_dump", "user_chosen", operator_id="user_op"
        )

    assert service.repository.read().flags == before


# ---------------------------------------------------------------------------
# B6 — no cache sits in front of SQLite
# ---------------------------------------------------------------------------


def test_010_FR_005_a_mutation_is_visible_to_the_very_next_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No stale cache survives a mutation made through the service itself."""

    config = _config(monkeypatch, tmp_path, flags="voice_brain_dump=on")
    service = _service(config, tmp_path)
    user = _user("user_a", OUTSIDER_EMAIL)
    assert service.effective_flags(user)["voice_brain_dump"] is True

    service.set_mode("voice_brain_dump", FlagMode.OFF, operator_id="user_op")

    assert service.effective_flags(user)["voice_brain_dump"] is False


def test_010_FR_005_a_mutation_committed_by_a_second_connection_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No cache sits between the service and the SQLite store: a row committed
    through a second repository instance over the same database is visible on
    the very next read, exactly like a same-process mutation (DD-15 — SQLite
    alone is authoritative, so there is nothing to invalidate)."""

    config = _config(monkeypatch, tmp_path, flags="voice_brain_dump=off")
    service = _service(config, tmp_path)
    user = _user("user_a", OUTSIDER_EMAIL)
    assert service.effective_flags(user)["voice_brain_dump"] is False

    other = FeatureFlagOverrideRepository(tmp_path)
    other.mutate(
        lambda current: {**current, "voice_brain_dump": FlagOverride(mode=FlagMode.ON)}
    )

    assert service.effective_flags(user)["voice_brain_dump"] is True


# ---------------------------------------------------------------------------
# B7 — degraded behaviour (DD-2)
# ---------------------------------------------------------------------------


def test_010_FR_004_degraded_resolves_every_managed_flag_ineffective_and_refuses_every_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded store resolves every managed flag ineffective for everyone —
    there is no environment fallback to answer from post-migration — and
    refuses every mutation."""

    config = _config(
        monkeypatch,
        tmp_path,
        flags="voice_brain_dump=internal",
        internal_users=COHORT_EMAIL,
    )
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_x", "x@example.com")
    with sqlite3.connect(service.repository.db_path) as conn:
        conn.execute(
            "UPDATE feature_flags SET mode = ? WHERE flag = ?",
            ("sideways", "voice_brain_dump"),
        )
        conn.commit()

    assert (
        service.effective_flags(_user("user_cohort", COHORT_EMAIL))["voice_brain_dump"]
        is False
    )
    assert (
        service.effective_flags(_user("user_out", OUTSIDER_EMAIL))["voice_brain_dump"]
        is False
    )
    assert service.describe(operator_id="user_op").degraded is True

    with pytest.raises(DegradedRuntimeFlagsError):
        service.set_mode("voice_brain_dump", FlagMode.ON, operator_id="user_op")
    with pytest.raises(DegradedRuntimeFlagsError):
        service.add_selected_user(
            "voice_brain_dump", operator_id="user_op", account_id="user_x"
        )


def test_010_SC_008_a_freshly_migrated_store_describes_as_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A freshly migrated store — the only state construction ever leaves,
    absence being impossible after migration (DD-2) — describes as healthy
    with every managed flag present."""

    config = _config(monkeypatch, tmp_path, flags="voice_brain_dump=on")
    service = _service(config, tmp_path)

    view = service.describe(operator_id="user_op")

    assert view.degraded is False
    assert [flag.name for flag in view.flags] == list(MANAGED_FLAGS)


def test_010_FR_006_describe_emits_exactly_one_aggregate_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One aggregate, content-free record per cohort-resolving read (DD-10)."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.add_selected_user(
        "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
    )

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        service.describe(operator_id="user_op")

    records = [r for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operator=user_op" in message
    assert "flags=3" in message
    assert "resolved_accounts=1" in message
    assert "chosen@example.com" not in message


def test_010_FR_006_each_mutation_emits_exactly_one_content_free_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One dedicated record per mutation, naming the target account when there is one."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        service.set_mode(
            "voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op"
        )
        service.add_selected_user(
            "voice_brain_dump", operator_id="user_op", email="chosen@example.com"
        )
        service.remove_selected_user(
            "voice_brain_dump", "user_chosen", operator_id="user_op"
        )

    records = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(records) == 3
    assert "action=set_mode" in records[0]
    assert "action=add_selected_user" in records[1]
    assert "account=user_chosen" in records[1]
    assert "action=remove_selected_user" in records[2]
    assert "account=user_chosen" in records[2]
    for message in records:
        assert "operator=user_op" in message
        assert "outcome=" in message
        assert "chosen@example.com" not in message


def test_010_FR_006_a_removal_of_a_non_account_shaped_id_is_not_logged_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A removal target that is not account-ID shaped is redacted, never echoed."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        service.remove_selected_user(
            "voice_brain_dump", "someone@example.com", operator_id="user_op"
        )

    message = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER][-1]
    assert "someone@example.com" not in message
    assert "account=-" in message


# ---------------------------------------------------------------------------
# B7a — revalidation under the write lock: purge and concurrent mode changes
# ---------------------------------------------------------------------------


def test_010_FR_007_a_purge_racing_the_lock_does_not_resurrect_the_scrubbed_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An account purged between resolution and the lock is refused, not
    silently re-added (010-FR-007, DD-13).

    `admin_service.find_account` is the last step `add_selected_user` takes
    before acquiring the repository's write lock, so hooking it deterministically
    simulates a purge that scrubs the cohort and deletes the account in the
    exact gap between that resolution and the lock — the same gap a real,
    unsynchronized purge could win.
    """

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_purged", "purged@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")

    real_find_account = service.admin_service.find_account

    def _find_then_purge(**kwargs: object) -> User | None:
        found = real_find_account(**kwargs)
        assert found is not None
        # `AccountService.purge_account` runs `feature_flag_repo.scrub_user`
        # first and `user_repo.delete` last (see account_service.py); these
        # are the two steps that matter for this race.
        service.repository.scrub_user(found.id)
        service.user_repo.delete(found.id)
        return found

    monkeypatch.setattr(service.admin_service, "find_account", _find_then_purge)

    with pytest.raises(SelectedUserNotFoundError):
        service.add_selected_user(
            "voice_brain_dump", operator_id="user_op", account_id="user_purged"
        )

    view = service.describe(operator_id="user_op")
    cohort = next(f for f in view.flags if f.name == "voice_brain_dump")
    assert cohort.selected_users == ()


def test_010_FR_007_add_is_refused_while_purge_has_scrubbed_the_cohort_but_not_yet_deleted_the_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`AccountService.purge_account` marks the account's `deletion_requested_at`
    before it scrubs the feature-flag cohort, and scrubs the cohort before it
    deletes the user record *last* (see account_service.py). In the window
    between the scrub and the delete the account is due for deletion but
    still resolves through `admin_service.find_account` and `UserRepository`,
    so the existence check alone does not refuse it. `add_selected_user` must
    still refuse there, and never reinsert the ID, using the account's own
    durable `deletion_requested_at` rather than a new lock, subsystem or
    tombstone
    (010-FR-007, DD-13).
    """

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    user = _seed_account(tmp_path, "user_due", "due@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")

    # Construct the real purge's intermediate state directly, short of its
    # final step: the account is marked due for deletion and the cohort is
    # scrubbed, but the user record itself is not deleted yet.
    service.repository.scrub_user(user.id)
    service.user_repo.mutate(
        user.id,
        lambda fresh: fresh.model_copy(update={"deletion_requested_at": utcnow()}),
    )
    assert service.user_repo.get_by_id(user.id) is not None

    caplog.clear()
    with (
        caplog.at_level(logging.INFO, logger=SERVICE_LOGGER),
        pytest.raises(SelectedUserNotFoundError),
    ):
        service.add_selected_user(
            "voice_brain_dump", operator_id="user_op", account_id="user_due"
        )

    # The purge now reaches its final step.
    service.user_repo.delete(user.id)

    view = service.describe(operator_id="user_op")
    cohort = next(f for f in view.flags if f.name == "voice_brain_dump")
    assert cohort.selected_users == ()

    records = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    add_records = [m for m in records if "action=add_selected_user" in m]
    assert len(add_records) == 1
    assert "outcome=no_account_found" in add_records[0]
    assert "due@example.com" not in add_records[0]


def test_010_FR_010_a_concurrent_mode_change_racing_add_selected_user_is_refused_not_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A `set_mode` away from SELECTED_USERS landing between this add's
    account resolution and its locked write is a clean refusal, not a write
    onto a cohort mode that no longer applies (010-FR-010)."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")

    real_find_account = service.admin_service.find_account

    def _find_then_change_mode(**kwargs: object) -> User | None:
        found = real_find_account(**kwargs)
        # Simulate a second operator's `set_mode` landing in the gap between
        # this add's account resolution and the lock it is about to take.
        service.set_mode("voice_brain_dump", FlagMode.OFF, operator_id="user_other")
        return found

    monkeypatch.setattr(service.admin_service, "find_account", _find_then_change_mode)

    caplog.clear()
    with (
        caplog.at_level(logging.INFO, logger=SERVICE_LOGGER),
        pytest.raises(ValidationFailure),
    ):
        service.add_selected_user(
            "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
        )

    view = service.describe(operator_id="user_op")
    changed = next(f for f in view.flags if f.name == "voice_brain_dump")
    assert changed.mode is FlagMode.OFF

    records = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    add_records = [m for m in records if "action=add_selected_user" in m]
    assert len(add_records) == 1
    assert "outcome=refused_mode_not_selected_users" in add_records[0]
    assert "account=-" in add_records[0]


def test_010_FR_010_a_concurrent_mode_change_racing_remove_selected_user_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A `set_mode` away from SELECTED_USERS landing between this call's start
    and its locked write is a clean refusal, never a `KeyError` from indexing
    a snapshot the race already changed underneath it (010-FR-010).

    `repository.mutate` is the one call both the pre-fix and current
    `remove_selected_user` reach only once, right before the lock, so hooking
    it is the version-independent way to land the race in that exact gap.
    """

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.repository.mutate(
        lambda current: {
            **current,
            "voice_brain_dump": FlagOverride(
                mode=FlagMode.SELECTED_USERS, selected_users=("user_chosen",)
            ),
        }
    )

    real_mutate = service.repository.mutate
    triggered = False

    def _mutate_after_racing_mode_change(apply: object) -> object:
        nonlocal triggered
        if not triggered:
            triggered = True
            service.set_mode("voice_brain_dump", FlagMode.OFF, operator_id="user_other")
        return real_mutate(apply)

    monkeypatch.setattr(service.repository, "mutate", _mutate_after_racing_mode_change)

    caplog.clear()
    with (
        caplog.at_level(logging.INFO, logger=SERVICE_LOGGER),
        pytest.raises(ValidationFailure),
    ):
        service.remove_selected_user(
            "voice_brain_dump", "user_chosen", operator_id="user_op"
        )

    view = service.describe(operator_id="user_op")
    retained = next(f for f in view.flags if f.name == "voice_brain_dump")
    assert retained.mode is FlagMode.OFF
    # DD-6: the race left the cohort retained, and the refused remove must
    # not have touched it either.
    assert [u.account_id for u in retained.selected_users] == ["user_chosen"]

    records = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    remove_records = [m for m in records if "action=remove_selected_user" in m]
    assert len(remove_records) == 1
    assert "outcome=refused_mode_not_selected_users" in remove_records[0]
    assert "account=-" in remove_records[0]


@pytest.mark.parametrize(
    "action,call",
    [
        (
            "set_mode",
            lambda service: service.set_mode(
                "voice_brain_dump", FlagMode.ON, operator_id="user_op"
            ),
        ),
        (
            "add_selected_user",
            lambda service: service.add_selected_user(
                "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
            ),
        ),
        (
            "remove_selected_user",
            lambda service: service.remove_selected_user(
                "voice_brain_dump", "user_chosen", operator_id="user_op"
            ),
        ),
    ],
)
def test_010_FR_006_a_refused_write_against_a_degraded_document_records_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    action: str,
    call: object,
) -> None:
    """Every mutation's own repository write can be refused for a degraded
    store; that refusal is still exactly one content-free record naming no
    account, not zero (010-FR-004, 010-FR-006, DD-10)."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    with sqlite3.connect(service.repository.db_path) as conn:
        conn.execute(
            "UPDATE feature_flags SET mode = ? WHERE flag = ?",
            ("sideways", "voice_brain_dump"),
        )
        conn.commit()

    caplog.clear()
    with (
        caplog.at_level(logging.INFO, logger=SERVICE_LOGGER),
        pytest.raises(DegradedRuntimeFlagsError),
    ):
        call(service)  # type: ignore[operator]

    records = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(records) == 1
    assert f"action={action}" in records[0]
    assert "outcome=refused_degraded" in records[0]
    assert "account=-" in records[0]
    assert "operator=user_op" in records[0]


@pytest.mark.parametrize(
    "action,call,expected_account",
    [
        (
            "set_mode",
            lambda service: service.set_mode(
                "voice_brain_dump", FlagMode.ON, operator_id="user_op"
            ),
            None,
        ),
        (
            "add_selected_user",
            lambda service: service.add_selected_user(
                "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
            ),
            "user_chosen",
        ),
        (
            "remove_selected_user",
            lambda service: service.remove_selected_user(
                "voice_brain_dump", "user_chosen", operator_id="user_op"
            ),
            "user_chosen",
        ),
    ],
)
def test_010_FR_006_an_atomic_write_failure_records_exactly_one_write_failed_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    action: str,
    call: object,
    expected_account: str | None,
) -> None:
    """A generic `OSError`/`StorageUnavailableError` from the repository's
    write — disk full, EIO, a permission failure — is never swallowed: it
    still surfaces to the caller so the existing 5xx behavior is unchanged,
    but each of the three mutations first records exactly one dedicated,
    content-free failure audit rather than none, and the store itself is
    untouched (010-FR-006, DD-10).
    """

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    before = service.repository.read().flags

    class _FailingConnection(sqlite3.Connection):
        """`sqlite3.Connection.execute` is a read-only slot on the instance,
        so the mid-transaction failure is injected via a `factory=` subclass
        rather than monkeypatching the instance."""

        def execute(self, sql: str, *params: object) -> sqlite3.Cursor:
            if sql.strip().upper().startswith("BEGIN IMMEDIATE"):
                raise sqlite3.OperationalError("disk full")
            return super().execute(sql, *params)

    original_connect = sqlite3.connect

    def _explode(*args: object, **kwargs: object) -> sqlite3.Connection:
        kwargs["factory"] = _FailingConnection
        return original_connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sqlite3, "connect", _explode)

    caplog.clear()
    with (
        caplog.at_level(logging.INFO, logger=SERVICE_LOGGER),
        pytest.raises(StorageUnavailableError),
    ):
        call(service)  # type: ignore[operator]

    monkeypatch.undo()
    assert service.repository.read().flags == before

    records = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    matching = [m for m in records if f"action={action}" in m]
    assert len(matching) == 1
    assert "outcome=write_failed" in matching[0]
    assert "chosen@example.com" not in matching[0]
    assert "operator=user_op" in matching[0]
    if expected_account is None:
        assert "account=-" in matching[0]
    else:
        assert f"account={expected_account}" in matching[0]


# ---------------------------------------------------------------------------
# Shared helper for account-backed cohorts
# ---------------------------------------------------------------------------


def _seed_account(data_dir: Path, user_id: str, email: str) -> User:
    repo = UserRepository(data_dir)
    user = User(
        id=user_id,
        email=email,
        password_hash="argon2-not-used-here",
        created_at=utcnow(),
    )
    repo.create(user)
    return user


# ---------------------------------------------------------------------------
# B8 / B8a — call-site coverage and the consent boundary, at the HTTP boundary
# ---------------------------------------------------------------------------


def _app_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    email: str,
    flags: str,
    internal_users: str | None = None,
) -> tuple[TestClient, Container, dict]:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", flags)
    if internal_users is None:
        monkeypatch.delenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", raising=False)
    else:
        monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", internal_users)
    get_config.cache_clear()  # type: ignore[attr-defined]
    app = create_app()
    container: Container = app.state.container
    container.invite_repo.create(Invite(code="invite_flags", created_at=utcnow()))
    client = TestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "invite_code": "invite_flags"},
    )
    assert resp.status_code == 201, resp.text
    return client, container, resp.json()


def _override(container: Container, flag: str, entry: FlagOverride) -> None:
    container.feature_flag_repo.mutate(lambda current: {**current, flag: entry})


def test_010_FR_008_runtime_off_closes_every_voice_brain_dump_call_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runtime OFF override closes the capture gate and the command route."""

    client, container, me = _app_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=on"
    )
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["voice_brain_dump"] is True
    )

    _override(container, "voice_brain_dump", FlagOverride(mode=FlagMode.OFF))

    assert client.get("/api/brain-dump-providers").status_code == 404
    assert (
        client.post(
            "/api/brain-dump-operations",
            headers={"Idempotency-Key": "flag-start"},
            json=_CONSENT_BODY,
        ).status_code
        == 404
    )
    commanded = client.post(
        "/api/brain-dump-operations/does-not-exist/commit",
        headers={"Idempotency-Key": "flag-commit"},
        json={"expected_revision": 1},
    )
    assert commanded.status_code == 404
    assert "not available" in commanded.text.lower()
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["voice_brain_dump"] is False
    )
    assert me["feature_flags"]["voice_brain_dump"] is True


def test_010_FR_008_runtime_cohort_opens_every_voice_brain_dump_call_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SELECTED_USERS override naming the caller admits every gated call site."""

    client, container, me = _app_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=off"
    )
    assert client.get("/api/brain-dump-providers").status_code == 404

    _override(
        container,
        "voice_brain_dump",
        FlagOverride(mode=FlagMode.SELECTED_USERS, selected_users=(me["id"],)),
    )

    assert client.get("/api/brain-dump-providers").status_code == 200
    started = client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "flag-start"},
        json=_CONSENT_BODY,
    )
    assert started.status_code == 201, started.text
    operation = started.json()
    commanded = client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "flag-commit"},
        json={"expected_revision": operation["revision"]},
    )
    # Admitted past the flag gate: the answer is now about the operation's own
    # state machine, never the fail-closed "not available" refusal.
    assert "not available" not in commanded.text.lower()
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["voice_brain_dump"] is True
    )


def test_010_DD_16_external_agent_relay_now_resolves_through_sqlite_not_env_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`external_agent_relay` is runtime-manageable through the SQLite
    resolver, exactly like the other two managed flags — the environment
    baseline only ever seeds it once, at migration. A runtime SQLite override
    on this flag must reach `/api/auth/me` the same way a `voice_brain_dump`
    override already does."""

    from app.api.dependencies import external_agent_relay_enabled

    client, container, me = _app_client(
        tmp_path,
        monkeypatch,
        email=OUTSIDER_EMAIL,
        flags="external_agent_relay=off",
    )

    _override(container, "external_agent_relay", FlagOverride(mode=FlagMode.ON))

    user = container.user_repo.get_by_id(me["id"])
    assert user is not None
    assert external_agent_relay_enabled(user, container.feature_flag_service) is True
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["external_agent_relay"]
        is True
    )


def test_010_FR_008_a_cohort_admission_does_not_move_the_consent_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newly admitted caller still fails visibly without per-recording consent."""

    client, container, me = _app_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=off"
    )
    _override(
        container,
        "voice_brain_dump",
        FlagOverride(mode=FlagMode.SELECTED_USERS, selected_users=(me["id"],)),
    )

    refused = client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "no-consent"},
        json={
            "consent": {
                "microphone": False,
                "external_processing_allowed": False,
                "provider": None,
                "language_hints": [],
                "vocabulary": [],
            }
        },
    )

    assert refused.status_code == 400, refused.text
    assert "consent" in refused.text.lower()


def test_010_FR_008_a_runtime_off_override_keeps_owner_authority_routes_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Withdraw/cancel/delete stay reachable under a runtime OFF override."""

    client, container, _me = _app_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=on"
    )
    started = client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "authority-start"},
        json=_CONSENT_BODY,
    )
    assert started.status_code == 201, started.text
    operation = started.json()

    _override(container, "voice_brain_dump", FlagOverride(mode=FlagMode.OFF))

    cancelled = client.post(
        f"/api/brain-dump-operations/{operation['id']}/cancel",
        headers={"Idempotency-Key": "authority-cancel"},
        json={"expected_revision": operation["revision"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    blocked = client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "authority-commit"},
        json={"expected_revision": cancelled.json()["revision"]},
    )
    assert blocked.status_code == 404
    assert "not available" in blocked.text.lower()


# ---------------------------------------------------------------------------
# DD-16 — the relay's capability boolean is a second, independent axis
# ---------------------------------------------------------------------------


def test_010_DD_16_external_agent_relay_is_now_a_runtime_manageable_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DD-16 makes `external_agent_relay` manageable like the other two flags:
    a mutation naming it must be accepted, not refused as unmanaged."""

    config = _config(monkeypatch, tmp_path, flags="external_agent_relay=off")
    service = _service(config, tmp_path)

    view = service.set_mode("external_agent_relay", FlagMode.ON, operator_id="user_op")

    assert any(
        flag.name == "external_agent_relay" and flag.mode is FlagMode.ON
        for flag in view.flags
    )


def test_010_DD_16_service_constructor_accepts_the_relay_capability_boolean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`FeatureFlagService` takes a constructor-supplied capability boolean, so
    the relay's effective value can AND it with the SQLite rollout answer."""

    config = _config(monkeypatch, tmp_path, flags="external_agent_relay=off")

    _service(config, tmp_path, relay_capability_available=True)


def test_010_DD_16_relay_effective_value_ands_rollout_with_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runtime ON never exposes the relay when no capability was constructed;
    a configured capability never overrides a SQLite OFF/non-matching answer —
    both axes must be favorable (DD-16)."""

    config = _config(monkeypatch, tmp_path, flags="external_agent_relay=off")
    user = _user("user_relay", OUTSIDER_EMAIL)

    rollout_on_capability_missing = _service(
        config, tmp_path / "case-a", relay_capability_available=False
    )
    rollout_on_capability_missing.set_mode(
        "external_agent_relay", FlagMode.ON, operator_id="user_op"
    )
    assert rollout_on_capability_missing.is_effective("external_agent_relay", user) is (
        False
    )

    rollout_off_capability_present = _service(
        config, tmp_path / "case-b", relay_capability_available=True
    )
    assert (
        rollout_off_capability_present.is_effective("external_agent_relay", user)
        is False
    )

    rollout_on_capability_present = _service(
        config, tmp_path / "case-c", relay_capability_available=True
    )
    rollout_on_capability_present.set_mode(
        "external_agent_relay", FlagMode.ON, operator_id="user_op"
    )
    assert (
        rollout_on_capability_present.is_effective("external_agent_relay", user) is True
    )
