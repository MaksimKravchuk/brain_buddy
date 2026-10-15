"""Test control clock and provider scripting on the frozen Python server (PR-07)."""

from __future__ import annotations

import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.providers.base import ProviderContext
from app.core import get_config
from app.core.test_clock import uninstall_clock_seam
from app.main import create_app

from .conftest import BrainBuddyTestClient

TOKEN = "tc-" + "x" * 29
HEADERS = {"X-Test-Control-Token": TOKEN}
BASE = "/api/__test__"
CONTEXT = ProviderContext(tree_id="t", node_id="n", prompt_version="v", chain_length=1)


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "https://bb.example.com")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_TEST_CONTROL_TOKEN", TOKEN)
    get_config.cache_clear()
    client = BrainBuddyTestClient(create_app())
    yield client
    client.close()
    uninstall_clock_seam()
    get_config.cache_clear()


def _container(client: TestClient) -> Any:
    return client.app.state.container  # type: ignore[attr-defined]


def test_027_fr_022_clock_moves_every_time_read_and_resets(
    control: TestClient,
) -> None:
    from app.services import auth_service

    pinned = control.post(
        f"{BASE}/clock", json={"set": "2031-01-02T03:04:05Z"}, headers=HEADERS
    )
    assert pinned.json() == {"mode": "pinned", "now": "2031-01-02T03:04:05Z"}
    control.post(f"{BASE}/clock", json={"advance_seconds": 90}, headers=HEADERS)
    container = _container(control)
    expected = "2031-01-02T03:05:35+00:00"
    assert auth_service.utcnow().isoformat() == expected
    assert container.task_service.clock().isoformat() == expected
    assert container.sync_retention._clock().isoformat() == expected
    back = control.delete(f"{BASE}/clock", headers=HEADERS)
    assert back.json()["mode"] == "wall"
    assert auth_service.utcnow().year != 2031


@pytest.mark.parametrize(
    "body", [{}, {"advance_seconds": 1, "set": "2031-01-02T03:04:05Z"}, {"set": "x"}]
)
def test_027_fr_022_clock_rejects_ambiguous_bodies(
    control: TestClient, body: dict[str, object]
) -> None:
    assert control.post(f"{BASE}/clock", json=body, headers=HEADERS).status_code == 422


def test_027_fr_011_held_call_blocks_until_released_and_ledger_has_no_content(
    control: TestClient,
) -> None:
    script = {"mode": "mock", "hold": True, "script": [{"confidence": 91}]}
    armed = control.put(f"{BASE}/providers/ai", json=script, headers=HEADERS)
    assert armed.status_code == 200
    provider = _container(control).validation_service.providers["mock"]
    results: list[int] = []
    worker = threading.Thread(
        target=lambda: results.append(
            provider.validate("SECRET-PROMPT", CONTEXT).confidence
        )
    )
    worker.start()
    calls: dict[str, Any] = {"count": 0}
    for _ in range(300):
        calls = control.get(f"{BASE}/providers/ai/calls", headers=HEADERS).json()
        if calls["count"]:
            break
        worker.join(0.01)
    assert calls["count"] == 1 and results == []
    assert set(calls["calls"][0]) == {"seq", "purpose", "owner_id", "correlation_id"}
    assert "SECRET-PROMPT" not in str(calls)
    released = control.post(
        f"{BASE}/providers/ai/release", json={"count": 1}, headers=HEADERS
    )
    assert released.json() == {"released": 1}
    worker.join(5)
    assert results == [91]


def test_027_fr_011_unscripted_kind_delegates_and_unknown_kind_is_404(
    control: TestClient,
) -> None:
    calls = control.get(f"{BASE}/providers/stt/calls", headers=HEADERS).json()
    assert calls == {"count": 0, "calls": []}
    assert control.get(f"{BASE}/mail", headers=HEADERS).json() == {"messages": []}
    unknown = control.put(
        f"{BASE}/providers/nope", json={"mode": "mock"}, headers=HEADERS
    )
    assert unknown.status_code == 404


def test_027_fr_022_provider_routes_need_the_token(control: TestClient) -> None:
    for method, path in (
        ("post", "/clock"),
        ("delete", "/clock"),
        ("put", "/providers/ai"),
        ("get", "/providers/ai/calls"),
        ("post", "/providers/ai/release"),
        ("get", "/mail"),
    ):
        assert getattr(control, method)(f"{BASE}{path}").status_code == 401


def _arm(client: TestClient, kind: str, script: list[dict[str, Any]]) -> None:
    body = {"mode": "mock", "script": script}
    resp = client.put(f"{BASE}/providers/{kind}", json=body, headers=HEADERS)
    assert resp.status_code == 200, resp.text


