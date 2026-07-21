#!/usr/bin/env python3
"""Redact ADR-0008 privacy-leak categories from publishable generated evidence.

CI generates backend/frontend/Playwright/mobile Allure results, bundles, and
logs that can legitimately end up carrying credential, email, absolute-path,
audio/transcript, or Task/TaskComment content values (e.g. voice brain-dump or
task fixtures echoed into a step description or log line). Rather than simply
failing the run, this script redacts every category
``validate_mobile_privacy_evidence.py`` detects, in place, on the same
evidence roots — so it must run immediately before that scanner at every
evidence layer (backend/frontend/Playwright/mobile), after taxonomy/result
validation has already read the untouched originals.

It only ever touches *decodable text* files: an unreadable binary attachment
(a screenshot, an audio recording, a crash dump, a Playwright trace/video) is
left completely untouched, since redaction cannot make it verifiably clean —
the scanner must and does keep failing closed on those. Redaction never
prints a matched value; only per-category counts are reported, mirroring the
scanner's own diagnostic-safe output.

Uses only the Python standard library, and imports its sibling
``validate_mobile_privacy_evidence.py`` for the category patterns and field
names, so the two scripts cannot silently drift out of sync on what counts as
a leak.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import validate_mobile_privacy_evidence as scanner

_REDACTED_CREDENTIAL = "REDACTED_CREDENTIAL"
_REDACTED_EMAIL = "REDACTED_EMAIL"
_REDACTED_PATH = "/REDACTED_PATH/"
# Deliberately not 64 hex characters: an all-zero 64-char replacement would
# still itself match scanner._CONTENT_HASH and be reported as a fresh leak.
_REDACTED_HASH = "REDACTED_CONTENT_HASH"
_REDACTED_AUDIO = "REDACTED_AUDIO"

# A superset of scanner._AUDIO_DATA_URI that also consumes the base64 payload:
# the scanner only needs to detect the "data:audio/...;base64," marker, but
# redacting just that prefix would leave the actual raw audio bytes (the
# payload) sitting right behind it — still a leak.
_AUDIO_DATA_URI_WITH_PAYLOAD = re.compile(
    r"data:audio/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]*"
)

_TRANSCRIPT_FIELD_SUB = re.compile(
    r"\"("
    + "|".join(scanner._TRANSCRIPT_FIELD_NAMES)
    + r")\"\s*:\s*\"(?:[^\"\\]|\\.)+\""
)
_TASK_CONTENT_FIELD_SUB = re.compile(
    r"\"("
    + "|".join(scanner._TASK_CONTENT_FIELD_NAMES)
    + r")\"\s*:\s*\"(?:[^\"\\]|\\.)+\""
)


def _redact_credential(match: re.Match[str]) -> str:
    matched = match.group(0)
    if matched.startswith('"session_token"'):
        return f'"session_token": "{_REDACTED_CREDENTIAL}"'
    return _REDACTED_CREDENTIAL


def _redact_field(match: re.Match[str]) -> str:
    # Empty the value but keep the real key and valid JSON `"key": "value"`
    # shape; an empty string is not itself flagged by the task_content /
    # audio_transcript_content checks.
    return f'"{match.group(1)}": ""'


def redact_text(text: str) -> tuple[str, set[str]]:
    """Redact every ADR-0008 leak category from decoded text.

    Returns the redacted text and the set of category names that fired, for
    diagnostic-safe reporting (never the matched values themselves).
    """

    categories: set[str] = set()

    def apply(pattern: re.Pattern[str], repl: object, category: str, value: str) -> str:
        new_value, count = pattern.subn(repl, value)
        if count:
            categories.add(category)
        return new_value

    text = apply(scanner._CREDENTIAL, _redact_credential, "credential", text)
    text = apply(scanner._EMAIL, _REDACTED_EMAIL, "email", text)
    text = apply(scanner._ABSOLUTE_PATH, _REDACTED_PATH, "absolute_path", text)
    text = apply(scanner._CONTENT_HASH, _REDACTED_HASH, "content_hash", text)
    text = apply(
        _AUDIO_DATA_URI_WITH_PAYLOAD, _REDACTED_AUDIO, "audio_transcript_content", text
    )
    text = apply(scanner._AUDIO_PATH, _REDACTED_AUDIO, "audio_transcript_content", text)
    text = apply(_TRANSCRIPT_FIELD_SUB, _redact_field, "audio_transcript_content", text)
    text = apply(_TASK_CONTENT_FIELD_SUB, _redact_field, "task_content", text)

    return text, categories


def sanitize(roots: list[Path], label: str) -> int:
    existing_roots = [root for root in roots if root.is_dir()]
    for root_index, root in enumerate(roots, start=1):
        if root not in existing_roots:
            print(
                f"{label}: requested evidence root #{root_index} is missing, skipping",
                file=sys.stderr,
            )

    if not existing_roots:
        print(f"{label}: no evidence roots exist, nothing to sanitize")
        return 0

    sanitized_files = 0
    scanned_files = 0
    categories_seen: set[str] = set()
    for root in existing_roots:
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            # Audio files are the leak in their entirety; there is no text
            # content to redact them down to, and they must keep failing the
            # scanner closed (ADR-0008).
            if file_path.suffix.lower() in scanner._AUDIO_EXTENSIONS:
                continue
            try:
                original = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                # Binary attachments are left untouched; the scanner remains
                # fail-closed on anything it cannot decode.
                continue
            scanned_files += 1
            redacted, categories = redact_text(original)
            if categories:
                file_path.write_text(redacted, encoding="utf-8")
                sanitized_files += 1
                categories_seen |= categories

    if sanitized_files:
        print(
            f"{label}: sanitized {sanitized_files} of {scanned_files} text file(s) across "
            f"{len(existing_roots)} evidence root(s); redacted categories: "
            + ", ".join(sorted(categories_seen))
        )
    else:
        print(
            f"{label}: no redactable content found in {scanned_files} text file(s) across "
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
        help="publishable evidence directory to sanitize recursively (repeatable)",
    )
    parser.add_argument("--label", required=True, help="layer label for messages")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return sanitize(args.path, args.label)


if __name__ == "__main__":
    raise SystemExit(main())
