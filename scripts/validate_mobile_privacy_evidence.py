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
# just long free text, so this must not require a minimum length. The name
# tuple is exposed (not just the compiled pattern) so sanitize_privacy_evidence.py
# can redact by the same field names instead of duplicating this list.
#
# `(\\*)` captures however many backslashes escape this field's own quotes:
# zero for a flat top-level field, or one-or-more when the whole object has
# been JSON-serialized into a string and embedded inside another JSON value
# (e.g. a step parameter or log line echoing a task/transcript payload as
# text) — a raw-text scan sees that nesting as literal `\"body\"`, not `"body"`.
# The same backslash run is required at all three other quote positions via
# `\1`, so this only fires on a structurally consistent field, not an
# accidental backslash run. The value body (captured, so callers can check
# it is actually non-empty — see _has_non_empty_field_match below) is
# matched lazily (`*?`, stopping at the first `\1"` it can reach) rather than
# greedily: at nesting depth greater than zero, every sibling key/value in
# the same enclosing string also delimits itself with the identical `\1"`
# escape sequence, so a greedy (or "one-or-more") match would either swallow
# through a nested sibling field (e.g. a `transcript` field immediately
# following `body` in the same object) via the `\\.` escaped-char
# alternative, or — for a field whose own value is legitimately empty —
# overshoot its own (immediately adjacent) closing quote entirely and latch
# onto a sibling field's quote instead, instead of stopping at this field's
# own closing quote.
_TRANSCRIPT_FIELD_NAMES = ("transcript", "transcriptText", "rawTranscript")
_TRANSCRIPT_FIELD = re.compile(
    r"(\\*)\"(?:" + "|".join(_TRANSCRIPT_FIELD_NAMES) + r")\1\"\s*:\s*\1\"((?:[^\"\\]|\\.)*?)\1\""
)

# Real Task/TaskComment wire field names (backend/app/schemas/tasks.py:
# title, details; TaskCommentDocument.body). These keys are distinctive
# enough on their own that even an ordinary short value ("buy milk") is a
# leak signal, not just a long one. Exposed as a name tuple for the same
# reason as _TRANSCRIPT_FIELD_NAMES above; same escaped-nesting handling as
# _TRANSCRIPT_FIELD above.
_TASK_CONTENT_FIELD_NAMES = ("title", "details", "body")
_TASK_CONTENT_FIELD = re.compile(
    r"(\\*)\"(?:" + "|".join(_TASK_CONTENT_FIELD_NAMES) + r")\1\"\s*:\s*\1\"((?:[^\"\\]|\\.)*?)\1\""
)


def _has_non_empty_field_match(pattern: re.Pattern[str], text: str) -> bool:
    """True if `pattern` (one of the two field patterns above) finds a field
    whose captured value is actually non-empty.

    The patterns themselves must accept an empty value (`*?`, not `+?`) so
    that a genuinely empty field's own closing quote — sitting immediately
    after its opening one — is recognized as the match boundary instead of
    being skipped past in search of *some* non-empty span (which, for an
    escaped/nested field, is reachable only by overrunning into a sibling
    field). Filtering on the captured group here, rather than requiring
    non-empty content in the pattern, is what keeps an already-empty field
    (e.g. post-sanitization, or a fixture asserting empty values are
    allowed) from being reported as a leak.
    """

    return any(match.group(2) for match in pattern.finditer(text))

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
    if (
        _AUDIO_DATA_URI.search(text)
        or _AUDIO_PATH.search(text)
        or _has_non_empty_field_match(_TRANSCRIPT_FIELD, text)
    ):
        found.add("audio_transcript_content")
    if _has_non_empty_field_match(_TASK_CONTENT_FIELD, text):
        found.add("task_content")
    return found


# Allure attachments can be nested under arbitrary directories, so the
# complete Allure root is treated as capture evidence. The older explicit
# screenshot/crash roots remain fail-closed as well, as do the Playwright
# HTML report and its raw test-results sibling: both can carry
# failure-only PNG screenshots, .webm videos, and .zip traces that are
# exactly the kind of capture/attachment evidence this scan exists to gate,
# and being binary they cannot be verified clean by the text-content checks
# below. Other CI roots may carry normal binary build assets; their text
# content is still scanned when decodable.
_FAIL_CLOSED_BINARY_ROOT_NAMES = {
    "allure-results",
    "screenshots",
    "crash-artifacts",
    "playwright-report",
    "test-results",
}


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
