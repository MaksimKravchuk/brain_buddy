#!/usr/bin/env python3
"""Deterministic Ship/Show/Ask path risk classifier (ADR-0008, ADR-0030).

Reads repository-relative paths on stdin, prints one
``<CLASS>\\t<path>\\t<reason>`` line per path, and exits 1 when any path is
ASK class. ASK-class surfaces must land through a reviewed PR or an explicitly
authorized manual high-risk landing, never automatic trunk promotion.

ADR-0030 narrows ASK, while the product has no real users, to what cannot be
undone after a mistake: persisted data and migrations, secrets (including
every GitHub workflow, since any of them can read repository secrets), GDPR
account deletion/export, the Allure quality-gate rules, and the landing
machinery that enforces this classification (this file and the
gate-integrity checker and its manifest). Delivery scripts, Docker/Fly
configuration and auth/session code are SHIP: CI, review and the verified
deploy smoke still guard them.

Two input modes:

- ``--null``/``-z`` (machine mode, REQUIRED for both delivery gates): paths
  are NUL-separated raw bytes as produced by
  ``git diff --no-renames --name-only -z``, read from ``sys.stdin.buffer``
  and decoded with ``surrogateescape``. git never quotes in ``-z`` output,
  so non-ASCII and otherwise unprintable paths classify on their real names,
  and ``--no-renames`` guarantees a rename appears as delete+add so a rename
  away from an ASK path still surfaces as its deletion.
- newline mode (default, for humans and simple fixtures): one path per line.
  A line that looks like git's quoted/backslash-escaped output (or contains
  any backslash) cannot be classified reliably and therefore fails closed as
  ASK — use the NUL mode instead.

Classification rules are ordered and fail closed toward ASK:

1. ASK directory prefixes ``backend/data/`` (persisted data) and
   ``.github/`` (workflows can read repository secrets).
2. ASK exact paths: GDPR account deletion/export, the Allure quality-gate
   rules, and the landing/gate machinery.
3. ASK filenames: ``.env`` and ``.env.*`` (environment/secrets templates).
4. Documentation (``docs/``, ``specs/``, ``*.md``) is SHIP: it cannot change
   runtime or CI behavior.
5. Whole-token match (path segments split on ``.``, ``_``, ``-``) against the
   secrets and migration token sets.
6. Everything else is SHIP.

Used by ``scripts/submit_to_trunk.sh`` (non-skippable preflight) and by the
``land`` job of the default-branch release workflow
(``deploy-fly-production.yml``), which runs the trusted ``origin/main`` copy
of this file so a candidate cannot weaken the gate on itself. Standard
library only, so it runs before any dependencies are installed.
"""

from __future__ import annotations

import argparse
import re
import sys

ASK = "ASK"
SHIP = "SHIP"

ASK_PREFIXES: tuple[tuple[str, str], ...] = (
    ("backend/data/", "persisted data surface"),
    # Any workflow can read repository secrets, and which ones a new or edited
    # workflow reaches cannot be decided from its path.
    (".github/", "CI/workflow surface (repository secrets)"),
)

# Surfaces whose names carry no risk token. Exact paths only: sibling paths
# stay SHIP.
ASK_EXACT_PATHS: dict[str, str] = {
    "backend/app/services/account_service.py": (
        "GDPR account deletion/export surface"
    ),
    # Decides what "passing" means for a whole CI run, yet its name carries no
    # ASK token: a raised failure budget must not land through automatic
    # promotion.
    "allurerc.mjs": "quality-gate configuration surface (Allure gate rules)",
    # The machinery that enforces this classification. If any of these could
    # land automatically, a candidate could widen SHIP for itself and every
    # change after it.
    "scripts/classify_path_risk.py": "landing gate surface (risk classifier)",
    "scripts/check_gate_integrity.py": "landing gate surface (gate integrity)",
    ".specify/gate-integrity.json": "landing gate surface (gate manifest)",
}

