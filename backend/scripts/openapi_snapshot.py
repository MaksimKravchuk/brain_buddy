#!/usr/bin/env python3
"""Deterministic, ephemeral OpenAPI generation and drift checking.

This never talks to a live server, Fly, production, or any arbitrary URL. It
always builds the FastAPI app in-process against a throwaway temporary data
directory with ``BRAIN_BUDDY_ENV=test`` and reads ``app.openapi()`` directly —
exactly the same construction the backend test suite uses
(``tests/conftest.py``, ``tests/test_mobile_session_api.py``).

Usage (from ``backend/``, with the project's dev dependencies installed via the
locked environment so output stays byte/semantically reproducible -- an
unlocked ``pip install`` can resolve a newer FastAPI/Pydantic and drift the
generated document):

    uv sync --locked --extra dev
    python -m scripts.openapi_snapshot dump --out ../mobile/api/openapi.json
    python -m scripts.openapi_snapshot check --snapshot ../mobile/api/openapi.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def build_ephemeral_openapi() -> dict[str, Any]:
    """Return ``create_app().openapi()`` for a throwaway test-mode app."""

    from app.core import get_config
    from app.main import create_app

    previous_env = os.environ.get("BRAIN_BUDDY_ENV")
    previous_data_dir = os.environ.get("BRAIN_BUDDY_DATA_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="brainbuddy-openapi-") as tmp_dir:
            os.environ["BRAIN_BUDDY_ENV"] = "test"
            os.environ["BRAIN_BUDDY_DATA_DIR"] = tmp_dir
            get_config.cache_clear()
            app = create_app()
            spec = app.openapi()
    finally:
        _restore_env("BRAIN_BUDDY_ENV", previous_env)
        _restore_env("BRAIN_BUDDY_DATA_DIR", previous_data_dir)
        get_config.cache_clear()
    return spec


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _canonical_text(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _diff(committed: Any, live: Any, path: str, lines: list[str]) -> None:
    if isinstance(committed, dict) and isinstance(live, dict):
        for key in sorted(set(committed) | set(live)):
            sub_path = f"{path}/{key}"
            if key not in committed:
                lines.append(f"  only in live (regenerate the snapshot):      {sub_path}")
            elif key not in live:
                lines.append(f"  only in committed (stale/removed operation): {sub_path}")
            else:
                _diff(committed[key], live[key], sub_path, lines)
    elif isinstance(committed, list) and isinstance(live, list):
        if committed != live:
            lines.append(f"  list differs at {path}: committed={committed!r} live={live!r}")
    elif committed != live:
        lines.append(f"  differs at {path}: committed={committed!r} live={live!r}")


def cmd_dump(args: argparse.Namespace) -> int:
    spec = build_ephemeral_openapi()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_canonical_text(spec), encoding="utf-8")
    print(f"Wrote ephemeral OpenAPI snapshot to {args.out}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    if not args.snapshot.is_file():
        print(f"error: committed snapshot does not exist: {args.snapshot}", file=sys.stderr)
        return 1

    live = build_ephemeral_openapi()
    committed = json.loads(args.snapshot.read_text(encoding="utf-8"))

    if committed == live:
        print(f"OK: {args.snapshot} matches create_app().openapi() (semantic comparison).")
        return 0

    lines: list[str] = []
    _diff(committed, live, "", lines)
    print(
        f"error: {args.snapshot} is out of date relative to create_app().openapi().",
        file=sys.stderr,
    )
    for line in lines:
        print(line, file=sys.stderr)
    print(
        "Regenerate with: python -m scripts.openapi_snapshot dump "
        f"--out {args.snapshot} (from backend/), then refresh the generated "
        "TypeScript client per mobile/README.md.",
        file=sys.stderr,
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dump = subparsers.add_parser(
        "dump", help="write the ephemeral OpenAPI document to a file"
    )
    dump.add_argument("--out", type=Path, required=True)
    dump.set_defaults(func=cmd_dump)

    check = subparsers.add_parser(
        "check",
        help="semantically compare a committed snapshot against the ephemeral document",
    )
    check.add_argument("--snapshot", type=Path, required=True)
    check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
