"""The vendored reference runtimes are unmodified, and this proves it.

Spec 014 FR-017 requires BrainBuddy's A2A client to be exercised against two
*real* third-party runtimes — the official a2a-sdk helloworld sample and the
Hermes A2A plugin — rather than against fakes written by the same hand that
wrote the client. That evidence is only worth something if the vendored copies
are byte-identical to the upstream sources they claim to be. A single
convenience edit ("just make it bind port 0", "just drop that import") would
turn a conformance proof into a self-portrait.

So the guarantee is mechanical: each vendored tree carries a ``PROVENANCE.md``
naming the upstream commit, the licence and a sha256 for every file, and these
tests re-hash the tree against that record. The tooling that would otherwise
rewrite these files — black, ``ruff --fix``, mypy — is excluded from
``backend/vendor/`` in ``.pre-commit-config.yaml`` and ``backend/pyproject.toml``
for exactly this reason.

The BrainBuddy-owned harness that drives the vendored plugin (the ``gateway``
import stub and ``run_stub.py``) is deliberately *not* under the provenance
record: it is our code, it is allowed to change, and it is listed as such below
so an unrecorded file is still a failure rather than a blind spot.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

VENDOR_ROOT = Path(__file__).resolve().parents[1] / "vendor"

HELLOWORLD_ROOT = VENDOR_ROOT / "a2a_helloworld"
HERMES_ROOT = VENDOR_ROOT / "hermes_a2a"

HELLOWORLD_COMMIT = "6603ba3f2c31a7ef33e70b9d8b5b5f8be42ac9a3"
HERMES_COMMIT = "63279301bcbdc185c1b07b98a9312eb0c862f26d"

#: Paths under ``hermes_a2a`` BrainBuddy wrote itself, so they carry no upstream
#: sha256. Everything else in the tree must appear in the provenance record.
HERMES_OWNED_PREFIXES = ("gateway/", "run_stub.py")

_SHA_ROW = re.compile(
    r"^\|\s*`(?P<path>[^`]+)`\s*\|\s*`(?P<sha256>[0-9a-f]{64})`\s*\|\s*$"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded_hashes(provenance: Path) -> dict[str, str]:
    """Parse the ``| `path` | `sha256` |`` rows out of a PROVENANCE.md."""

    text = provenance.read_text(encoding="utf-8")
    return {
        match.group("path"): match.group("sha256")
        for line in text.splitlines()
        if (match := _SHA_ROW.match(line.strip()))
    }


def _vendored_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "PROVENANCE.md"
        and "__pycache__" not in path.parts
    )


def _assert_tree_matches_provenance(
    root: Path,
    *,
    commit: str,
    licence_marker: str,
    owned_prefixes: tuple[str, ...] = (),
) -> None:
    provenance = root / "PROVENANCE.md"
    assert provenance.is_file(), (
        f"{provenance} is missing: a vendored runtime without a provenance "
        "record cannot be proved unmodified."
    )

    text = provenance.read_text(encoding="utf-8")
    assert commit in text, f"{provenance} does not record the upstream commit {commit}."
    assert (
        licence_marker in text
    ), f"{provenance} does not record the upstream licence ({licence_marker})."
    assert (root / "LICENSE").is_file(), (
        f"{root / 'LICENSE'} is missing: the upstream licence travels with the "
        "vendored source."
    )

    recorded = _recorded_hashes(provenance)
    assert recorded, f"{provenance} records no per-file sha256 rows."

    present = _vendored_files(root)
    assert present, f"{root} contains no vendored files."

    mismatched: list[str] = []
    unrecorded: list[str] = []
    for path in present:
        relative = path.relative_to(root).as_posix()
        if relative.startswith(owned_prefixes):
            continue
        expected = recorded.get(relative)
        if expected is None:
            unrecorded.append(relative)
            continue
        actual = _sha256(path)
        if actual != expected:
            mismatched.append(f"{relative}: recorded {expected}, found {actual}")

    missing = sorted(
        relative for relative in recorded if not (root / relative).is_file()
    )

    assert not unrecorded, (
        "vendored files with no provenance entry (an unrecorded file is an "
        f"unproved file): {unrecorded}"
    )
    assert not missing, f"provenance records files that are not vendored: {missing}"
    assert not mismatched, (
        "vendored files differ from their recorded upstream sha256 — the tree "
        f"has been modified: {mismatched}"
    )


@pytest.mark.parametrize(
    ("relative", "reason"),
    [
        ("__main__.py", "the sample's server entrypoint"),
        ("agent_executor.py", "the sample's executor"),
    ],
)
def test_014_FR_017_vendored_helloworld_carries_the_files_the_reference_test_runs(
    relative: str, reason: str
) -> None:
    """The helloworld reference runtime is present in full.

    AC-001: the conformance evidence names the official sample, so the two
    modules the reference test actually starts must both be vendored.
    """

    path = HELLOWORLD_ROOT / relative
    assert path.is_file(), f"{path} is missing ({reason})."


def test_014_FR_017_vendored_helloworld_files_match_provenance_sha256() -> None:
    """Every vendored helloworld file hashes to its recorded sha256.

    AC-001, 014-SC-001: the "unmodified official sample" claim is only
    verifiable if the bytes are checked against the recorded upstream commit.
    """

    _assert_tree_matches_provenance(
        HELLOWORLD_ROOT,
        commit=HELLOWORLD_COMMIT,
        licence_marker="Apache-2.0",
    )


def test_014_FR_017_vendored_hermes_plugin_files_match_provenance_sha256() -> None:
    """Every vendored Hermes plugin file hashes to its recorded sha256.

    AC-001, 014-SC-001: the Hermes plugin is the second reference runtime; the
    BrainBuddy-owned harness beside it is excluded by name, so an accidental
    edit to the *plugin* still fails.
    """

    _assert_tree_matches_provenance(
        HERMES_ROOT,
        commit=HERMES_COMMIT,
        licence_marker="MIT",
        owned_prefixes=HERMES_OWNED_PREFIXES,
    )