def test_027_fr_011_identity_proxy_scripts_tokens_notifications_and_errors(
    control: TestClient,
) -> None:
    from app.services.auth_provider_service import ProviderError

    gateway = _container(control).modern_auth_service.provider
    assert gateway.callback_uri  # unscripted attributes pass straight through
    _arm(
        control,
        "identity",
        [
            {"identity": {"subject": "s1", "email": "a@example.com"}},
            {"identity": {}, "issuing_client": "ios"},
            {"revoke": {}},
            {"notification": {"event_type": "account-delete"}},
            {"error": "invalid_proof"},
        ],
    )
    google = gateway.exchange_google(
        "c", redirect_uri="r", pkce_verifier="v", nonce="n"
    )
    assert google.identity.subject == "s1"
    assert google.identity.provider == "google"
    apple = gateway.exchange_apple("c", redirect_uri="r", nonce="n")
    assert apple.identity.provider == "apple" and apple.issuing_client == "ios"
    assert gateway.revoke_apple("tok") is None
    assert gateway.verify_notification("jws").event_type == "account-delete"
    with pytest.raises(ProviderError):
        gateway.exchange_google("c", redirect_uri="r", pkce_verifier="v", nonce="n")
    calls = control.get(f"{BASE}/providers/identity/calls", headers=HEADERS).json()
    assert [c["purpose"] for c in calls["calls"]][:2] == [
        "exchange_google",
        "exchange_apple",
    ]


def test_027_fr_011_unaddressed_revoke_never_consumes_an_exchange_item(
    control: TestClient,
) -> None:
    gateway = _container(control).modern_auth_service.provider
    _arm(control, "identity", [{"identity": {"subject": "s1"}}])
    assert gateway.revoke_apple("tok") is None  # background cleanup, any number
    assert gateway.revoke_apple("tok") is None
    apple = gateway.exchange_apple("c", redirect_uri="r", nonce="n")
    assert apple.identity.subject == "s1"


def test_027_fr_011_stt_proxy_scripts_text_and_failures(control: TestClient) -> None:
    from app.exceptions import ProviderRetryableError, ProviderTerminalError
    from app.workflows.voice_brain_dump.providers import AccurateSttRequest

    stt = _container(control).voice_brain_dump_service.accurate_stt
    assert isinstance(stt.provider_name, str)
    assert isinstance(stt.requires_external_processing, bool)
    _arm(
        control,
        "stt",
        [{"text": "buy milk"}, {"error": "retryable"}, {"error": "terminal"}],
    )
    request = AccurateSttRequest(operation_id="op", media_ref="m")
    assert stt.transcribe_sealed_audio(request).segments[0].text == "buy milk"
    with pytest.raises(ProviderRetryableError):
        stt.transcribe_sealed_audio(request)
    with pytest.raises(ProviderTerminalError):
        stt.transcribe_sealed_audio(request)


def test_027_fr_011_ai_proxy_scripted_failure_and_unscripted_delegation(
    control: TestClient,
) -> None:
    from app.exceptions import ProviderTerminalError

    provider = _container(control).validation_service.providers["mock"]
    assert provider.validate("p", CONTEXT).raw  # unarmed: the real mock answers
    _arm(control, "ai", [{"error": "terminal"}])
    with pytest.raises(ProviderTerminalError):
        provider.validate("p", CONTEXT)


def test_027_fr_011_smtp_capture_records_mail_and_scripted_failure(
    control: TestClient,
) -> None:
    from app.api.test_control_providers import ProviderControl, _smtp_capture

    smtp = ProviderControl("smtp")
    send = _smtp_capture(smtp)
    send("a@example.com", "123456", "login")
    assert smtp.mail == [
        {"recipient": "a@example.com", "purpose": "login", "code": "123456"}
    ]
    smtp.configure([{"error": True}], hold=False)
    with pytest.raises(RuntimeError):
        send("b@example.com", "1", "login")
    assert len(smtp.mail) == 1 and smtp.calls[0]["purpose"] == "login"
    wired = _container(control).modern_auth_service.mail is not None
    resp = control.put(f"{BASE}/providers/smtp", json={"mode": "mock"}, headers=HEADERS)
    assert resp.status_code == (200 if wired else 409)


def test_027_fr_011_rearming_without_hold_frees_waiters_and_release_is_bounded() -> (
    None
):
    from app.api.test_control_providers import ProviderControl

    control = ProviderControl("ai")
    control.configure([{}], hold=True)
    done: list[bool] = []
    worker = threading.Thread(
        target=lambda: done.append(control.enter("x") is not None)
    )
    worker.start()
    while not control.calls:
        worker.join(0.01)
    control.configure([], hold=False)
    worker.join(5)
    assert done == [True] and control.release(5) == 0
