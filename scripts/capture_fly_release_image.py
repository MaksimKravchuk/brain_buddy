#!/usr/bin/env python3
"""Extract the newest deployable release image from ``flyctl releases`` JSON.

Reads the output of the documented ``flyctl releases --app <app> --image
--json`` form on stdin and prints the first (newest) release image that is a
verifiable ``registry.fly.io/`` reference. Fly has shipped the image field
under different casings across flyctl versions (``image_ref``, ``ImageRef``,
``imageRef``), so keys are matched case- and underscore-insensitively.

A release is only a usable rollback target if it actually succeeded: when a
status field is present (any casing) its value must be a known successful
terminal state (``complete``, ``succeeded``, ``success``, case-insensitively)
or the release is skipped. A missing status field is tolerated for older
flyctl output.

On any malformed or unexpected input the script prints nothing and exits 0:
the deploy workflow treats an empty capture as a hard failure before any
remote mutation, so silence here fails closed there.
"""

from __future__ import annotations

import json
import sys

REQUIRED_PREFIX = "registry.fly.io/"
SUCCESSFUL_STATUSES = frozenset({"complete", "succeeded", "success"})


def _release_succeeded(release: dict) -> bool:
    """True when the release has no status field or a known successful one."""

    for key, value in release.items():
        if key.replace("_", "").lower() != "status":
            continue
        return (
            isinstance(value, str) and value.strip().lower() in SUCCESSFUL_STATUSES
        )
    return True


def extract_image(raw: str) -> str:
    try:
        releases = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(releases, list):
        return ""
    for release in releases:
        if not isinstance(release, dict):
            continue
        if not _release_succeeded(release):
            continue
        for key, value in release.items():
            if key.replace("_", "").lower() != "imageref":
                continue
            if isinstance(value, str) and value.startswith(REQUIRED_PREFIX):
                return value
    return ""


def main() -> int:
    image = extract_image(sys.stdin.read())
    if image:
        print(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
