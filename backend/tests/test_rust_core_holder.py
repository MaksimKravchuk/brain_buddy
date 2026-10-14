"""026-FR-002: one replaceable Rust runtime holder serves every core caller.

A contained Rust panic leaves the runtime closed. The Task and Review facades,
the sync receipt/device executors and the navigator hold ``RustCoreHolder``
instead of a raw runtime, so the next call after the poisoning runs on a fresh
runtime, while a call already in flight on the poisoned one still fails cleanly.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.modules.tasks import navigator
from app.modules.tasks.rust_adapter import RustBridgeError, RustCore, RustCoreHolder
from app.modules.tasks.rust_task_facade import _envelope, _inputs
from tests.allure_evidence import attach_json, check_equal

from .conftest import FrozenClock
from .test_sync_device_review import Device, new
from .test_sync_review_projection import Synced

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Rust core holder"),
    allure.story("A poisoned runtime is replaced for the next call"),
]


@pytest.fixture
def synced(api_client: TestClient, frozen_clock: FrozenClock) -> Synced:
    found = Synced(api_client, frozen_clock)
    found.grants_enabled()
    return found


@pytest.fixture
def device(synced: Synced) -> Device:
    return Device(synced)


def _decide(core: RustCore) -> Any:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    envelope = _envelope(
        "task.create",
        "task_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d12",
        {"title": "Held"},
        now,
        None,
    )
    return core.decide({}, envelope, _inputs(now, "owner-1"))


def test_026_FR_002_a_healthy_holder_keeps_one_runtime() -> None:
    holder = RustCoreHolder()
    with allure.step("repeated calls resolve to the same open runtime"):
        first = holder.get()
        check_equal("same runtime", holder.get() is first, True)
        check_equal("open", first.is_open, True)
        assert _decide(holder).change_set is not None
        check_equal("still the same", holder.get() is first, True)


def test_026_FR_002_a_poisoned_runtime_is_replaced_on_the_next_call() -> None:
    holder = RustCoreHolder()
    poisoned = holder.get()
    with allure.step("the runtime is poisoned"):
        poisoned.close()
        check_equal("is_open", poisoned.is_open, False)
    with allure.step("the next decision runs on a fresh runtime"):
        assert _decide(holder).change_set is not None
        fresh = holder.get()
        check_equal(
            "replaced and open", (fresh is not poisoned, fresh.is_open), (True, True)
        )
    with (
        allure.step("the poisoned runtime itself stays closed"),
        pytest.raises(RustBridgeError) as closed,
    ):
        attach_json("poisoned", {"is_open": poisoned.is_open})
        _decide(poisoned)
    check_equal("code", closed.value.code, "WORKSPACE_CLOSED")


def test_026_FR_002_concurrent_callers_during_replacement_get_one_runtime() -> None:
    created: list[RustCore] = []
    gate = threading.Event()

    def factory() -> RustCore:
        core = RustCore()
        created.append(core)
        if len(created) > 1:
            gate.wait(timeout=0.2)  # widen the race window for the replacement
        return core

    holder = RustCoreHolder(factory)
    holder.get().close()
    seen: list[RustCore] = []

    def call() -> None:
        seen.append(holder.get())

    with allure.step("sixteen callers race to use the poisoned holder"):
        threads = [threading.Thread(target=call) for _ in range(16)]
        for thread in threads:
            thread.start()
        gate.set()
        for thread in threads:
            thread.join()
        attach_json("callers", {"threads": len(threads), "answered": len(seen)})
    with allure.step("exactly one replacement was created and shared"):
        check_equal("runtimes created", len(created), 2)
        check_equal("distinct seen", {id(c) for c in seen}, {id(created[1])})


def test_026_FR_002_a_call_in_flight_on_the_poisoned_runtime_fails_cleanly() -> None:
    holder = RustCoreHolder()
    in_flight = holder.get()
    with allure.step("the runtime closes under a call that already resolved it"):
        in_flight.close()
        with pytest.raises(RustBridgeError) as failure:
            _decide(in_flight)
        check_equal("code", failure.value.code, "WORKSPACE_CLOSED")
    with allure.step("the failed call is not retried on the replacement"):
        replacement = holder.get()
        check_equal("replaced", replacement is not in_flight, True)


def test_026_FR_002_task_create_review_decide_and_device_commands_survive_poisoning(
    synced: Synced, device: Device
) -> None:
    holder = synced.container.rust_core
    api = synced.api
    with allure.step("the container's facades and stores share the one holder"):
        task_core = synced.container.task_service._rust_facade._core
        review_core = synced.container.review_service._rust_facade._core
        check_equal(
            "shared", (holder is task_core, holder is review_core), (True, True)
        )
    poisoned = holder.get()
    poisoned.close()
    with allure.step("a Task create succeeds on a fresh runtime"):
        created = api.create("after the panic", state="next")
        check_equal("state", created["state"], "next")
        check_equal("replaced", holder.get() is not poisoned, True)
    poisoned = holder.get()
    poisoned.close()
    with allure.step("a device Task command succeeds on a fresh runtime"):
        receipt = device.accepted("task.create", new("task"), {"title": "Device task"})
        attach_json("receipt", receipt)
        check_equal("replaced", holder.get() is not poisoned, True)
    poisoned = holder.get()
    poisoned.close()
    with allure.step("a Review decide succeeds on a fresh runtime"):
        card = api.create("waiting card", state="waiting", waiting_for="Ann")
        synced.clock.advance(days=40)
        task = api.task(card["id"])
        poisoned = holder.get()
        poisoned.close()
        receipt = device.accepted(
            "review.decide",
            task["id"],
            {
                "decision_id": new("decision"),
                "type": "follow_up",
                "title": "Call Ann",
                "follow_up_task_id": new("task"),
            },
            checks=[("task", task["id"], task["revision"])],
        )
        created_task = receipt["result"]["created_task"]
        check_equal("follow-up", created_task["title"], "Call Ann")
        check_equal("replaced", holder.get() is not poisoned, True)


def test_026_FR_002_the_voice_proposal_check_uses_the_shared_runtime_holder(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production container's brain-dump port checks proposals on the holder.

    A poisoned holder must be replaced through the holder, and no second raw
    runtime may be built by the process-wide policy fallback.
    """

    container = api_client.app.state.container  # type: ignore[attr-defined]
    holder: RustCoreHolder = container.rust_core
    owner_id = api_client.get("/api/auth/me").json()["id"]
    port = container.voice_brain_dump_service.task_port
    holder_built: list[RustCore] = []
    policy_fallback_calls: list[None] = []
    real_factory = holder._factory
    real_shared = navigator.shared_policy_core

    def counting_factory() -> RustCore:
        core = real_factory()
        holder_built.append(core)
        return core

    def counting_shared() -> RustCore:
        policy_fallback_calls.append(None)
        return real_shared()

    monkeypatch.setattr(holder, "_factory", counting_factory)
    monkeypatch.setattr(navigator, "shared_policy_core", counting_shared)

    with allure.step("the shared holder's runtime is poisoned"):
        poisoned = holder.get()
        poisoned.close()
        check_equal("is_open", poisoned.is_open, False)
    with allure.step("a valid proposal passes the production brain-dump port"):
        created = port.create_native_inbox_task(
            owner_id=owner_id,
            title="Buy milk",
            source_capture_ids=["brain_dump:op-1:proposal-1"],
            idempotency_key="brain_dump_action:op-1:proposal-1",
        )
        attach_json("created task", {"id": created.id})
        check_equal("replaced through the holder", holder.get() is not poisoned, True)
    with allure.step("exactly one replacement runtime was built, by the holder"):
        check_equal("holder builds", len(holder_built), 1)
        check_equal("holder's runtime", holder.get() is holder_built[0], True)
    with allure.step("the process-wide policy fallback was never used"):
        check_equal("policy fallback calls", len(policy_fallback_calls), 0)
