"""Test control: clock and mock-provider scripting (spec 027 PR-07).

Extends ``app.api.test_control`` (same prefix, same ``X-Test-Control-Token``
gate, mounted only when ``BRAIN_BUDDY_ENV=test``). Provider kinds are ``ai``,
``stt``, ``identity`` and ``smtp``. Until a ``PUT /providers/{kind}`` arms a
kind, its original adapter runs (SMTP never leaves the process). The call
ledger records count, purpose, owner id and correlation id, never content.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.providers.base import ProviderResult
from app.api.test_control import TEST_CONTROL_PREFIX, require_test_control_token
from app.container import Container
from app.core.config import AppConfig, AppEnvironment
from app.core.logging import get_correlation_id
from app.core.test_clock import CLOCK, TestClock, install_clock_seam
from app.exceptions import NotFoundError, ProviderRetryableError, ProviderTerminalError
from app.services.auth_provider_service import (
    AppleNotification,
    ProviderError,
    ProviderIdentity,
    ProviderTokens,
)
from app.workflows.voice_brain_dump.providers import DeterministicAccurateStt

KINDS = ("ai", "stt", "identity", "smtp")
HOLD_TIMEOUT_SECONDS = 60.0


class ProviderControl:
    """Script, hold gate and content-free call ledger for one provider kind."""

    def __init__(self, kind: str, available: bool = True) -> None:
        self.kind = kind
        self.available = available
        self.armed = False
        self.hold = False
        self.script: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.mail: list[dict[str, str]] = []
        self._cond = threading.Condition()
        self._tickets = 0
        self._released = 0

    def configure(self, script: list[dict[str, Any]], hold: bool) -> None:
        with self._cond:
            self.armed = True
            self.script = list(script)
            self.hold = hold
            self.calls = []
            if not hold:  # idempotent: re-arming without hold frees waiters
                self._released = self._tickets
            self._cond.notify_all()

    def release(self, count: int) -> int:
        with self._cond:
            freed = min(count, self._tickets - self._released)
            self._released += freed
            self._cond.notify_all()
            return freed

    def enter(self, purpose: str) -> dict[str, Any] | None:
        """Record a call; block while held; return the scripted item or None."""

        with self._cond:
            self.calls.append(
                {
                    "seq": len(self.calls) + 1,
                    "purpose": purpose,
                    "owner_id": None,
                    "correlation_id": get_correlation_id(),
                }
            )
            if not self.armed:
                return None
            item = self.script.pop(0) if self.script else {}
            if self.hold:
                ticket = self._tickets
                self._tickets += 1
                deadline = time.monotonic() + HOLD_TIMEOUT_SECONDS
                while self._released <= ticket:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise ProviderTerminalError("TEST_CONTROL_HOLD_TIMEOUT")
                    self._cond.wait(left)
            return item


def _failure(item: dict[str, Any]) -> None:
    error = item.get("error")
    if error == "retryable":
        raise ProviderRetryableError("Scripted retryable provider failure.")
    if error:
        raise ProviderTerminalError("Scripted terminal provider failure.")


class _AiProxy:
    def __init__(self, control: ProviderControl, original: Any) -> None:
        self._control, self._original = control, original
        self.provider_id = original.provider_id

    def validate(self, prompt: str, context: Any, *, config: Any = None) -> Any:
        item = self._control.enter("validation")
        if item is None:
            return self._original.validate(prompt, context, config=config)
        _failure(item)
        return ProviderResult(
            confidence=int(item.get("confidence", 50)),
            verdict=str(item.get("verdict", "ok")),
            observations=list(item.get("observations", [])),
            suggested_questions=list(item.get("suggested_questions", [])),
            raw={"scripted": True},
        )


class _SttProxy:
    def __init__(self, control: ProviderControl, original: Any) -> None:
        self._control, self._original = control, original

    @property
    def provider_name(self) -> str:
        return str(self._original.provider_name)

    @property
    def requires_external_processing(self) -> bool:
        return bool(self._original.requires_external_processing)

    def transcribe_sealed_audio(self, request: Any) -> Any:
        item = self._control.enter("accurate_stt")
        if item is None:
            return self._original.transcribe_sealed_audio(request)
        _failure(item)
        text = str(item.get("text", "scripted transcript"))
        return DeterministicAccurateStt(
            {request.media_ref: text}
        ).transcribe_sealed_audio(request)


def _identity_result(name: str, item: dict[str, Any]) -> Any:
    if name == "revoke_apple":
        return None
    now = int(time.time())
    if name == "verify_notification":
        fields = {
            "jti": "scripted-jti",
            "event_type": "consent-revoked",
            "subject": "scripted-subject",
            "audience": "test",
            "issued_at": now,
            "event_time": now,
        }
        return AppleNotification(**{**fields, **item.get("notification", {})})
    provider = "google" if name == "exchange_google" else "apple"
    fields = {
        "provider": provider,
        "issuer": f"https://scripted.{provider}.test",
        "subject": "scripted-subject",
        "email": None,
        "email_authoritative": False,
        "is_private_email": False,
        "audience": "test",
        "issued_at": now,
    }
    identity = ProviderIdentity(**{**fields, **item.get("identity", {})})
    return ProviderTokens(identity, str(item.get("issuing_client", "test-client")))


class _IdentityProxy:
    _SCRIPTED = ("exchange_google", "exchange_apple", "revoke_apple")

    def __init__(self, control: ProviderControl, original: Any) -> None:
        self._control, self._original = control, original

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._original, name)
        if name not in (*self._SCRIPTED, "verify_notification"):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            item = self._control.enter(name)
            if item is None:
                return target(*args, **kwargs)
            if item.get("error"):
                raise ProviderError(item["error"])
            return _identity_result(name, item)

        return call


def _smtp_capture(control: ProviderControl) -> Callable[[str, str, str], None]:
    def send(recipient: str, code: str, purpose: str) -> None:
        item = control.enter(purpose) or {}
        if item.get("error"):
            raise RuntimeError("scripted smtp failure")
        control.mail.append({"recipient": recipient, "purpose": purpose, "code": code})

    return send


def _install_providers(container: Container) -> dict[str, ProviderControl]:
    controls = {kind: ProviderControl(kind) for kind in KINDS}
    validation = container.validation_service
    validation.providers = {
        key: _AiProxy(controls["ai"], value)
        for key, value in validation.providers.items()
    }
    voice: Any = container.voice_brain_dump_service
    voice.accurate_stt = _SttProxy(controls["stt"], voice.accurate_stt)
    auth: Any = container.modern_auth_service
    auth.provider = _IdentityProxy(controls["identity"], auth.provider)
    if auth.apple is not None:
        auth.apple.gateway = auth.provider
    if auth.mail is None:
        controls["smtp"].available = False
    else:
        auth.mail._send = _smtp_capture(controls["smtp"])
    return controls


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClockRequest(_Body):
    advance_seconds: float | None = Field(default=None, ge=0, le=10**9)
    set: datetime | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> ClockRequest:
        if (self.advance_seconds is None) == (self.set is None):
            raise ValueError("Send exactly one of advance_seconds or set.")
        if self.set is not None and self.set.tzinfo is None:
            raise ValueError("set must be an RFC3339 instant with an offset.")
        return self


class ProviderRequest(_Body):
    mode: Literal["mock"]
    script: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    hold: bool = False


class ReleaseRequest(_Body):
    count: int = Field(default=1, ge=1, le=10_000)


router = APIRouter(
    prefix=TEST_CONTROL_PREFIX,
    tags=["test-control"],
    dependencies=[Depends(require_test_control_token)],
)


def _control(request: Request, kind: str) -> ProviderControl:
    control: ProviderControl | None = request.app.state.test_providers.get(kind)
    if control is None:
        raise NotFoundError("provider", kind)
    return control


@router.post("/clock")
def move_clock(body: ClockRequest) -> dict[str, str]:
    if body.set is not None:
        CLOCK.set(body.set)
    else:
        CLOCK.advance(body.advance_seconds or 0.0)
    return CLOCK.describe()


@router.delete("/clock")
def reset_clock() -> dict[str, str]:
    CLOCK.reset()
    return CLOCK.describe()


@router.put("/providers/{kind}")
def script_provider(
    kind: str, body: ProviderRequest, request: Request
) -> dict[str, object]:
    control = _control(request, kind)
    if not control.available:
        raise HTTPException(status_code=409, detail=f"Provider '{kind}' is not wired.")
    control.configure(body.script, body.hold)
    return {
        "kind": kind,
        "mode": body.mode,
        "script": len(body.script),
        "hold": body.hold,
    }


@router.get("/providers/{kind}/calls")
def provider_calls(kind: str, request: Request) -> dict[str, object]:
    calls = list(_control(request, kind).calls)
    return {"count": len(calls), "calls": calls}


@router.post("/providers/{kind}/release")
def release_provider(
    kind: str, body: ReleaseRequest, request: Request
) -> dict[str, int]:
    return {"released": _control(request, kind).release(body.count)}


@router.get("/mail")
def captured_mail(request: Request) -> dict[str, list[dict[str, str]]]:
    return {"messages": list(request.app.state.test_providers["smtp"].mail)}


def install_test_control_providers(app: FastAPI, config: AppConfig) -> TestClock | None:
    """Wire the clock seam and provider doubles; test environment with token only."""

    if config.environment is not AppEnvironment.TEST or not config.test_control_token:
        return None
    container: Container = app.state.container
    app.state.test_providers = container.test_control = _install_providers(container)
    clock = install_clock_seam(container)
    app.include_router(router, prefix=config.api_prefix)
    return clock
