"""Tests for the Brain Dump session repository (file-backed persistence)."""

from __future__ import annotations

from pathlib import Path

from app.repositories.brain_dump import BrainDumpRepository
from app.schemas.brain_dump import BrainDumpSession, Draft, SessionStatus
from app.utils.time import utcnow


def _make_session(
    owner_id: str = "owner-a", session_id: str = "bd-1"
) -> BrainDumpSession:
    now = utcnow()
    return BrainDumpSession(
        id=session_id,
        owner_id=owner_id,
        status=SessionStatus.RECORDING,
        drafts=[],
        created_at=now,
        updated_at=now,
        revision=1,
    )


def test_create_and_load_session(data_dir: Path) -> None:
    repo = BrainDumpRepository(data_dir)
    session = _make_session()
    repo.save(session)

    loaded = repo.load(session.id, owner_id=session.owner_id)
    assert loaded.id == session.id
    assert loaded.owner_id == session.owner_id
    assert loaded.status == SessionStatus.RECORDING


def test_load_wrong_owner_returns_none(data_dir: Path) -> None:
    repo = BrainDumpRepository(data_dir)
    session = _make_session(owner_id="owner-a")
    repo.save(session)

    # Owner B cannot load owner A's session.
    assert repo.load(session.id, owner_id="owner-b") is None


def test_load_nonexistent_returns_none(data_dir: Path) -> None:
    repo = BrainDumpRepository(data_dir)
    assert repo.load("missing", owner_id="owner-a") is None


def test_save_updates_existing_session(data_dir: Path) -> None:
    repo = BrainDumpRepository(data_dir)
    session = _make_session()
    repo.save(session)

    session.status = SessionStatus.REVIEWING
    session.drafts.append(
        Draft(
            id="d1",
            text="Buy groceries",
            created_at=utcnow(),
            updated_at=utcnow(),
            revision=1,
        )
    )
    repo.save(session)

    loaded = repo.load(session.id, owner_id=session.owner_id)
    assert loaded is not None
    assert loaded.status == SessionStatus.REVIEWING
    assert len(loaded.drafts) == 1
    assert loaded.drafts[0].text == "Buy groceries"


def test_get_active_session_by_owner(data_dir: Path) -> None:
    repo = BrainDumpRepository(data_dir)
    session = _make_session(owner_id="owner-a", session_id="bd-active")
    repo.save(session)

    # Completed session should not be returned as active.
    completed = _make_session(owner_id="owner-a", session_id="bd-done")
    completed.status = SessionStatus.COMPLETED
    repo.save(completed)

    active = repo.get_active_session(owner_id="owner-a")
    assert active is not None
    assert active.id == "bd-active"


def test_no_active_session_returns_none(data_dir: Path) -> None:
    repo = BrainDumpRepository(data_dir)
    assert repo.get_active_session(owner_id="owner-a") is None


def test_draft_ordering_preserved(data_dir: Path) -> None:
    repo = BrainDumpRepository(data_dir)
    session = _make_session()
    now = utcnow()
    for i in range(5):
        session.drafts.append(
            Draft(
                id=f"d{i}", text=f"Task {i}", created_at=now, updated_at=now, revision=1
            )
        )
    repo.save(session)

    loaded = repo.load(session.id, owner_id=session.owner_id)
    assert loaded is not None
    assert [d.text for d in loaded.drafts] == [f"Task {i}" for i in range(5)]


def test_export_results_persisted(data_dir: Path) -> None:
    repo = BrainDumpRepository(data_dir)
    session = _make_session()
    session.export_results = [{"draft_id": "d1", "external_ref": "rtm-123"}]
    repo.save(session)

    loaded = repo.load(session.id, owner_id=session.owner_id)
    assert loaded is not None
    assert loaded.export_results == [{"draft_id": "d1", "external_ref": "rtm-123"}]
