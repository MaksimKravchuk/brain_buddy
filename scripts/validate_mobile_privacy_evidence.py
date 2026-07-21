#!/usr/bin/env python3
"""Scan publishable mobile CI evidence for privacy leaks (ADR-0008).

Before mobile logs, Allure results, screenshots, crash artifacts, bundles,
source maps, and build output are uploaded as CI artifacts, they must not
carry credential values, email values, raw audio/transcript content, task
content (Task/TaskComment title, details, or body text), absolute
developer/device paths, or content hashes. Any unreadable binary screenshot
or attachment anywhere under a publishable Allure root fails closed rather
than passing silently, since it cannot be verified clean — this is not limited
to directories named screenshots or crash-artifacts. Explicit screenshot and
crash-artifact roots also fail closed. Static build assets remain allowed:
they are bundled code, not capture/attachment evidence. ADR-0008 requires this
scan as a release gate; see "Verification / tests" item 7 in
``docs/decisions/0008-add-one-expo-mobile-client-over-opaque-sessions.md``.

This intentionally never prints the offending file's name or path, since a
malicious or fixture filename can itself carry the same value found in its
content; a finding names its category and a reproducible sorted-order
position instead. It uses only the Python standard library so it can run
before mobile or backend dependencies are installed.
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
# Any non-empty value under a transcript-shaped key is a leak signal: real
# voice brain-dump transcripts are ordinary short sentences ("buy milk"), not
# just long free text, so this must not require a minimum length.
_TRANSCRIPT_FIELD = re.compile(
    r"\"(?:transcript|transcriptText|rawTranscript)\"\s*:\s*\"(?:[^\"\\]|\\.)+\""
)

# Real Task/TaskComment wire field names (backend/app/schemas/tasks.py:
# title, details; TaskCommentDocument.body). These keys are distinctive
# enough on their own that even an ordinary short value ("buy milk") is a
# leak signal, not just a long one.
_TASK_CONTENT_FIELD = re.compile(
    r"\"(?:title|details|body)\"\s*:\s*\"(?:[^\"\\]|\\.)+\""
)

# Developer/device home directories, not the shared GitHub-hosted runner
# account, so a generic CI-produced ``/home/runner/...`` path in a source map
# does not fail the scan. Also covers native iOS (`/var/mobile/...`) and
# Android (`/data/user/0/...`) per-device absolute paths that can leak into
# crash artifacts or logs.
_ABSOLUTE_PATH = re.compile(
    r"/Users/[A-Za-z0-9_.\-]+/"
    r"|/home/(?!runner/)[A-Za-z0-9_.\-]+/"
    r"|[A-Za-z]:\\Users\\[A-Za-z0-9_.\-]+\\"
    r"|/var/mobile/[A-Za-z0-9_.\-]+/"
    r"|/data/user/0/[A-Za-z0-9_.\-]+/"
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


# Allure attachments can be nested under arbitrary directories, so the
# complete Allure root is treated as capture evidence. The older explicit
# screenshot/crash roots remain fail-closed as well. Other CI roots may carry
# normal binary build assets; their text content is still scanned when decodable.
_FAIL_CLOSED_BINARY_ROOT_NAMES = {"allure-results", "screenshots", "crash-artifacts"}


def _is_fail_closed_binary_root(root: Path) -> bool:
    # A scanned root passed as e.g. frontend/allure-results/vitest or
    # frontend/allure-results/playwright is still Allure capture evidence
    # even though its own leaf directory name ("vitest"/"playwright") is not
    # one of the explicit fail-closed names: any ancestor segment named
    # "allure-results" means every file beneath it is Allure evidence.
    return root.name in _FAIL_CLOSED_BINARY_ROOT_NAMES or "allure-results" in root.parts


def _categories_for_file(path: Path, *, fail_closed_binary: bool) -> set[str]:
    found: set[str] = set()
    if path.suffix.lower() in _AUDIO_EXTENSIONS:
        found.add("audio_transcript_content")
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        if fail_closed_binary:
            found.add("unreadable_binary_evidence")
        return found
    return found | _categories_in_text(text)


def scan(roots: list[Path], label: str) -> int:
    existing_roots = [root for root in roots if root.is_dir()]
    for root_index, root in enumerate(roots, start=1):
        if root not in existing_roots:
            print(
                f"{label}: requested evidence root #{root_index} is missing, skipping",
                file=sys.stderr,
            )

    if not existing_roots:
        print(
            f"error: {label}: none of the requested evidence roots exist "
            f"({len(roots)} requested)",
            file=sys.stderr,
        )
        return 1

    findings: list[tuple[Path, str]] = []
    # A finding is reported by its position in this deterministic sorted
    # listing, never by its name or path: a malicious or fixture filename can
    # itself carry the exact value its content matched (a credential, email,
    # or transcript text used as a filename), so printing the raw basename or
    # full path could leak it just as surely as printing the matched text
    # would. The (root, sorted index, total) triple is still reproducible —
    # rerun the same scan against the same evidence root and the Nth file in
    # sorted order is the offending file — without ever echoing its content.
    display_refs: dict[Path, str] = {}
    scanned = 0
    for root_index, root in enumerate(existing_roots, start=1):
        root_files = [p for p in sorted(root.rglob("*")) if p.is_file()]
        fail_closed_binary = _is_fail_closed_binary_root(root)
        for index, file_path in enumerate(root_files, start=1):
            scanned += 1
            display_refs[file_path] = (
                f"file #{index} of {len(root_files)} under evidence root #{root_index} (sorted order)"
            )
            for category in sorted(
                _categories_for_file(file_path, fail_closed_binary=fail_closed_binary)
            ):
                findings.append((file_path, category))

    if findings:
        for file_path, category in findings:
            # Reference and category only: never the matched text, nor the
            # file's own name or path.
            print(f"error: {label}: {display_refs[file_path]} contains a {category} value", file=sys.stderr)
        categories = sorted({category for _, category in findings})
        print(
            f"error: {label}: privacy scan found {len(findings)} issue(s) "
            f"across {len({path for path, _ in findings})} file(s): "
            + ", ".join(categories),
            file=sys.stderr,
        )
        return 1

    print(
        f"{label}: privacy scan passed for {scanned} file(s) across "
        f"{len(existing_roots)} evidence root(s)"
    )
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
