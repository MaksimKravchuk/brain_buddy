"""T034: the ``voice_brain_dump`` server rollout flag gates the backend feature.

The native voice Brain Dump commands and provider discovery are exposed only
when the ADR-0008 rollout flag ``voice_brain_dump`` is effective for the caller:
OFF blocks everyone, INTERNAL allows only the allow-listed cohort, ON allows
every authenticated user. A blocked caller gets a fail-closed 404 (the feature
is simply not present for them), never a partial execution.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core.config import get_config
from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow

INTERNAL_EMAIL = "voice-cohort@example.com"
OUTSIDER_EMAIL = "voice-outsider@example.com"
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


def _signed_up_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    email: str,
    flags: str,
    internal_users: str | None = None,
) -> TestClient:
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
    invite_code = f"invite_{email.split('@', 1)[0]}"
    container.invite_repo.create(Invite(code=invite_code, created_at=utcnow()))
    client = TestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "invite_code": invite_code},
    )
    assert resp.status_code == 201, resp.text
    return client


def _start(client: TestClient):
    return client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "flag-start"},
        json=_CONSENT_BODY,
    )


def test_me_exposes_voice_brain_dump_flag_off_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cross-agent contract: the flag is visible (and false) on /auth/me."""

    client = _signed_up_client(tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="")
    body = client.get("/api/auth/me").json()
    assert body["feature_flags"]["voice_brain_dump"] is False


def test_off_blocks_start_command_for_everyone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _signed_up_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=off"
    )
    resp = _start(client)
    assert resp.status_code == 404, resp.text


def test_off_blocks_provider_discovery_for_everyone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _signed_up_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=off"
    )
    resp = client.get("/api/brain-dump-providers")
    assert resp.status_code == 404, resp.text


def test_off_blocks_gated_operation_command_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forward/new-capture action on the generic ``{action}`` route is closed
    when OFF (privacy controls -- withdraw/cancel/delete -- stay reachable and
    are covered separately)."""

    client = _signed_up_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=off"
    )
    resp = client.post(
        "/api/brain-dump-operations/does-not-exist/commit",
        headers={"Idempotency-Key": "flag-commit"},
        json={"expected_revision": 1},
    )
    assert resp.status_code == 404, resp.text
    # Fail closed on the flag, not because the operation is missing: the refusal
    # must not disclose whether the operation exists.
    assert "not available" in resp.text.lower()


def test_internal_allows_only_the_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _signed_up_client(
        tmp_path,
        monkeypatch,
        email=INTERNAL_EMAIL,
        flags="voice_brain_dump=internal",
        internal_users=INTERNAL_EMAIL,
    )
    assert client.get("/api/brain-dump-providers").status_code == 200
    assert _start(client).status_code == 201


def test_internal_blocks_non_cohort_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _signed_up_client(
        tmp_path,
        monkeypatch,
        email=OUTSIDER_EMAIL,
        flags="voice_brain_dump=internal",
        internal_users=INTERNAL_EMAIL,
    )
    assert client.get("/api/brain-dump-providers").status_code == 404
    assert _start(client).status_code == 404


def test_on_allows_every_authenticated_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _signed_up_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=on"
    )
    assert client.get("/api/brain-dump-providers").status_code == 200
    assert _start(client).status_code == 201


def test_flag_gate_still_requires_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unauthenticated caller is rejected as 401 before the flag is consulted."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", "voice_brain_dump=off")
    get_config.cache_clear()  # type: ignore[attr-defined]
    app = create_app()
    client = TestClient(app)
    assert client.get("/api/brain-dump-providers").status_code == 401
