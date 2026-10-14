#!/usr/bin/env python3
"""Reject private data in committed 027 fixtures and evidence (research R13/R15).

Scans ``contracts/fixtures/`` and ``specs/027-rust-server/evidence/`` for
emails, invite codes, session/provider credentials, local paths and content
hashes. Evidence may carry correlation IDs, timings, counts, git SHAs (40 hex)
and screenshots; it must not carry anything that identifies a real person or
fingerprints content. Binary files (screenshots, generated WAV) are skipped.

    python3 scripts/check_evidence_hygiene.py [ROOT ...]

Missing roots are fine (the directories appear as later slices land).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_ROOTS = ("contracts/fixtures", "specs/027-rust-server/evidence")

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    (
        "invite code",
        re.compile(
            r"invite[_ -]?(?:code|token)\"?\s*[:=]\s*\"?[A-Za-z0-9_-]{4,}", re.I
        ),
    ),
    (
        "credential",
        re.compile(
            r"(?:\bsk-[A-Za-z0-9_-]{16,}|\bAKIA[0-9A-Z]{16}\b"
            r"|\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"
            r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
            r"|(?:session[_-]?(?:id|token)?|api[_-]?key|secret(?:[_-]?key)?"
            r"|access[_-]?key(?:[_-]?id)?|password|cookie)\"?\s*[:=]\s*\"?"
            r"[A-Za-z0-9._~+/=-]{8,})",
            re.I,
        ),
    ),
    (
        "local path",
        re.compile(r"(?:/home/[^/\s\"']+|/Users/[^/\s\"']+|[A-Za-z]:\\Users\\)"),
    ),
    (
        "content hash",
        re.compile(
            r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{64}|[0-9A-Fa-f]{32})(?![0-9A-Fa-f])"
            r"|\b(?:sha256|sha-256|md5|blake3)[:=]\s*\S+",
            re.I,
        ),
    ),
)


def scan_text(text: str) -> list[tuple[int, str]]:
    """Return ``(line number, rule name)`` for every violation in ``text``."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in RULES:
            if pattern.search(line):
                found.append((number, name))
    return found


def scan_roots(roots: list[Path]) -> list[str]:
    problems: list[str] = []
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in files:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            problems.extend(f"{path}:{line}: {name}" for line, name in scan_text(text))
    return problems


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or [Path(r) for r in DEFAULT_ROOTS]
    problems = scan_roots([r for r in roots if r.exists()])
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"evidence hygiene: {len(problems)} violation(s)", file=sys.stderr)
        return 1
    print("evidence hygiene: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
