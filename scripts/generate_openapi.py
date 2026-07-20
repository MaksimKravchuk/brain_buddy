#!/usr/bin/env python3
"""Deterministically generate the pinned OpenAPI v1 snapshot.

ADR-0008 requires the mobile contract generator to consume an OpenAPI
document produced from an *ephemeral* app/data root, never the developer's
real ``backend/data`` volume or persisted user data. This script builds the
FastAPI app the same way the test suite does -- ``BRAIN_BUDDY_ENV=test``
plus a throwaway temporary data directory -- computes ``app.openapi()``, and
writes it with stable key ordering so the diff is meaningful and CI can
detect drift byte-for-byte.

Usage:
    python3 scripts/generate_openapi.py [--check]

``--check`` compares the freshly generated document against the committed
``openapi/brainbuddy-v1.json`` and exits non-zero on any difference,
without writing to disk -- this is what CI/``make check-api-contract`` runs.
Without ``--check`` the script overwrites the pinned snapshot in place.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
SNAPSHOT_PATH = REPO_ROOT / "openapi" / "brainbuddy-v1.json"


def _generate_schema() -> dict:
    """Build the FastAPI app against an ephemeral app/data root and return
    its OpenAPI schema as a plain dict."""

    import os

    with tempfile.TemporaryDirectory(prefix="brainbuddy-openapi-gen-") as tmp:
        os.environ["BRAIN_BUDDY_ENV"] = "test"
        os.environ["BRAIN_BUDDY_DATA_DIR"] = tmp
        os.environ.pop("BRAIN_BUDDY_ADMIN_EMAIL", None)
        os.environ.pop("BRAIN_BUDDY_ADMIN_PASSWORD", None)

        if str(BACKEND_ROOT) not in sys.path:
            sys.path.insert(0, str(BACKEND_ROOT))

        from app.core import get_config

        get_config.cache_clear()

        from app.main import create_app

        app = create_app()
        try:
            schema = app.openapi()
        finally:
            _stop_voice_sweep(app)
        get_config.cache_clear()
        return schema


def _stop_voice_sweep(app) -> None:
    """Mirror the test suite's shutdown so this one-shot generation run
    never leaves a background thread alive after the script exits."""

    stop_event = getattr(app.state, "voice_sweep_stop_event", None)
    wake_event = getattr(app.state, "voice_sweep_wake_event", None)
    thread = getattr(app.state, "voice_sweep_thread", None)
    if stop_event is not None:
        stop_event.set()
    if wake_event is not None:
        wake_event.set()
    if thread is not None:
        thread.join(timeout=5)


def _dump(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare against the pinned snapshot instead of writing it.",
    )
    args = parser.parse_args()

    schema = _generate_schema()
    rendered = _dump(schema)

    if args.check:
        if not SNAPSHOT_PATH.exists():
            print(f"Missing pinned OpenAPI snapshot at {SNAPSHOT_PATH}", file=sys.stderr)
            return 1
        current = SNAPSHOT_PATH.read_text(encoding="utf-8")
        if current != rendered:
            print(
                "OpenAPI contract drift detected: "
                f"{SNAPSHOT_PATH} does not match the generated schema.\n"
                "Run `make generate-openapi` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"OpenAPI contract matches {SNAPSHOT_PATH}")
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
