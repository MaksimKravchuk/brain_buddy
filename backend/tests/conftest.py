"""Common pytest fixtures for backend tests."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.container import Container, build_container
from app.core import get_config
from app.core.rate_limit import login_rate_limiter, sensitive_action_rate_limiter
from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow

from .allure_taxonomy import resolve

# --- Hermetic voice-provider environment ------------------------------------
# ``app.core.config`` calls ``load_dotenv()`` at import, so a developer's
# repo-root ``.env`` (e.g. ``BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER=deepgram``
# plus real ``OPENAI_API_KEY``/``DEEPGRAM_API_KEY`` credentials) would leak into
# the pytest process. That flips the TEST-env deterministic providers into
# ``Disabled*``/real adapters and breaks the deterministic suite. Scrub every
# voice provider selector and external credential once, at conftest import,
# before any app config is built -- so the suite is hermetic regardless of a
# developer's local ``.env``. Tests that intentionally exercise a specific
# provider set it via ``monkeypatch`` (function-scoped, applied after this
# module-level scrub) and keep working.
_LEAKY_VOICE_ENV_PREFIX = "BRAIN_BUDDY_VOICE_"
_LEAKY_VOICE_ENV_NAMES = ("OPENAI_API_KEY", "DEEPGRAM_API_KEY")


def _scrub_leaky_voice_env() -> None:
    for name in list(os.environ):
        if name.startswith(_LEAKY_VOICE_ENV_PREFIX) or name in _LEAKY_VOICE_ENV_NAMES:
            del os.environ[name]


_scrub_leaky_voice_env()

# --- Voice Brain Dump rollout flag default (T034) ---------------------------
# The native voice Brain Dump feature ships behind a server-owned, default-OFF
# rollout flag (``voice_brain_dump``, ADR-0008). The backend suite predates the
# flag and drives the brain-dump routes directly, so the whole TEST process
# defaults the flag ON -- overriding any developer ``.env`` for hermeticity, in
# the same spirit as the voice-provider scrub above. The handful of tests that
# specifically exercise the OFF/INTERNAL gate build their own app with a
# monkeypatched ``BRAIN_BUDDY_FEATURE_FLAGS`` (function-scoped, applied after
# this module-level default), so this default never masks the gate itself.
os.environ["BRAIN_BUDDY_FEATURE_FLAGS"] = "voice_brain_dump=on"
os.environ.pop("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", None)

TEST_OWNER_ID = "user_test_owner"
TEST_USER_EMAIL = "primary@example.com"
TEST_USER_PASSWORD = "correct-horse-battery-staple"
SECOND_USER_EMAIL = "secondary@example.com"
SECOND_USER_PASSWORD = "another-horse-battery-staple"


class BrainBuddyTestClient(TestClient):
    """Declare the deterministic text-audio fixture MIME on test uploads."""

    def put(self, url: str, **kwargs: Any):  # type: ignore[no-untyped-def, override]
        if "/brain-dump-operations/" in url and "/audio/" in url:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("Content-Type", "audio/x-brain-buddy-test-text")
            kwargs["headers"] = headers
        return super().put(url, **kwargs)


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter() -> Generator[None, None, None]:
    """Ensure the in-memory rate limiters don't bleed across tests."""

    login_rate_limiter.reset()
    sensitive_action_rate_limiter.reset()
    yield
    login_rate_limiter.reset()
    sensitive_action_rate_limiter.reset()


