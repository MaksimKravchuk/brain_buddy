#!/usr/bin/env python3
"""Validate BrainBuddy Spec Kit feature directories.

This check is intentionally deterministic and offline. It does not regenerate
Spec Kit output; it only rejects new feature-spec directories that omit the
minimum artifacts BrainBuddy requires after adopting github/spec-kit v0.12.17.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = REPO_ROOT / "specs"

REQUIRED_FILES = (
    "spec.md",
    "checklists/requirements.md",
    "plan.md",
    "tasks.md",
)

GRANDFATHERED = {
    "002-async-voice-workflows": {
        "reason": (
            "Pre-v0.12.17 adoption ADR/spec package; acceptance-tests.md is "
            "its normative checklist. Do not fabricate missing generated "
            "artifacts unless this feature is materially changed."
        ),
        "baseline_sha256": {
            "spec.md": (
                "31ea73d70afb6cf2c1172d094f235e7a91994174883b05f74a93dd46adfae49d"
            ),
            "acceptance-tests.md": (
                "db5b58eb61638e435b1c3b6764f6d599f4a9339a6cff5c6e0224804d1cbf3ea2"
            ),
        },
    },
}

FEATURE_DIR_PATTERN = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_regular_nonempty(path: Path, failures: list[str], label: str) -> bool:
    if not path.exists():
        failures.append(f"{_relative(path.parent)}: missing {label}")
        return False
    if not path.is_file():
        failures.append(f"{_relative(path)}: must be a regular file")
        return False
    if path.stat().st_size == 0:
        failures.append(f"{_relative(path)}: file is empty")
        return False
    return True


def _validate_required_files(spec_dir: Path, failures: list[str]) -> None:
    for required_file in REQUIRED_FILES:
        _require_regular_nonempty(spec_dir / required_file, failures, required_file)


def _grandfathered_baseline_matches(spec_dir: Path, failures: list[str]) -> bool:
    baseline = GRANDFATHERED[spec_dir.name]["baseline_sha256"]
    matches = True

    for normative_file, expected_hash in baseline.items():
        candidate = spec_dir / normative_file
        if not _require_regular_nonempty(
            candidate,
            failures,
            f"grandfathered normative {normative_file}",
        ):
            matches = False
            continue

        actual_hash = _sha256(candidate)
        if actual_hash != expected_hash:
            matches = False

    return matches


def main() -> int:
    if not SPECS_DIR.exists():
        print("Spec Kit check failed: specs/ directory is missing", file=sys.stderr)
        return 1
    if not SPECS_DIR.is_dir():
        print("Spec Kit check failed: specs/ must be a directory", file=sys.stderr)
        return 1

    failures: list[str] = []
    grandfathered_seen: list[str] = []
    seen_dirs: set[str] = set()

    for spec_dir in sorted(path for path in SPECS_DIR.iterdir() if path.is_dir()):
        name = spec_dir.name
        seen_dirs.add(name)
        if not FEATURE_DIR_PATTERN.match(name):
            failures.append(
                f"{_relative(spec_dir)}: directory name must match "
                "NNN-kebab-case-feature"
            )
            continue

        if name in GRANDFATHERED:
            if _grandfathered_baseline_matches(spec_dir, failures):
                grandfathered_seen.append(
                    f"{_relative(spec_dir)} ({GRANDFATHERED[name]['reason']})"
                )
                continue

            grandfathered_seen.append(
                f"{_relative(spec_dir)} baseline changed; enforcing current "
                "Spec Kit artifact minimum"
            )

        _validate_required_files(spec_dir, failures)

    for grandfathered_name, config in sorted(GRANDFATHERED.items()):
        if grandfathered_name not in seen_dirs:
            failures.append(
                f"specs/{grandfathered_name}: missing grandfathered spec "
                f"directory ({config['reason']})"
            )

    if failures:
        print("Spec Kit artifact check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        print(
            "\nNew or materially changed features must follow: constitution -> "
            "/speckit-specify -> /speckit-clarify -> /speckit-plan -> "
            "/speckit-checklist -> /speckit-tasks -> Hermes Kanban handoff.",
            file=sys.stderr,
        )
        return 1

    print("Spec Kit artifact check passed.")
    if grandfathered_seen:
        print("Grandfathered historical specs:")
        for entry in grandfathered_seen:
            print(f"- {entry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
