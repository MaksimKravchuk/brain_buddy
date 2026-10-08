"""Spec 021 PR-02: X-Client attribution and the validated correlation id."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import CorrelationIdMiddleware


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware, api_prefix="/api")

    @app.get("/api/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError("handler failed")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _lines(caplog: pytest.LogCaptureFixture, prefix: str) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.api.middleware"
        and record.getMessage().startswith(prefix)
    ]


@pytest.mark.parametrize(
    ("header", "client_name", "version"),
    [
        ("brainbuddy-macos/0.1.0", "macos", "0.1.0"),
        ("brainbuddy-ios/1.4", "ios", "1.4"),
        (None, "web", "-"),
        ("evil\nvalue", "other", "-"),
        ("brainbuddy-macos/", "other", "-"),
        ("brainbuddy-ios/" + "1" * 33, "other", "-"),
        ("brainbuddy-watchos/1.0", "other", "-"),
    ],
    ids=["macos", "ios", "absent", "injected", "no-version", "too-long", "unknown"],
)
def test_021_FR_031_x_client_is_logged_as_client_and_version(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    header: str | None,
    client_name: str,
    version: str,
) -> None:
    """Both request log lines carry the parsed fields, never the raw header."""

    headers = {} if header is None else {"X-Client": header}
    expected = f"client={client_name} client_version={version}"
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        assert client.get("/api/ok", headers=headers).status_code == 200
        assert client.get("/api/boom", headers=headers).status_code == 500

    (served,) = _lines(caplog, "api_request ")
    (failed,) = _lines(caplog, "api_request_failed ")
    assert expected in served
    assert expected in failed
    if header is not None and client_name == "other":
        assert header not in caplog.text
        assert "evil" not in caplog.text


def test_021_FR_031_the_header_changes_no_response(client: TestClient) -> None:
    """X-Client is a log label: status, body and headers are identical."""

    plain = client.get("/api/ok")
    labelled = client.get("/api/ok", headers={"X-Client": "brainbuddy-macos/0.1.0"})

    assert (plain.status_code, plain.content) == (
        labelled.status_code,
        labelled.content,
    )
    strip = {"x-correlation-id", "date"}
    assert {k: v for k, v in plain.headers.items() if k not in strip} == {
        k: v for k, v in labelled.headers.items() if k not in strip
    }


@pytest.mark.parametrize("header", ["X-Correlation-ID", "X-Request-ID"])
def test_021_FR_015_forged_correlation_id_is_replaced_by_a_fresh_uuid(
    client: TestClient, caplog: pytest.LogCaptureFixture, header: str
) -> None:
    """A newline-bearing id is never echoed nor logged."""

    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/ok", headers={header: "abc\nforged=1"})

    issued = response.headers["X-Correlation-ID"]
    assert str(uuid.UUID(issued)) == issued
    assert "forged" not in caplog.text
    assert all("forged" not in str(record.__dict__) for record in caplog.records)


@pytest.mark.parametrize(
    "incoming",
    [
        "3f1c1a2e-7b44-4c1d-9a55-0d6f3a1b2c4e",
        "abc.DEF_123-x",
        "a" * 64,
    ],
)
def test_021_FR_015_a_well_formed_correlation_id_is_echoed_unchanged(
    client: TestClient, incoming: str
) -> None:
    """The kit's lower-cased UUID, and any 1..64 safe characters, pass."""

    response = client.get("/api/ok", headers={"X-Correlation-ID": incoming})

    assert response.headers["X-Correlation-ID"] == incoming


@pytest.mark.parametrize("incoming", ["a" * 65, "has space", "semi;colon"])
def test_021_FR_015_an_out_of_pattern_correlation_id_is_replaced(
    client: TestClient, incoming: str
) -> None:
    """Too long or outside the safe alphabet gives a fresh UUID."""

    response = client.get("/api/ok", headers={"X-Correlation-ID": incoming})

    issued = response.headers["X-Correlation-ID"]
    assert issued != incoming
    assert str(uuid.UUID(issued)) == issued


def test_021_FR_030_the_client_fields_survive_the_production_log_filter(
    client: TestClient,
) -> None:
    """PushCallbackAccessFilter accepts the new line shape instead of redacting it."""

    from app.core.logging import PushCallbackAccessFilter

    logger = logging.getLogger("app.api.middleware")
    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    handler = Capture(level=logging.INFO)
    handler.addFilter(PushCallbackAccessFilter(api_prefix="/api"))
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        client.get("/api/ok", headers={"X-Client": "brainbuddy-ios/1.4"})
        client.get("/api/boom", headers={"X-Client": "brainbuddy-ios/1.4"})
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)

    assert len(seen) == 2
    assert all("client=ios client_version=1.4" in line for line in seen)
    assert all("[redacted]" not in line for line in seen)


@pytest.mark.parametrize(
    "client_args",
    [("raw\nvalue", "-"), ("ios", "1.4\nforged"), ("ios", "1" * 33), ("ios", 14)],
    ids=["unknown-client", "bad-version", "long-version", "version-type"],
)
def test_021_FR_030_the_production_filter_redacts_an_unvalidated_client_field(
    client_args: tuple[object, object],
) -> None:
    """A record whose client fields were not parsed cannot carry raw input."""

    from app.core.logging import PushCallbackAccessFilter

    event = logging.LogRecord(
        "app.api.middleware",
        logging.INFO,
        __file__,
        1,
        "api_request method=%s path=%s status=%s "
        "client=%s client_version=%s duration_ms=%.1f",
        ("GET", "/api/ok", 200, *client_args, 1.0),
        None,
    )

    assert PushCallbackAccessFilter(api_prefix="/api").filter(event)
    assert "[redacted]" in event.getMessage()
    assert "forged" not in event.getMessage()
    assert "raw" not in event.getMessage()
