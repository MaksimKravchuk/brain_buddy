"""Attach what a step checked to the Allure step that checked it.

A step that only wraps assertions finishes in under a millisecond and carries no
trace of the inputs, so ``scripts/validate_allure_taxonomy.py`` rejects it as a
zero-duration no-op. These helpers attach the compared values to the *current*
step and then assert, so the report shows the vector and both sides of each
comparison, and a failure still points at the exact check.
"""

from __future__ import annotations

import json
from typing import Any

import allure


def attach_json(name: str, payload: Any) -> None:
    """Attach ``payload`` as JSON evidence to the running step."""

    allure.attach(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        name=name,
        attachment_type=allure.attachment_type.JSON,
    )


def check_equal(label: str, actual: Any, expected: Any) -> None:
    """Attach ``actual`` and ``expected`` for ``label``, then assert they match."""

    attach_json(
        f"check: {label}",
        {"actual": actual, "expected": expected, "matches": actual == expected},
    )
    assert actual == expected, label
