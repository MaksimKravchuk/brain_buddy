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
import json
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

# Mirrors scanner._TRANSCRIPT_FIELD / scanner._TASK_CONTENT_FIELD, including
# capturing the value (group 3) so an already-empty field can be recognized
# and left untouched instead of overrunning into a sibling field — see
# scanner._has_non_empty_field_match for why the value must be matched
# lazily and zero-width-permitting (`*?`) rather than "one or more". Group 1
# captures the backslash run (if any) escaping this field's own quotes, so a
# field nested inside another JSON string is matched — and redacted back to
# the same escaping depth — not just a flat top-level one. Group 2 captures
# the field name for the replacement below.
_TRANSCRIPT_FIELD_SUB = re.compile(
    r"(\\*)\"("
    + "|".join(scanner._TRANSCRIPT_FIELD_NAMES)
    + r")\1\"\s*:\s*\1\"((?:[^\"\\]|\\.)*?)\1\""
)
_TASK_CONTENT_FIELD_SUB = re.compile(
    r"(\\*)\"("
    + "|".join(scanner._TASK_CONTENT_FIELD_NAMES)
    + r")\1\"\s*:\s*\1\"((?:[^\"\\]|\\.)*?)\1\""
)


def _redact_credential(match: re.Match[str]) -> str:
    matched = match.group(0)
    if matched.startswith('"session_token"'):
        return f'"session_token": "{_REDACTED_CREDENTIAL}"'
    return _REDACTED_CREDENTIAL


def _redact_field(match: re.Match[str]) -> str:
    # Empty the value but keep the real key and valid JSON `"key": "value"`
    # shape; an empty string is not itself flagged by the task_content /
    # audio_transcript_content checks. The escape prefix captured in group 1
    # (empty for a flat field, one or more backslashes when the field was
    # serialized inside another JSON string) is echoed back around every
    # quote, so a nested occurrence redacts to a validly re-escaped empty
    # string instead of breaking out of its enclosing JSON string value.
    escape, name = match.group(1), match.group(2)
    return f'{escape}"{name}{escape}": {escape}"{escape}"'


def _redact_non_empty_fields(pattern: re.Pattern[str], text: str) -> tuple[str, bool]:
    """Redact only matches whose captured value (group 3) is non-empty.

    The pattern accepts an empty value so it can correctly recognize a
    field's own (possibly immediately-adjacent) closing quote as its match
    boundary instead of overrunning into a sibling field — see
    scanner._has_non_empty_field_match. An already-empty field carries
    nothing to redact, and rewriting it to the same text would still be
    reported as "sanitized" by a naive subn() count, so it is left
    byte-for-byte untouched here instead.
    """

    pieces: list[str] = []
    last_end = 0
    changed = False
    for match in pattern.finditer(text):
        if not match.group(3):
            continue
        pieces.append(text[last_end : match.start()])
        pieces.append(_redact_field(match))
        last_end = match.end()
        changed = True
    pieces.append(text[last_end:])
    return "".join(pieces), changed


def _redact_plain_text(text: str) -> tuple[str, set[str]]:
    """Redact every ADR-0008 leak category from non-JSON decoded text."""

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

    text, changed = _redact_non_empty_fields(_TRANSCRIPT_FIELD_SUB, text)
    if changed:
        categories.add("audio_transcript_content")
    text, changed = _redact_non_empty_fields(_TASK_CONTENT_FIELD_SUB, text)
    if changed:
        categories.add("task_content")

    return text, categories


def _redact_json_value(value: object) -> tuple[object, set[str]]:
    """Redact parsed JSON while preserving every enclosing serialization layer."""

    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        categories: set[str] = set()
        for key, child in value.items():
            if isinstance(key, str) and isinstance(child, str) and child:
                if key == "session_token" and len(child) >= 20:
                    redacted[key] = _REDACTED_CREDENTIAL
                    categories.add("credential")
                    continue
                if key in scanner._TRANSCRIPT_FIELD_NAMES:
                    redacted[key] = ""
                    categories.add("audio_transcript_content")
                    continue
                if key in scanner._TASK_CONTENT_FIELD_NAMES:
                    redacted[key] = ""
                    categories.add("task_content")
                    continue
            redacted_child, child_categories = _redact_json_value(child)
            redacted[key] = redacted_child
            categories |= child_categories
        return redacted, categories
    if isinstance(value, list):
        redacted_items: list[object] = []
        categories: set[str] = set()
        for child in value:
            redacted_child, child_categories = _redact_json_value(child)
            redacted_items.append(redacted_child)
            categories |= child_categories
        return redacted_items, categories
    if isinstance(value, str):
        try:
            nested = json.loads(value)
        except json.JSONDecodeError:
            return _redact_plain_text(value)
        if isinstance(nested, (dict, list)):
            redacted_nested, categories = _redact_json_value(nested)
            return json.dumps(redacted_nested, ensure_ascii=False), categories
        return _redact_plain_text(value)
    return value, set()


def redact_text(text: str) -> tuple[str, set[str]]:
    """Redact text, parsing JSON first to preserve nested JSON-string values."""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _redact_plain_text(text)
    redacted, categories = _redact_json_value(payload)
    return json.dumps(redacted, ensure_ascii=False), categories


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
