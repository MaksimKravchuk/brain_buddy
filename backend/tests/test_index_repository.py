"""Concurrency tests for the global tree index."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event

from app.repositories.index import IndexRepository
from app.schemas.domain import IndexEntry


def test_concurrent_upserts_preserve_entries_for_different_trees(
    tmp_path, monkeypatch
) -> None:
    repository = IndexRepository(tmp_path)
    writers_ready = Barrier(2)
    first_save_started = Event()
    release_first_save = Event()
    original_save_all = repository.save_all

    def block_first_save(entries):
        if not first_save_started.is_set():
            first_save_started.set()
            assert release_first_save.wait(timeout=2)
        original_save_all(entries)

    monkeypatch.setattr(repository, "save_all", block_first_save)
    now = datetime.now(UTC)

    def upsert(tree_id: str) -> None:
        writers_ready.wait(timeout=2)
        repository.upsert(
            IndexEntry(
                id=tree_id,
                title=tree_id,
                updated_at=now,
                owner_id="owner",
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(upsert, "tree_a")
        second = executor.submit(upsert, "tree_b")
        assert first_save_started.wait(timeout=2)
        release_first_save.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert {entry.id for entry in repository.load_all()} == {"tree_a", "tree_b"}
