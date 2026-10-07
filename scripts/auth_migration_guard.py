#!/usr/bin/env python3
"""Fail closed before restoring an image that cannot read Identity authority.

The remote probe reads only coarse migration metadata through SQLite read-only
mode. It neither imports application settings nor reads account/session rows.
Actual running-image capability is captured and matched before deployment;
the volume is probed again immediately before forward deployment or rollback.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


class GuardError(RuntimeError):
    """A coarse diagnostic without remote output, paths or record contents."""


def image_schema_epoch(source: Path) -> int:
    if not source.exists():
        return 0
    try:
        tree = ast.parse(source.read_text())
        values = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "AUTH_SCHEMA_EPOCH"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ]
        if len(values) != 1 or type(values[0]) is not int or values[0] < 1:
            raise GuardError("Unverified image storage capability.")
        return values[0]
    except (OSError, SyntaxError) as error:
        raise GuardError("Unverified image storage capability.") from error


def probe_storage(data: Path, source: Path) -> dict[str, Any]:
    try:
        capability = image_schema_epoch(source)
        database = data / "auth.sqlite3"
        legacy_present = any(
            directory.exists() and any(directory.iterdir())
            for directory in (data / "users", data / "sessions")
        )
        if not database.exists():
            return {
                "schema_epoch": 0,
                "import_committed": False,
                "cleanup_complete": True,
                "image_schema_epoch": capability,
                "legacy_auth_present": legacy_present,
            }
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(
                "SELECT schema_epoch, import_committed, cleanup_complete "
                "FROM auth_migration_ledger WHERE id = 1"
            ).fetchall()
        finally:
            connection.close()
        if (
            len(rows) != 1
            or type(rows[0][0]) is not int
            or rows[0][0] < 1
            or rows[0][1] not in (0, 1)
            or rows[0][2] not in (0, 1)
        ):
            raise GuardError("Unverified Identity migration state.")
        return {
            "schema_epoch": rows[0][0],
            "import_committed": bool(rows[0][1]),
            "cleanup_complete": bool(rows[0][2]),
            "image_schema_epoch": capability,
            "legacy_auth_present": legacy_present,
        }
    except (OSError, sqlite3.Error) as error:
        raise GuardError("Unverified Identity migration state.") from error


def restore_allowed(current_epoch: object, captured_epoch: object) -> bool:
    return (
        type(current_epoch) is int
        and type(captured_epoch) is int
        and 0 <= current_epoch <= captured_epoch
    )


def remote_probe_source() -> str:
    # Ship only these stdlib definitions to the old/new image. Importing the
    # app would load settings and fails precisely when the old binary cannot
    # start against the new schema. No credentials enter this source/output.
    definitions = "\n".join(
        inspect.getsource(function)
        for function in (GuardError, image_schema_epoch, probe_storage)
    )
    return (
        "from __future__ import annotations\n"
        "import ast,json,os,sqlite3\nfrom pathlib import Path\n"
        + definitions
        + "\ntry:\n"
        + " print(json.dumps(probe_storage(Path(os.environ.get('BRAIN_BUDDY_DATA_DIR', '/app/data')), Path('/app/app/repositories/auth_store.py'))))\n"
        + "except GuardError:\n print(json.dumps({'error':'unverified'})); raise SystemExit(1)\n"
    )


def _fly(args: list[str]) -> object:
    try:
        result = subprocess.run(
            ["flyctl", *args], capture_output=True, text=True, timeout=30, check=False
        )
        if result.returncode != 0:
            raise GuardError("Identity probe unavailable; image restore forbidden.")
        return json.loads(result.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise GuardError(
            "Identity probe unavailable; image restore forbidden."
        ) from error


def _reports(app: str, *, expected_image: str | None = None) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", app):
        raise GuardError("Invalid app identity.")
    machines = _fly(["machines", "list", "--app", app, "--json"])
    if not isinstance(machines, list) or not machines:
        raise GuardError("No verifiable backend machine.")
    reports = []
    for machine in machines:
        if not isinstance(machine, dict):
            raise GuardError("Unverified backend machine.")
        machine_id = machine.get("id")
        config = machine.get("config")
        image = config.get("image") if isinstance(config, dict) else None
        if (
            not isinstance(machine_id, str)
            or not re.fullmatch(r"[a-f0-9]{14,16}", machine_id)
            or not isinstance(image, str)
            or not image.startswith("registry.fly.io/")
            or (expected_image is not None and image != expected_image)
        ):
            raise GuardError("Running backend differs from captured image.")
        report = _fly(
            [
                "ssh",
                "console",
                "--quiet",
                "--app",
                app,
                "--machine",
                machine_id,
                "--command",
                "python3 -c " + shlex.quote(remote_probe_source()),
            ]
        )
        if (
            not isinstance(report, dict)
            or set(report)
            != {
                "schema_epoch",
                "import_committed",
                "cleanup_complete",
                "image_schema_epoch",
                "legacy_auth_present",
            }
            or type(report["schema_epoch"]) is not int
            or report["schema_epoch"] < 0
            or type(report["image_schema_epoch"]) is not int
            or report["image_schema_epoch"] < 0
            or type(report["import_committed"]) is not bool
            or type(report["cleanup_complete"]) is not bool
            or type(report["legacy_auth_present"]) is not bool
        ):
            raise GuardError("Unverified Identity migration state.")
        reports.append(report)
    return reports


def capture(app: str, image: str, output: Path) -> None:
    reports = _reports(app, expected_image=image)
    record = {
        "version": 1,
        "app": app,
        "image": image,
        "image_schema_epoch": min(row["image_schema_epoch"] for row in reports),
    }
    output.write_text(json.dumps(record) + "\n")
    output.chmod(0o600)


def check(app: str, captured: Path, *, forward: bool = False) -> None:
    try:
        record = json.loads(captured.read_text())
    except (OSError, ValueError) as error:
        raise GuardError(
            "Missing captured storage evidence; restore forbidden."
        ) from error
    if (
        not isinstance(record, dict)
        or type(record.get("version")) is not int
        or record["version"] != 1
        or record.get("app") != app
        or not isinstance(record.get("image"), str)
        or not record["image"].startswith("registry.fly.io/")
        or type(record.get("image_schema_epoch")) is not int
    ):
        raise GuardError("Unverified captured storage evidence.")
    reports = _reports(app)
    epoch = max(row["schema_epoch"] for row in reports)
    target_epoch = (
        image_schema_epoch(
            Path(__file__).resolve().parent.parent
            / "backend/app/repositories/auth_store.py"
        )
        if forward
        else record["image_schema_epoch"]
    )
    if (
        forward
        and target_epoch >= 1
        and any(
            (row["schema_epoch"] == 0 and row["legacy_auth_present"])
            or not row["cleanup_complete"]
            for row in reports
        )
    ):
        raise GuardError(
            "Explicit authentication migration must finish before deployment. "
            "Keep the existing release running until the stopped-writer "
            "maintenance window; do not replace its image or stage secrets."
        )
    if not restore_allowed(epoch, target_epoch):
        raise GuardError(
            "Identity storage requires a compatible image. Preserve the volume; "
            "contain access and use exact-SHA forward repair. Deployment remains failed."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "forward", "restore"))
    parser.add_argument("--app", required=True)
    parser.add_argument("--image")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "capture":
            if not args.image or args.output is None:
                raise GuardError("Capture needs image and output.")
            capture(args.app, args.image, args.output)
        else:
            if args.capture is None:
                raise GuardError("Missing captured storage evidence.")
            check(args.app, args.capture, forward=args.action == "forward")
        print("Identity image compatibility verified.")
        return 0
    except GuardError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
