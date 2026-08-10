"""Concurrency tests for the global tree index."""

from __future__ import annotations

import json
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


def test_upsert_replaces_existing_entry_and_serializes_optional_defaults(
    tmp_path,
) -> None:
    repository = IndexRepository(tmp_path)
    first = IndexEntry(
        id="tree_a",
        title="Original",
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        owner_id="owner_a",
    )
    replacement = IndexEntry(
        id="tree_a",
        title="Replacement",
        description="updated description",
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    repository.upsert(first)
    repository.upsert(replacement)

    assert repository.load_all() == [replacement]
    assert json.loads(repository.index_path.read_text(encoding="utf-8")) == [
        replacement.model_dump(mode="json")
    ]