def _declared_label_types(item: pytest.Item) -> set[str]:
    """Label types (epic/feature/story) a test already set via decorators."""

    declared: set[str] = set()
    for marker in item.iter_markers(name="allure_label"):
        label_type = marker.kwargs.get("label_type")
        if isinstance(label_type, str):
            declared.add(label_type)
    return declared


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, None, None]:
    """Apply the deterministic Allure taxonomy to every backend test.

    Runs in the *call* phase so the dynamic title and the wrapping step attach to
    the test result itself (labels applied during fixture setup stick, but the
    result name and steps must be set while the test body executes). epic/feature/
    story are filled from the module map unless the test declared its own; the
    title is humanised from the docstring/name unless a ``@allure.title`` is
    present; and the body is wrapped in one named step so every emitted result
    satisfies the taxonomy gate. Explicit decorators always win — this only fills
    what a test did not set for itself.
    """

    func = getattr(item, "function", None)
    if func is None:  # non-python item; nothing to tag
        yield
        return

    param_id = getattr(getattr(item, "callspec", None), "id", None)
    meta = resolve(
        module_name=item.module.__name__,
        function_name=getattr(item, "originalname", None) or item.name,
        docstring=getattr(func, "__doc__", None),
        param_id=param_id,
    )

    declared = _declared_label_types(item)
    if "epic" not in declared:
        allure.dynamic.epic(meta.epic)
    if "feature" not in declared:
        allure.dynamic.feature(meta.feature)
    if "story" not in declared:
        allure.dynamic.story(meta.story)
    if not getattr(func, "__allure_display_name__", None):
        allure.dynamic.title(meta.title)

    with allure.step(meta.step):
        allure.attach(
            f"Taxonomy evidence for: {meta.title}",
            name="Taxonomy evidence",
            attachment_type=allure.attachment_type.TEXT,
        )
        yield


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def container(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Container, None, None]:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    config = get_config()
    yield build_container(config)
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)


@pytest.fixture
def tree_service(container: Container):
    return container.tree_service


@pytest.fixture
def node_service(container: Container):
    return container.node_service


@pytest.fixture
def relation_service(container: Container):
    return container.relation_service


@pytest.fixture
def version_service(container: Container):
    return container.version_service


@pytest.fixture
def validation_service(container: Container):
    return container.validation_service


def _allow_openai_voice_consent(container: Container) -> None:
    """Grant the 'openai' voice-provider consent category in test containers.

    Production ``build_container`` derives this allowlist from the configured
    provider settings. Tests default both voice providers to
    disabled/deterministic and instead swap in fake or real-shaped adapters
    directly on ``voice_brain_dump_service``, so they grant the "openai"
    category explicitly here to exercise consent-bound flows against those
    swapped-in adapters -- decoupling the fixtures from container-derivation
    internals.
    """

    container.voice_brain_dump_service.allowed_external_provider_categories = frozenset(
        {"openai"}
    )


def _build_authenticated_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    subdir: str,
    email: str,
    password: str,
) -> tuple[TestClient, dict[str, str]]:
    data_root = tmp_path / subdir
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    container: Container = app.state.container
    _allow_openai_voice_consent(container)

    invite_code = f"invite_{subdir}"
    container.invite_repo.create(Invite(code=invite_code, created_at=utcnow()))

    client = BrainBuddyTestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
            "invite_code": invite_code,
        },
    )
    if resp.status_code != 201:
        raise RuntimeError(f"Test signup failed ({resp.status_code}): {resp.text}")
    return client, resp.json()


@pytest.fixture
def api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    """A TestClient that is already signed in as the primary test user."""

    client, _ = _build_authenticated_client(
        tmp_path,
        monkeypatch,
        subdir="api-data",
        email=TEST_USER_EMAIL,
        password=TEST_USER_PASSWORD,
    )
    yield client
    client.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)


@pytest.fixture
def second_api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, TestClient], None, None]:
    """Two signed-in clients sharing the same backend, for isolation tests."""

    data_root = tmp_path / "shared-data"
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    container: Container = app.state.container
    _allow_openai_voice_consent(container)

    # Mint two invites up-front so both users can sign up in the same app.
    first_code = "invite_first"
    second_code = "invite_second"
    container.invite_repo.create(Invite(code=first_code, created_at=utcnow()))
    container.invite_repo.create(Invite(code=second_code, created_at=utcnow()))

    client_a = BrainBuddyTestClient(app)
    resp_a = client_a.post(
        "/api/auth/signup",
        json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD,
            "invite_code": first_code,
        },
    )
    assert resp_a.status_code == 201, resp_a.text

    client_b = BrainBuddyTestClient(app)
    resp_b = client_b.post(
        "/api/auth/signup",
        json={
            "email": SECOND_USER_EMAIL,
            "password": SECOND_USER_PASSWORD,
            "invite_code": second_code,
        },
    )
    assert resp_b.status_code == 201, resp_b.text

    yield client_a, client_b
    client_a.close()
    client_b.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)


@pytest.fixture
def anonymous_api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    """A TestClient with no active session — used for auth gate tests."""

    data_root = tmp_path / "anon-data"
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    client = BrainBuddyTestClient(app)
    yield client
    client.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)
