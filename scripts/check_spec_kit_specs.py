#!/usr/bin/env python3
"""Validate BrainBuddy Spec Kit feature directories.

This check is intentionally deterministic and offline. It does not regenerate
Spec Kit output; it only rejects new feature-spec directories that omit the
minimum artifacts BrainBuddy requires with github/spec-kit v0.15.0.

Legacy `hermes-handoff.json` files are validated when present. The repository
check enforces only the portable Spec Kit minimum; an explicitly managed outcome
has additional runtime gates outside this checker.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = REPO_ROOT / "specs"

# Resolved from this file rather than REPO_ROOT so tests may retarget the specs
# tree without detaching the canonical handoff validator.
HANDOFF_VALIDATOR_PATH = Path(__file__).resolve().with_name("spec_kit_planning_review.py")
HANDOFF_VALIDATOR_MODULE = "spec_kit_planning_review"
HANDOFF_ARTIFACT = "hermes-handoff.json"

REQUIRED_FILES = (
    "spec.md",
    "checklists/requirements.md",
    "plan.md",
    "tasks.md",
)

GRANDFATHERED = {
    "001-relation-linking-refactor": {
        "reason": (
            "Complete pre-ADR-0009 Spec Kit package; do not fabricate a review "
            "handoff unless the feature is materially changed."
        ),
        "baseline_sha256": {
            "spec.md": "f07bc74f166155c8ff98d4bd3ae7d637d0b15ee26ba73950311d67e718c677fe",
            "checklists/requirements.md": "eca9a2ef68d93344959e0a56798bda832e6319d23cb394eb00f62c270827e746",
            "plan.md": "305f8f62d09c914952180f4c4d8bb08840e8eb2c743e67264c0b552d57d8f6a8",
            "tasks.md": "0c4918899412a43b66c532610eb18e578846807f19640bf4ff0e4e93e191bdc8",
        },
    },
    "002-async-voice-workflows": {
        "reason": (
            "Materially completed before ADR-0009 with acceptance, plan, checklist, "
            "tasks, and readiness evidence; do not fabricate a review handoff unless "
            "the feature changes again."
        ),
        "baseline_sha256": {
            "spec.md": "79d8a2b0b8e84e7e1e3f0c576ee7a54b09d5e2028912bb4973fb43c4f7ecbe91",
            "acceptance-tests.md": "b1cc305eea3dd81357d26b0e3aca43b12ad42d158f362313b3f1d44d9b918556",
            "checklists/requirements.md": "9cee75287ac022fc50eb379d9f918c82e420e4f44953f000960c1d20ed17f4ed",
            "plan.md": "e1c4629de5a9316032729f6b39d356d0ae8d13b0f22efb25ff98035728d65d31",
            "tasks.md": "e87914c6810904fe4603da1ec83771674ec12eaf282a60f270e27db5312d302b",
            "implementation-readiness.md": "551769b166e847544e7b699352ae5fc647baf68cd905af097121bb47a2296563",
        },
    },
    "003-smart-add-classification": {
        "reason": (
            "Complete pre-ADR-0009 Spec Kit package; do not fabricate a review "
            "handoff unless the feature is materially changed."
        ),
        "baseline_sha256": {
            "spec.md": "6f206e0fb577bb8576b0e7d988b769e620825c4b3bb92189cdba1747a0ae042f",
            "checklists/requirements.md": "5833882f1430c7bb96a445d40938c8cb038011e9b497034f1b4df334fea29122",
            "plan.md": "c987593bc068de5246264f33a270a7e7f760a44d96bcd8dec18b34a3ab1d77b4",
            "tasks.md": "505d99644d93df15abca0d9bfd0cc42d525e7689732f9602de4720faf3afdb16",
        },
    },
    "004-verified-trunk-delivery": {
        "reason": (
            "Complete pre-ADR-0009 delivery spec; do not fabricate a review "
            "handoff unless the feature is materially changed."
        ),
        "baseline_sha256": {
            "spec.md": "a7cd154d6ff9cb94ba403e1726c8328676e4b7776b38ac0601151e34a5a1852d",
            "checklists/requirements.md": "011d5b92f61665c240338fcddc5e695d14efd37f28a3c5fc869470b82cc6e20e",
            "plan.md": "29ab1115aa95251e08027fdf24e11845ea7ac0ea48b40a2c28b1bded1705358b",
            "tasks.md": "90b86a53c634d1643bdec4028a43e0360d14c2044645a0cf6234433e44bdab88",
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


def _load_handoff_validator() -> Callable[[object], dict[str, Any]]:
    """Load the canonical handoff validator by path, without touching sys.path.

    The module is cached under its own name so repeated loads (and suites that
    already imported it) reuse one module object instead of re-executing it.
    """
    module = sys.modules.get(HANDOFF_VALIDATOR_MODULE)
    if module is None:
        spec = importlib.util.spec_from_file_location(
            HANDOFF_VALIDATOR_MODULE, HANDOFF_VALIDATOR_PATH
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load validator from {HANDOFF_VALIDATOR_PATH}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[HANDOFF_VALIDATOR_MODULE] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[HANDOFF_VALIDATOR_MODULE]
            raise
    validate_handoff = getattr(module, "validate_handoff", None)
    if not callable(validate_handoff):
        raise RuntimeError(f"{HANDOFF_VALIDATOR_PATH} does not expose validate_handoff")
    return validate_handoff


def _validate_handoff_contents(path: Path, failures: list[str]) -> None:
    """Fail closed unless the handoff satisfies the canonical contract."""
    try:
        validate_handoff = _load_handoff_validator()
    except Exception as exc:  # noqa: BLE001 - any load failure must fail closed
        failures.append(f"{_relative(path)}: handoff validator unavailable ({exc})")
        return

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        failures.append(f"{_relative(path)}: invalid JSON ({exc})")
        return

    try:
        validate_handoff(payload)
    except (ValueError, KeyError, TypeError) as exc:
        failures.append(f"{_relative(path)}: invalid Hermes handoff ({exc})")


def _validate_required_files(spec_dir: Path, failures: list[str]) -> None:
    for required_file in REQUIRED_FILES:
        _require_regular_nonempty(spec_dir / required_file, failures, required_file)

    legacy_handoff = spec_dir / HANDOFF_ARTIFACT
    if legacy_handoff.exists() and _require_regular_nonempty(
        legacy_handoff, failures, HANDOFF_ARTIFACT
    ):
        _validate_handoff_contents(legacy_handoff, failures)


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
            "/speckit-checklist -> /speckit-tasks -> /speckit-analyze.",
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
