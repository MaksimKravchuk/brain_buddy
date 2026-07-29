#!/usr/bin/env python3
"""Contract tests for scripts/capture_fly_release_image.py.

The parser consumes ``flyctl releases --image --json`` output on stdin and must
print the newest release image only when it is a verifiable
``registry.fly.io/`` reference, tolerating the documented JSON field casings
(``image_ref``, ``ImageRef``, ``imageRef``). Anything else prints nothing so
the deploy workflow's emptiness check fails closed before any mutation.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("capture_fly_release_image.py")

REGISTRY_IMAGE = "registry.fly.io/brain-buddy-backend:deployment-01H"
OLDER_IMAGE = "registry.fly.io/brain-buddy-backend:deployment-00G"


def _run(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    )


class CaptureFlyReleaseImageTest(unittest.TestCase):
    def test_script_exists(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "capture_fly_release_image.py must exist")

    def _assert_captures(self, payload: object, expected: str) -> None:
        result = _run(json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), expected)

    def _assert_empty(self, payload: str) -> None:
        result = _run(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_snake_case_image_ref(self) -> None:
        self._assert_captures([{"image_ref": REGISTRY_IMAGE}], REGISTRY_IMAGE)

    def test_pascal_case_image_ref(self) -> None:
        self._assert_captures([{"ImageRef": REGISTRY_IMAGE}], REGISTRY_IMAGE)

    def test_camel_case_image_ref(self) -> None:
        self._assert_captures([{"imageRef": REGISTRY_IMAGE}], REGISTRY_IMAGE)

    def test_first_valid_release_wins(self) -> None:
        payload = [
            {"ImageRef": REGISTRY_IMAGE},
            {"ImageRef": OLDER_IMAGE},
        ]
        self._assert_captures(payload, REGISTRY_IMAGE)

    def test_skips_releases_without_a_valid_image(self) -> None:
        payload = [
            "not-a-release",
            {"ImageRef": None},
            {"ImageRef": ""},
            {"Status": "failed"},
            {"image_ref": OLDER_IMAGE},
        ]
        self._assert_captures(payload, OLDER_IMAGE)

    def test_failed_release_is_skipped_in_favor_of_older_success(self) -> None:
        """A rollback target must be a release that actually succeeded."""

        payload = [
            {"Status": "failed", "ImageRef": REGISTRY_IMAGE},
            {"Status": "complete", "ImageRef": OLDER_IMAGE},
        ]
        self._assert_captures(payload, OLDER_IMAGE)

    def test_non_terminal_statuses_are_skipped(self) -> None:
        for status in ("running", "pending", "in_progress", "cancelled", "error"):
            with self.subTest(status=status):
                self._assert_empty(
                    json.dumps([{"status": status, "image_ref": REGISTRY_IMAGE}])
                )

    def test_successful_terminal_statuses_are_accepted_case_insensitively(
        self,
    ) -> None:
        for status in ("complete", "COMPLETE", "Succeeded", "success", " complete "):
            with self.subTest(status=status):
                self._assert_captures(
                    [{"Status": status, "ImageRef": REGISTRY_IMAGE}], REGISTRY_IMAGE
                )

    def test_status_key_casings_are_all_honored(self) -> None:
        for key in ("status", "Status", "STATUS"):
            with self.subTest(key=key):
                self._assert_empty(
                    json.dumps([{key: "failed", "ImageRef": REGISTRY_IMAGE}])
                )

    def test_present_but_non_string_status_is_skipped(self) -> None:
        """A present status that is not a known successful string fails closed."""

        for status in (None, 5, True, ["complete"]):
            with self.subTest(status=status):
                self._assert_empty(
                    json.dumps([{"Status": status, "ImageRef": REGISTRY_IMAGE}])
                )

    def test_absent_status_field_is_tolerated(self) -> None:
        """Older flyctl output without a status field remains usable."""

        self._assert_captures([{"ImageRef": REGISTRY_IMAGE}], REGISTRY_IMAGE)

    def test_rejects_non_fly_registry_images(self) -> None:
        self._assert_empty(json.dumps([{"ImageRef": "docker.io/library/nginx:1"}]))

    def test_rejects_lookalike_registry_prefix(self) -> None:
        self._assert_empty(
            json.dumps([{"ImageRef": "registry.fly.io.evil.example/app:1"}])
        )

    def test_invalid_json_prints_nothing(self) -> None:
        self._assert_empty("flyctl exploded {")

    def test_non_list_json_prints_nothing(self) -> None:
        self._assert_empty(json.dumps({"releases": [{"ImageRef": REGISTRY_IMAGE}]}))

    def test_empty_input_prints_nothing(self) -> None:
        self._assert_empty("")


if __name__ == "__main__":
    unittest.main()
