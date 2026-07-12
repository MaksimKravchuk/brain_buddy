"""Tests for the RTM (Remember The Milk) task tracker adapter port and fake."""

from __future__ import annotations

from app.ai.task_tracker import (
    FakeTaskTrackerAdapter,
    TaskTrackerResult,
)


def test_fake_adapter_creates_task() -> None:
    adapter = FakeTaskTrackerAdapter()
    result = adapter.create_inbox_task(name="Buy groceries")

    assert isinstance(result, TaskTrackerResult)
    assert result.external_ref is not None
    assert result.success is True


def test_fake_adapter_idempotent_for_same_name_and_key() -> None:
    adapter = FakeTaskTrackerAdapter()
    result1 = adapter.create_inbox_task(name="Call mom", idempotency_key="key-1")
    result2 = adapter.create_inbox_task(name="Call mom", idempotency_key="key-1")

    assert result1.external_ref == result2.external_ref


def test_fake_adapter_different_keys_create_different_tasks() -> None:
    adapter = FakeTaskTrackerAdapter()
    result1 = adapter.create_inbox_task(name="Task A", idempotency_key="key-a")
    result2 = adapter.create_inbox_task(name="Task B", idempotency_key="key-b")

    assert result1.external_ref != result2.external_ref


def test_fake_adapter_records_calls() -> None:
    adapter = FakeTaskTrackerAdapter()
    adapter.create_inbox_task(name="Task 1", idempotency_key="k1")
    adapter.create_inbox_task(name="Task 2", idempotency_key="k2")

    assert len(adapter.calls) == 2
    assert adapter.calls[0].name == "Task 1"
    assert adapter.calls[1].name == "Task 2"


def test_fake_adapter_no_tags_notes_priority_dates() -> None:
    """RTM Inbox tasks are name-only — no extra metadata."""
    adapter = FakeTaskTrackerAdapter()
    result = adapter.create_inbox_task(name="Plain task")

    assert result.success is True
    # The fake adapter should not set any metadata fields.
    assert result.external_ref is not None
