"""Auth request targets remain secret-free at each server logging edge."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import CorrelationIdMiddleware
from app.core.config import AppConfig
from app.core.logging import (
    CorrelationIdFilter,
    PushCallbackAccessFilter,
    build_logging_dict,
    reset_correlation_id,
    sanitize_log_path,
    set_correlation_id,
)


@pytest.mark.parametrize(
    "target,expected,prefix",
    [
        (
            "/api/auth/providers/google/callback?code=synthetic-code&state=synthetic-state#grant=synthetic-grant",
            "/api/auth/providers/google/callback",
            "/api",
        ),
        (
            "/api/auth/providers/apple/callback?email=person@example.com&id_token=synthetic-token",
            "/api/auth/providers/apple/callback",
            "/api",
        ),
        (
            "/api/auth/email/request?email=person@example.com&code=123456",
            "/api/auth/email/request",
            "/api",
        ),
        (
            "/api/account/auth-export?proof=synthetic-proof",
            "/api/account/auth-export",
            "/api",
        ),
        (
            "/auth/complete#attempt=attempt&state=synthetic-state&grant=synthetic-grant",
            "/auth/complete",
            "/api",
        ),
        (
            "brainbuddy://auth/callback?grant=synthetic-grant#token=synthetic-token",
            "brainbuddy://auth/callback",
            "/api",
        ),
        (
            "/settings/account/delete?email=person@example.com#grant=synthetic-grant",
            "/settings/account/delete",
            "/api",
        ),
        (
            "/api/%61uth/providers/google/callback%3Fcode%3Dsynthetic-code",
            "/api/auth/providers/google/callback",
            "/api",
        ),
        (
            "/api/%2561uth/providers/google/callback?code=synthetic-code",
            "/api/auth/providers/google/callback",
            "/api",
        ),
        (
            "/api/%25252561uth/providers/google/callback?code=synthetic-code",
            "[redacted]",
            "/api",
        ),
        (
            "/api/auth/providers/google/callback%253Fcode%253Dsynthetic-code",
            "/api/auth/providers/google/callback",
            "/api",
        ),
        (
            "/api//auth/providers/google/callback?code=synthetic-code",
            "/api/auth/providers/google/callback",
            "/api",
        ),
        (
            "/api/other/../auth/providers/google/callback?code=synthetic-code",
            "/api/auth/providers/google/callback",
            "/api",
        ),
        (
            "https://person:synthetic-password@api.example.com/api/auth/providers/google/callback?code=synthetic-code",
            "/api/auth/providers/google/callback",
            "/api",
        ),
        (
            "/custom/v2/auth/providers/google/callback?code=synthetic-code",
            "/custom/v2/auth/providers/google/callback",
            "/custom/v2",
        ),
        ("/api/tasks?cursor=ordinary", "/api/tasks?cursor=ordinary", "/api"),
        (
            "/api/tasks/name%20with%20spaces?cursor=ordinary",
            "/api/tasks/name%20with%20spaces?cursor=ordinary",
            "/api",
        ),
        ("/api/accounting?cursor=ordinary", "/api/accounting?cursor=ordinary", "/api"),
        (
            "/api/a2a/push/run-1/synthetic-token?code=synthetic-code",
            "/api/a2a/push/run-1/[redacted]",
            "/api",
        ),
    ],
)
def test_022_FR_021_sensitive_request_targets_remove_query_and_fragment(
    target: str, expected: str, prefix: str
) -> None:
    """Auth targets hide proofs and personal query input while unrelated URLs keep their meaning."""
    assert sanitize_log_path(target, api_prefix=prefix) == expected


@pytest.mark.parametrize(
    "target",
    [
        None,
        123,
        b"/api/auth?code=synthetic-code",
        "/api/auth/callback\ncode=synthetic-code",
        "https://[bad/api/auth?code=synthetic-code",
    ],
)
def test_022_FR_021_malformed_targets_are_total_and_fail_closed(target: Any) -> None:
    """Malformed targets never raise or print attacker-controlled credentials."""
    assert sanitize_log_path(target, api_prefix="/api") == "[redacted]"


def record(
    message: str, args: Any, *, name: str = "uvicorn.access"
) -> logging.LogRecord:
    event = logging.LogRecord(name, logging.DEBUG, __file__, 1, message, (), None)
    event.args = args
    return event


def test_022_FR_021_uvicorn_access_preserves_status_and_correlation_without_auth_proofs() -> (
    None
):
    """The actual uvicorn record shape retains method, path, status and correlation metadata."""
    event = record(
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:1",
            "GET",
            "/api/auth/providers/google/callback?code=synthetic-code&state=synthetic-state",
            "1.1",
            303,
        ),
    )
    binding = set_correlation_id("90bd7172-350e-4c98-b72d-1680f14db84a")
    try:
        assert CorrelationIdFilter().filter(event)
        assert PushCallbackAccessFilter(api_prefix="/api").filter(event)
        rendered = logging.Formatter("%(correlation_id)s %(message)s").format(event)
    finally:
        reset_correlation_id(binding)
    assert "synthetic" not in rendered
    assert "GET /api/auth/providers/google/callback HTTP/1.1" in rendered
    assert "303" in rendered
    assert "90bd7172-350e-4c98-b72d-1680f14db84a" in rendered


@pytest.mark.parametrize(
    "args",
    [
        None,
        (),
        ("synthetic-code",),
        {"request": "/api/auth?code=synthetic-code"},
        ("127.0.0.1:1", "GET", 123, "1.1", 200),
        ("127.0.0.1:1", "GET", "/api/tasks", "1.1", 200, "synthetic-code"),
    ],
)
def test_022_FR_021_unknown_uvicorn_shapes_redact_instead_of_allowing_raw_payload(
    args: Any,
) -> None:
    """An unknown access format cannot bypass redaction or break message formatting."""
    event = record("Unknown request contains synthetic-code %s", args)
    event.color_message = "synthetic-code"
    event.exc_text = "synthetic-code"
    event.stack_info = "synthetic-code"
    assert PushCallbackAccessFilter(api_prefix="/api").filter(event)
    assert "synthetic-code" not in logging.Formatter("%(message)s").format(event)
    assert "color_message" not in event.__dict__


def test_022_FR_021_auth_exception_text_cannot_leak_at_application_or_uvicorn_edge() -> (
    None
):
    """Auth failure records retain coarse outcomes and discard secret-bearing traceback text."""
    try:
        raise RuntimeError("synthetic-code person@example.com")
    except RuntimeError as error:
        exception = (type(error), error, error.__traceback__)
    application = record(
        "api_request_failed method=%s path=%s duration_ms=%.1f",
        ("POST", "/api/auth/providers/apple/callback?code=synthetic-code", 2.0),
        name="app.api.middleware",
    )
    uvicorn = record("Exception in ASGI application", (), name="uvicorn.error")
    for event in (application, uvicorn):
        event.exc_info = exception
        assert PushCallbackAccessFilter(api_prefix="/api").filter(event)
        rendered = logging.Formatter("%(message)s").format(event)
        assert "synthetic-code" not in rendered
        assert "person@example.com" not in rendered
    assert "api_request_failed" in application.getMessage()


def test_022_FR_021_unknown_uvicorn_error_message_without_args_is_redacted() -> None:
    """An unfamiliar server diagnostic cannot print a literal callback credential."""
    event = record(
        "Unknown error /api/auth?code=synthetic-code", (), name="uvicorn.error"
    )
    assert PushCallbackAccessFilter(api_prefix="/api").filter(event)
    assert "synthetic-code" not in event.getMessage()


@pytest.mark.parametrize(
    "message,args",
    [
        ("api_request synthetic-code %s %s %s", ("GET", "/api/auth", 1.0)),
        (
            "api_request method=%s path=%s status=%s duration_ms=%.1f",
            ("synthetic-code", "/api/auth", 200, 1.0),
        ),
        (
            "api_request method=%s path=%s status=%s duration_ms=%.1f",
            ("GET", "/api/auth", "synthetic-code", 1.0),
        ),
        (
            "api_request_failed method=%s path=%s duration_ms=%.1f",
            ("GET", "/api/auth", "synthetic-code"),
        ),
        ("Unknown middleware diagnostic synthetic-code", ()),
    ],
)
def test_022_FR_021_unknown_application_request_shapes_are_safe_to_format(
    message: str, args: Any
) -> None:
    """Malformed application request records cannot leak through another format field."""
    event = record(message, args, name="app.api.middleware")
    assert PushCallbackAccessFilter(api_prefix="/api").filter(event)
    assert "synthetic-code" not in logging.Formatter("%(message)s").format(event)


def test_022_FR_021_previously_redacted_application_target_still_clears_exception() -> (
    None
):
    """A middleware-redacted malformed target cannot regain its secret through a traceback."""
    event = record(
        "api_request_failed method=%s path=%s duration_ms=%.1f",
        ("GET", "[redacted]", 1.0),
        name="app.api.middleware",
    )
    event.exc_text = "synthetic-code"
    assert PushCallbackAccessFilter(api_prefix="/api").filter(event)
    assert "synthetic-code" not in logging.Formatter("%(message)s").format(event)


@pytest.mark.parametrize(
    "untrusted_id", ["person@example.com", "synthetic-code", "123456", "grant=proof"]
)
def test_022_FR_021_auth_logs_do_not_echo_credentials_from_untrusted_correlation_header(
    untrusted_id: str,
) -> None:
    """The log correlation field cannot echo rejected credential-shaped request header input."""
    event = record(
        "api_request_failed method=%s path=%s duration_ms=%.1f",
        ("GET", "/api/auth/providers/google/callback", 1.0),
        name="app.api.middleware",
    )
    event.correlation_id = untrusted_id
    assert PushCallbackAccessFilter(api_prefix="/api").filter(event)
    rendered = logging.Formatter("%(correlation_id)s %(message)s").format(event)
    assert untrusted_id not in rendered
    assert "api_request_failed" in rendered


def test_022_FR_021_logging_filter_never_loads_configuration_and_receives_explicit_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Logging receives the settled route prefix without config or network work while filtering."""
    import app.core.logging as log_module

    def forbidden_config() -> AppConfig:
        raise AssertionError("Logging filter attempted configuration I/O")

    monkeypatch.setattr(log_module, "get_config", forbidden_config)
    event = record(
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/api/auth?code=synthetic-code", "1.1", 400),
    )
    assert PushCallbackAccessFilter().filter(event)
    assert "synthetic-code" not in event.getMessage()
    configured = build_logging_dict("DEBUG", api_prefix="/custom")
    assert configured["filters"]["push_callback"]["api_prefix"] == "/custom"
    assert "push_callback" in configured["handlers"]["console"]["filters"]