SECRET_TOKENS: frozenset[str] = frozenset(
    {
        "secret",
        "secrets",
        "credential",
        "credentials",
    }
)
MIGRATION_TOKENS: frozenset[str] = frozenset(
    {"migration", "migrations", "alembic"}
)

_TOKEN_SPLIT = re.compile(r"[._\-]+")
_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokens(path: str) -> frozenset[str]:
    tokens: set[str] = set()
    for segment in path.split("/"):
        for piece in _TOKEN_SPLIT.split(segment):
            for token in _CAMEL_SPLIT.split(piece):
                if token:
                    tokens.add(token.lower())
    return frozenset(tokens)


def _is_ask_filename(filename: str) -> str | None:
    lowered = filename.lower()
    if lowered == ".env" or lowered.startswith(".env."):
        return "environment/secrets template"
    return None


def classify_path(path: str) -> tuple[str, str]:
    """Classify one repository-relative path; returns (class, reason)."""

    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.strip("/")
    if not normalized:
        return SHIP, "empty path"

    for prefix, reason in ASK_PREFIXES:
        if normalized.startswith(prefix):
            return ASK, reason
    exact_reason = ASK_EXACT_PATHS.get(normalized)
    if exact_reason is not None:
        return ASK, exact_reason

    filename = normalized.rsplit("/", 1)[-1]
    filename_reason = _is_ask_filename(filename)
    if filename_reason is not None:
        return ASK, filename_reason

    if (
        normalized.startswith("docs/")
        or normalized.startswith("specs/")
        or normalized.lower().endswith(".md")
    ):
        return SHIP, "documentation only"

    tokens = _tokens(normalized)
    for token_set, reason in (
        (SECRET_TOKENS, "secrets surface"),
        (MIGRATION_TOKENS, "migration/destructive persistence surface"),
    ):
        matched = sorted(tokens & token_set)
        if matched:
            return ASK, f"{reason} (token {matched[0]!r})"

    return SHIP, "no ASK-class surface matched"


def looks_quoted_or_escaped(line: str) -> bool:
    """True when a newline-mode line looks like git's quoted output.

    git quotes non-ASCII/special paths in newline output (core.quotepath)
    as ``"\\303\\251..."``; such a listing cannot be mapped back to the real
    path reliably, so it must fail closed toward ASK.
    """

    return line.startswith('"') or line.endswith('"') or "\\" in line


def _null_separated_paths(data: bytes) -> list[str]:
    """Decode a NUL-separated ``git ... -z`` listing; never quoted by git."""

    return [
        chunk.decode("utf-8", errors="surrogateescape")
        for chunk in data.split(b"\x00")
        if chunk
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--null",
        "-z",
        action="store_true",
        help=(
            "read NUL-separated raw paths (git diff --no-renames --name-only "
            "-z); required for the delivery gates"
        ),
    )
    args = parser.parse_args(argv)

    # Undecodable bytes in path names must never crash the gate: escape them
    # on output while classifying on the decoded path itself.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")

    if args.null:
        entries = [
            (path, None) for path in _null_separated_paths(sys.stdin.buffer.read())
        ]
    else:
        entries = []
        for raw in sys.stdin.read().splitlines():
            line = raw.strip()
            if not line:
                continue
            forced_reason = (
                "quoted/escaped path listing cannot be classified reliably; "
                "feed NUL-separated paths via --null (-z) instead"
                if looks_quoted_or_escaped(line)
                else None
            )
            entries.append((line, forced_reason))

    ask_paths: list[str] = []
    for path, forced_reason in entries:
        if not path.strip():
            continue
        if forced_reason is not None:
            classification, reason = ASK, forced_reason
        else:
            classification, reason = classify_path(path)
        print(f"{classification}\t{path}\t{reason}")
        if classification == ASK:
            ask_paths.append(path)
    if ask_paths:
        print(
            "ASK-class paths require a reviewed PR or an explicitly authorized "
            "manual high-risk landing (ADR-0008); refusing automatic trunk "
            "promotion for: " + ", ".join(ask_paths),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
