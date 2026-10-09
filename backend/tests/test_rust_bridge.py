"""Boundary checks for the PyO3 core bridge (spec 026, T004).

The Rust side proves panic containment and state transitions in
``rust/bindings/python`` (``cargo test -p bb-python bridge``); these tests prove
what only Python can see: typed conversion, error translation without payload
text, and handle lifetimes across repeated open/close and threads.
"""

from __future__ import annotations

import json
import re
import threading
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import allure
import bb_core
import pytest

from app.exceptions import ValidationFailure
from app.modules.tasks.rust_adapter import (
    PROTOCOL_VERSION,
    RustBridgeError,
    RustCore,
    translate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET = "Buy-milk-secret-title"
COMMAND_ID = "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11"
COMMAND: dict[str, Any] = {
    "protocol_version": 1,
    "command_id": COMMAND_ID,
    "scope_id": "scope-1",
    "device_id": "device-1",
    "device_epoch": "epoch-1",
    "local_sequence": "9007199254740993",
    "type": "task.create",
    "command_version": 1,
    "entity_id": "task-1",
    "preconditions": [],
    "depends_on": [],
    "issued_at": "2026-10-09T12:00:00Z",
    "payload": {"title": SECRET, "notes": None},
}


def _wire(**overrides: Any) -> bytes:
    return json.dumps({**COMMAND, **overrides}).encode()


@pytest.fixture
def core() -> Iterator[RustCore]:
    with RustCore() as runtime:
        yield runtime


def test_026_FR_002_decoded_command_crosses_as_owned_typed_values(
    core: RustCore,
) -> None:
    """A command decodes to Python-owned values with decimal counters intact."""
    decoded = core.decode_command(_wire())
    assert (decoded.command_id, decoded.scope_id, decoded.device_id) == (
        COMMAND_ID,
        "scope-1",
        "device-1",
    )
    assert (decoded.command_type, decoded.command_version) == ("task.create", 1)
    assert decoded.local_sequence == "9007199254740993"
    assert decoded.executable is True
    assert decoded.unsupported_reason is None
    assert decoded.protocol_version == PROTOCOL_VERSION


def test_026_FR_002_wire_form_keeps_omitted_and_null_fields(core: RustCore) -> None:
    """The stable wire form preserves nulls and leaves omitted fields omitted."""
    decoded = core.decode_command(_wire())
    wire = json.loads(decoded.wire)
    assert "supersedes_command_id" not in wire
    assert wire["payload"] == COMMAND["payload"]
    assert wire["local_sequence"] == "9007199254740993"


def test_026_FR_012_unsupported_command_is_returned_not_rejected(
    core: RustCore,
) -> None:
    """An unknown command type is kept in stable form instead of raising."""
    decoded = core.decode_command(_wire(type="task.from_the_future"))
    assert decoded.executable is False
    assert decoded.unsupported_reason == "command_type"
    assert json.loads(decoded.wire)["type"] == "task.from_the_future"

    newer = core.decode_command(_wire(protocol_version=2))
    assert (newer.executable, newer.unsupported_reason) == (False, "protocol_version")


def test_026_FR_005_duplicate_keys_are_rejected(core: RustCore) -> None:
    """A repeated JSON key is a validation failure, never last-one-wins."""
    wire = b'{"command_id": "a", "command_id": "b"}'
    with pytest.raises(ValidationFailure) as caught:
        core.decode_command(wire)
    assert caught.value.detail == {"code": "INVALID_REQUEST", "field": None}


@pytest.mark.parametrize(
    "wire",
    [
        b'{"title": "' + SECRET.encode() + b'"',
        b"\xff\xfe" + SECRET.encode(),
        _wire(command_id=SECRET),
        _wire(extra=SECRET),
    ],
    ids=["truncated-json", "invalid-utf8", "bad-command-id", "unknown-field"],
)
def test_026_FR_022_codec_errors_are_typed_without_payload_text(
    core: RustCore, wire: bytes
) -> None:
    """Codec failures carry a stable code and rule name, never input text."""
    with pytest.raises(ValidationFailure) as caught:
        core.decode_command(wire)
    error = caught.value
    assert error.detail["code"] == "INVALID_REQUEST"
    for rendering in (str(error), repr(error), json.dumps(error.detail)):
        assert SECRET not in rendering
    assert error.__cause__ is None


def test_026_FR_022_runtime_errors_become_rust_bridge_error() -> None:
    """Non-input bridge codes keep code, retryability and field, and no payload."""
    error = translate(bb_core.BridgeError("STORE_BUSY", True, "scope"))
    assert isinstance(error, RustBridgeError)
    assert (error.code, error.retryable, error.field) == ("STORE_BUSY", True, "scope")
    assert str(error) == "The Rust core is unavailable (STORE_BUSY)."


def test_026_FR_012_unsupported_protocol_version_refuses_to_open() -> None:
    """A runtime for an unsupported protocol version is a typed refusal."""
    with pytest.raises(RustBridgeError) as caught:
        RustCore(PROTOCOL_VERSION + 1)
    assert (caught.value.code, caught.value.field) == (
        "UPGRADE_REQUIRED",
        "protocol_version",
    )


def test_026_FR_002_repeated_open_close_is_idempotent_and_final() -> None:
    """Fifty open/close cycles: close is idempotent and later calls fail typed."""
    for _ in range(50):
        runtime = RustCore()
        assert runtime.is_open
        assert runtime.decode_command(_wire()).executable
        runtime.close()
        runtime.close()
        assert not runtime.is_open
        with pytest.raises(RustBridgeError) as caught:
            runtime.decode_command(_wire())
        assert caught.value.code == "WORKSPACE_CLOSED"
        assert caught.value.retryable is False


def test_026_FR_002_context_manager_closes_on_error() -> None:
    """Leaving the context closes the runtime even when the body raised."""
    runtime = RustCore()
    with pytest.raises(RuntimeError), runtime:
        raise RuntimeError("boom")
    assert not runtime.is_open


def test_026_FR_002_concurrent_calls_share_one_runtime(core: RustCore) -> None:
    """Calls from several threads complete and agree while the GIL is released."""
    wire = _wire()
    results: list[str] = []
    failures: list[BaseException] = []

    def work() -> None:
        try:
            results.extend(core.decode_command(wire).command_id for _ in range(200))
        except BaseException as error:  # noqa: BLE001 - surfaced by the assert
            failures.append(error)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not failures
    assert results == [COMMAND_ID] * 800


def test_026_FR_002_close_during_concurrent_calls_fails_typed() -> None:
    """A close racing live calls yields results or typed closed/cancelled errors."""
    runtime = RustCore()
    wire = _wire()
    outcomes: list[str] = []

    def work() -> None:
        for _ in range(500):
            try:
                runtime.decode_command(wire)
                outcomes.append("ok")
            except RustBridgeError as error:
                outcomes.append(error.code)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    runtime.close()
    for thread in threads:
        thread.join()
    assert set(outcomes) <= {"ok", "WORKSPACE_CLOSED", "CANCELLED"}
    assert len(outcomes) == 2000


def test_026_FR_002_one_rust_toolchain_pin_builds_every_wheel() -> None:
    """CI, the image build and the Rust workspace pin the same toolchain."""
    toolchain_file = REPO_ROOT / "rust" / "rust-toolchain.toml"
    if not toolchain_file.is_file():
        pytest.skip("repository root not available (backend-only checkout)")
    pinned = tomllib.loads(toolchain_file.read_text())["toolchain"]["channel"]

    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text()
    assert set(re.findall(r"rust:([\d.]+)-slim", dockerfile)) == {pinned}
    assert f"RUSTUP_TOOLCHAIN={pinned}" in dockerfile

    for name in ("ci.yml", "mutation-quality.yml"):
        workflow = (REPO_ROOT / ".github" / "workflows" / name).read_text()
        versions = set(re.findall(r"toolchain: ([\d.]+)", workflow))
        assert versions == {pinned}, name


QUERY_INPUTS: dict[str, Any] = {
    "now": "2026-10-09T12:00:00Z",
    "device_zone": "UTC",
    "policy": {
        "weekly_review": False,
        "navigator_provider": None,
        "navigator_available": False,
        "consent_text_version": 1,
    },
}


def _evidence(name: str, content: object) -> None:
    allure.attach(
        content if isinstance(content, str) else json.dumps(content, indent=2),
        name=name,
        attachment_type=allure.attachment_type.TEXT,
    )


def test_026_FR_002_a_typed_query_is_answered_with_plain_values(
    core: RustCore,
) -> None:
    """An answered query returns the result as plain JSON values."""
    with allure.step("ask for the tags of an empty read set"):
        result = core.query({}, {"kind": "tags"}, QUERY_INPUTS)
        _evidence("result", result)
    with allure.step("the answer is the typed result, not a wrapper"):
        assert result == {"kind": "tags", "value": []}
        _evidence("kind", result["kind"])


def test_026_FR_002_a_refused_query_is_a_validation_failure_with_a_reason_code(
    core: RustCore,
) -> None:
    """A refused query raises with the stable reason code and no input text."""
    missing = "task_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11"
    with allure.step("ask for a task the read set does not hold"):
        with pytest.raises(ValidationFailure) as refused:
            core.query({}, {"kind": "task_detail", "task_id": missing}, QUERY_INPUTS)
        _evidence("detail", refused.value.detail)
    with allure.step("the refusal names its reason, never the asked-for id"):
        assert refused.value.detail == {"reason": "not_found"}
        assert missing not in str(refused.value) + repr(refused.value.detail)
        _evidence("reason", refused.value.detail["reason"])