def test_022_FR_021_real_middleware_failure_and_success_logs_are_auth_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Real middleware request logs remain safe on callback success and handler failure."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware, api_prefix="/custom")

    @app.get("/custom/auth/providers/google/callback")
    async def callback() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/custom/auth/providers/apple/callback")
    async def failure() -> None:
        raise RuntimeError("synthetic-code person@example.com")

    logger = logging.getLogger("app.api.middleware")
    protection = PushCallbackAccessFilter(api_prefix="/custom")
    logger.addFilter(protection)
    try:
        with caplog.at_level(logging.DEBUG, logger="app.api.middleware"):
            client = TestClient(app, raise_server_exceptions=False)
            assert (
                client.get(
                    "/custom/auth/providers/google/callback?code=synthetic-code&state=synthetic-state"
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/custom/auth/providers/apple/callback?email=person@example.com"
                ).status_code
                == 500
            )
    finally:
        logger.removeFilter(protection)
    events = [event for event in caplog.records if event.name == "app.api.middleware"]
    assert len(events) == 2
    rendered = "\n".join(
        logging.Formatter("%(message)s").format(event) for event in events
    )
    assert "api_request " in rendered and "api_request_failed" in rendered
    assert "synthetic" not in rendered and "person@example.com" not in rendered


def test_022_FR_021_actual_nginx_template_uses_sanitized_targets_and_safe_error_policy() -> (
    None
):
    """The shipped nginx template logs sanitized targets and never raw auth URLs or referrers."""
    template = (
        Path(__file__).resolve().parents[2] / "deploy/nginx/default.conf"
    ).read_text()
    formats = re.findall(r"log_format\s+\w+\s+(.+?);", template, re.DOTALL)
    assert len(formats) == 1
    assert "$request " not in formats[0] and "$request_uri" not in formats[0]
    assert "$http_referer" not in formats[0]
    assert (
        "$auth_log_target" in formats[0]
        and "$status" in formats[0]
        and "$request_id" in formats[0]
    )
    assert re.search(r"map\s+\$uri\s+\$auth_safe_uri", template)
    assert "set $auth_log_target $auth_safe_uri;" in template
    assert "default $request_uri;" in template
    assert '"~%[0-9A-Fa-f]{2}" [redacted];' in template
    assert "auth|account" in template
    assert "a2a/push" in template and "[redacted]" in template
    assert re.search(r"access_log\s+/dev/stdout\s+auth_safe;", template)
    assert re.search(r"error_log\s+/dev/null\s*;", template)
