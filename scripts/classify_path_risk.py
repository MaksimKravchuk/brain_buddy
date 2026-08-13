#!/usr/bin/env python3
"""Deterministic Ship/Show/Ask path risk classifier (ADR-0008).

Reads repository-relative paths on stdin, prints one
``<CLASS>\\t<path>\\t<reason>`` line per path, and exits 1 when any path is
ASK class. ASK-class surfaces — CI/workflow definitions, delivery/CI scripts,
Fly/Docker/deploy configuration, auth/session/user/invite code,
migrations and destructive persistence paths, and secrets/permissions
surfaces — must land through a reviewed PR or an explicitly authorized manual
high-risk landing, never automatic trunk promotion.

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

1. ASK directory prefixes and CI entry points (``.github/``, ``scripts/``,
   ``deploy/``, ``backend/data/``, ``Makefile``).
2. ASK exact paths: EAS release configuration (``mobile/eas.json``) and the API
   modules that wire session auth and per-owner privacy enforcement (``backend/app/api/dependencies.py``,
   ``middleware.py``, ``routes.py``, ``tasks.py``) — their names carry no
   auth token, so they are listed explicitly.
3. ASK filenames (``fly*.toml``, ``Dockerfile*``, ``docker-compose*``,
   ``compose.y*ml``, ``.dockerignore``, ``.env*``).
4. Documentation (``docs/``, ``specs/``, ``*.md``) is SHIP: it cannot change
   runtime or CI behavior.
5. Whole-token match (path segments split on ``.``, ``_``, ``-``) against the
   auth/session/user/invite, secrets/permissions, and migration token sets.
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
    (".github/", "CI/workflow surface"),
    ("scripts/", "delivery/CI script surface"),
    ("deploy/", "deploy configuration surface"),
    ("backend/data/", "persisted data surface"),
)

ASK_TOP_LEVEL_FILES: frozenset[str] = frozenset({"Makefile"})

# Release/auth surfaces whose names carry no risk token: EAS build/submission
# configuration and API modules that wire session auth and per-owner privacy
# enforcement. Exact paths only: sibling paths stay SHIP.
ASK_EXACT_PATHS: dict[str, str] = {
    "mobile/eas.json": "mobile release build/submission configuration",
    "backend/app/api/dependencies.py": (
        "auth/per-owner privacy enforcement surface (session dependencies)"
    ),
    "backend/app/api/middleware.py": (
        "auth/per-owner privacy enforcement surface (request middleware)"
    ),
    "backend/app/api/routes.py": (
        "auth/per-owner privacy enforcement surface (owner-filtered routes)"
    ),
    "backend/app/api/tasks.py": (
        "auth/per-owner privacy enforcement surface (owner-filtered task API)"
    ),
}

AUTH_TOKENS: frozenset[str] = frozenset(
    {
        "auth",
        "session",
        "sessions",
        "user",
        "users",
        "invite",
        "invites",
        "login",
        "logout",
        "signup",
        "password",
        "passwords",
    }
)
SECRET_TOKENS: frozenset[str] = frozenset(
    {
        "secret",
        "secrets",
        "credential",
        "credentials",
        "permission",
        "permissions",
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
    if lowered.startswith("fly.") and lowered.endswith(".toml"):
        return "Fly deploy configuration"
    if lowered == "dockerfile" or lowered.startswith("dockerfile."):
        return "Docker build configuration"
    if lowered.startswith("docker-compose") or lowered in (
        "compose.yml",
        "compose.yaml",
    ):
        return "Docker Compose configuration"
    if lowered == ".dockerignore":
        return "Docker build configuration"
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
    if normalized in ASK_TOP_LEVEL_FILES:
        return ASK, "CI entry point"
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
        (AUTH_TOKENS, "auth/session/user/invite surface"),
        (SECRET_TOKENS, "secrets/permissions surface"),
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
