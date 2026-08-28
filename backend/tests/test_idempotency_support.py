from __future__ import annotations

from datetime import date

import pytest
from pydantic import BaseModel

from app.exceptions import ConflictError
from app.utils.idempotency import (
    ReplayFingerprint,
    idempotency_key_digest,
    request_fingerprint,
    require_matching_replay,
)


class Payload(BaseModel):
    title: str = "default"
    optional: str | None = None
    due_date: date | None = None


def test_known_sha256_and_utf8_key_vector() -> None:
    assert (
        idempotency_key_digest("clé")
        == "51cbcf30514d0802eb5c60a018f384ea3fb9b69307c554ee63ecb43177594de4"
    )
    assert (
        idempotency_key_digest("owner-α")
        == "de3d25073e03c80fe92dc0263a5780333dabea88a285c29e24d6adb84f1bf2e9"
    )


def test_request_fingerprint_is_canonical_and_preserves_fields_set() -> None:
    assert (
        request_fingerprint("command", Payload(optional=None))
        == "543fd9f23b9173964fcd56b746e9382a6ab310a28a8f6dbd0392beb3f8a58ffa"
    )
    assert request_fingerprint("command", Payload()) != request_fingerprint(
        "command", Payload(optional=None)
    )
    assert request_fingerprint("command", Payload()) != request_fingerprint(
        "other", Payload()
    )
    assert request_fingerprint("command", Payload(title="café")) == request_fingerprint(
        "command", Payload(title="café")
    )


def test_request_fingerprint_uses_json_mode_for_date_payload() -> None:
    assert (
        request_fingerprint("command", Payload(due_date=date(2026, 8, 28)))
        == "1c3a3ba5a8981fa04447f698bbe6604dfc5f2087a73dbc8fb5d435517f7ea9a6"
    )


def test_require_matching_replay_accepts_exact_fingerprint() -> None:
    assert (
        require_matching_replay(
            ReplayFingerprint("command", "hash"),
            key="same",
            command="command",
            request_hash="hash",
        )
        is None
    )


@pytest.mark.parametrize(
    ("command", "request_hash"), [("other", "hash"), ("command", "other")]
)
def test_require_matching_replay_rejects_mismatch_with_exact_conflict(
    command: str, request_hash: str
) -> None:
    with pytest.raises(ConflictError) as raised:
        require_matching_replay(
            ReplayFingerprint("command", "hash"),
            key="same",
            command=command,
            request_hash=request_hash,
        )
    assert raised.value.resource == "Idempotency-Key"
    assert raised.value.identifier == "same"
