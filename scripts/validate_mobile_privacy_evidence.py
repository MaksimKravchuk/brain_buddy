#!/usr/bin/env python3
"""Scan publishable mobile CI evidence for privacy leaks (ADR-0008).

Before mobile logs, Allure results, screenshots, crash artifacts, bundles,
source maps, and build output are uploaded as CI artifacts, they must not
carry credential values, email values, raw audio/transcript content, task
content (Task/TaskComment title, details, or body text), absolute
developer/device paths, or content hashes. ADR-0008 requires this scan as a
release gate; see "Verification / tests" item 7 in
``docs/decisions/0008-add-one-expo-mobile-client-over-opaque-sessions.md``.

This intentionally reports only the offending file path and category name,
never the matched text, so a scan failure cannot itself leak the value it
found. It uses only the Python standard library so it can run before mobile
or backend dependencies are installed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Raw audio must never leave the device as part of publishable CI evidence
# (ADR-0008: local audio is deleted once upload recovery no longer needs it).
# A file with one of these extensions inside scanned evidence is itself the
# leak, regardless of whether its bytes decode as text.
_AUDIO_EXTENSIONS = {".m4a", ".wav", ".caf", ".mp3", ".aac", ".3gp", ".amr"}

_CREDENTIAL = re.compile(
    r"(?:Bearer\s+|Authorization\"?\s*[:=]\s*\"?Bearer\s+|eyJ)[A-Za-z0-9._~-]{32,}"
    r"|\"session_token\"\s*:\s*\"[^\"]{20,}\""
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

_AUDIO_DATA_URI = re.compile(r"data:audio/[a-zA-Z0-9.+-]+;base64,")
_AUDIO_PATH = re.compile(
    r"[^\s\"']+\.(?:m4a|wav|caf|mp3|aac|3gp|amr)\b", re.IGNORECASE
)
# A long free-text value under a transcript-shaped key is a stronger signal
# than the key alone, which fixture objects legitimately use with short
# placeholder strings.
_TRANSCRIPT_FIELD = re.compile(
    r"\"(?:transcript|transcriptText|rawTranscript)\"\s*:\s*\"(?:[^\"\\]|\\.){200,}\""
)

# Real Task/TaskComment wire field names (backend/app/schemas/tasks.py:
# title, details; TaskCommentDocument.body). A long value under one of these
# keys is a stronger signal than the key alone, which short fixture titles
# like "buy milk" legitimately use.
_TASK_CONTENT_FIELD = re.compile(
    r"\"(?:title|details|body)\"\s*:\s*\"(?:[^\"\\]|\\.){80,}\""
)

# Developer/device home directories, not the shared GitHub-hosted runner
# account, so a generic CI-produced ``/home/runner/...`` path in a source map
# does not fail the scan.
_ABSOLUTE_PATH = re.compile(
    r"/Users/[A-Za-z0-9_.\-]+/"
    r"|/home/(?!runner/)[A-Za-z0-9_.\-]+/"
    r"|[A-Za-z]:\\Users\\[A-Za-z0-9_.\-]+\\"
)

# A bare SHA-256 hex digest (e.g. an uploaded audio chunk's content hash).
# Allure's own historyId/testCaseId use 32-char MD5-style hex, which this
# 64-char pattern never matches.
_CONTENT_HASH = re.compile(r"\b[a-fA-F0-9]{64}\b")

_CATEGORY_CHECKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("credential", _CREDENTIAL),
    ("email", _EMAIL),
    ("absolute_path", _ABSOLUTE_PATH),
    ("content_hash", _CONTENT_HASH),
)


def _categories_in_text(text: str) -> set[str]:
    found = {name for name, pattern in _CATEGORY_CHECKS if pattern.search(text)}
    if _AUDIO_DATA_URI.search(text) or _AUDIO_PATH.search(text) or _TRANSCRIPT_FIELD.search(text):
        found.add("audio_transcript_content")
    if _TASK_CONTENT_FIELD.search(text):
        found.add("task_content")
    return found


def _categories_for_file(path: Path) -> set[str]:
    found: set[str] = set()
    if path.suffix.lower() in _AUDIO_EXTENSIONS:
        found.add("audio_transcript_content")
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return found
    return found | _categories_in_text(text)


def scan(roots: list[Path], label: str) -> int:
    existing_roots = [root for root in roots if root.is_dir()]
    for root in roots:
        if root not in existing_roots:
            print(f"{label}: no evidence at {root}, skipping", file=sys.stderr)

    if not existing_roots:
        print(
            f"error: {label}: none of the requested evidence roots exist: "
            + ", ".join(str(root) for root in roots),
            file=sys.stderr,
        )
        return 1

    findings: list[tuple[Path, str]] = []
    scanned = 0
    for root in existing_roots:
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            scanned += 1
            for category in sorted(_categories_for_file(file_path)):
                findings.append((file_path, category))

    if findings:
        for file_path, category in findings:
            # Path and category only: never the matched text itself.
            print(f"error: {label}: {file_path} contains a {category} value", file=sys.stderr)
        categories = sorted({category for _, category in findings})
        print(
            f"error: {label}: privacy scan found {len(findings)} issue(s) "
            f"across {len({path for path, _ in findings})} file(s): "
            + ", ".join(categories),
            file=sys.stderr,
        )
        return 1

    print(f"{label}: privacy scan passed for {scanned} file(s) in {', '.join(str(r) for r in existing_roots)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        action="append",
        help="publishable evidence directory to scan recursively (repeatable)",
    )
    parser.add_argument("--label", required=True, help="layer label for messages")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return scan(args.path, args.label)


if __name__ == "__main__":
    raise SystemExit(main())
