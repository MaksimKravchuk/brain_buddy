"""Contract tests for scripts/extract_staged_feature_flags.py.

The deploy workflow feeds this parser the PREVIOUS revision of itself and
restages whatever it prints before rolling an image back, so a wrong or
guessed answer would be applied to production at its worst moment. Every case
below therefore pins the fail-closed direction: anything but exactly one
well-formed, non-empty, duplicate-free assignment must print nothing on stdout
and exit non-zero, and no diagnostic may echo a flag name, state or value —
the caller masks the captured string and must be able to trust that the
failure path never leaked it first.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("extract_staged_feature_flags.py")

_SPEC = importlib.util.spec_from_file_location("extract_staged_feature_flags", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
extract_staged_flags = _MODULE.extract_staged_flags
ExtractionError = _MODULE.ExtractionError

AUTHORIZED = "delivery_canary=internal"


def _workflow(staged: str, *, extra: str = "") -> str:
    """A minimal stand-in for the staging step's shell line."""

    return (
        "      - name: Stage the smoke identity and feature-flag rollout\n"
        "        run: |\n"
        "          flyctl secrets set --stage --app app \\\n"
        f'            BRAIN_BUDDY_FEATURE_FLAGS="{staged}"\n' + extra
    )


def _run(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class ExtractStagedFeatureFlagsTest(unittest.TestCase):
    def test_script_exists(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "extract_staged_feature_flags.py must exist")

    def test_extracts_the_single_staged_rollout(self) -> None:
        self.assertEqual(extract_staged_flags(_workflow(AUTHORIZED)), AUTHORIZED)

    def test_cli_prints_the_rollout_and_exits_zero(self) -> None:
        result = _run(_workflow(AUTHORIZED))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), AUTHORIZED)

    def test_the_real_deploy_workflow_yields_its_authorized_rollout(self) -> None:
        """The parser must agree with the workflow the repository ships.

        This is the revision a rollback from the NEXT release will read, so a
        parser that cannot read it would fail that deploy before any mutation.
        """

        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "deploy-fly-production.yml"
        )
        self.assertEqual(
            extract_staged_flags(workflow.read_text(encoding="utf-8")), AUTHORIZED
        )

    def test_a_comment_naming_the_variable_is_ignored(self) -> None:
        """Prose about the rollout must not be mistaken for the rollout."""

        commented = (
            '      # a manual BRAIN_BUDDY_FEATURE_FLAGS="stale_flag=on" is reverted\n'
            + _workflow(AUTHORIZED)
        )
        self.assertEqual(extract_staged_flags(commented), AUTHORIZED)

    def _assert_rejected(self, payload: str) -> str:
        with self.assertRaises(ExtractionError) as caught:
            extract_staged_flags(payload)
        result = _run(payload)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "", "nothing may be captured")
        return f"{caught.exception} {result.stderr}"

    def test_a_missing_assignment_is_rejected(self) -> None:
        self._assert_rejected("      - name: Stage nothing\n        run: echo hi\n")

    def test_a_second_declared_assignment_is_rejected(self) -> None:
        """Two declarations make "the" rollout ambiguous; guessing is not an
        option when the answer is restaged onto production."""

        self._assert_rejected(
            _workflow(AUTHORIZED, extra=_workflow("delivery_canary=off"))
        )

    def test_the_rollback_restore_line_is_not_a_second_declaration(self) -> None:
        """The rollback step assigns the variable too, from an expansion.

        Every revision from this one on contains both lines, so the parser has
        to read the literal declaration and ignore the restore that re-applies
        an already-captured value.
        """

        restoring = _workflow(
            AUTHORIZED,
            extra=(
                "      - name: Roll back to the captured images and verify\n"
                "        run: |\n"
                "          flyctl secrets set --stage --app app \\\n"
                '            BRAIN_BUDDY_FEATURE_FLAGS="${PREVIOUS_FEATURE_FLAGS}"\n'
            ),
        )
        self.assertEqual(extract_staged_flags(restoring), AUTHORIZED)

    def test_an_interpolated_rollout_declares_nothing(self) -> None:
        """A rollout that is not a literal cannot be read from the revision, so
        it fails closed rather than capturing an unexpanded expression."""

        self._assert_rejected(_workflow("${SOME_ROLLOUT}"))
        self._assert_rejected(_workflow("delivery_canary=${SOME_STATE}"))

    def test_an_empty_value_is_rejected(self) -> None:
        for staged in ("", "   ", ","):
            with self.subTest(staged=staged):
                self._assert_rejected(_workflow(staged))

    def test_a_malformed_entry_is_rejected(self) -> None:
        for staged in (
            "delivery_canary",
            "delivery_canary=",
            "=internal",
            "delivery_canary=internal,voice_brain_dump",
        ):
            with self.subTest(staged=staged):
                self._assert_rejected(_workflow(staged))

    def test_a_repeated_flag_name_is_rejected(self) -> None:
        """Duplicates disagree about the state, so there is no single answer."""

        self._assert_rejected(_workflow("admin_portal=internal,admin_portal=off"))

    def test_diagnostics_never_echo_the_rollout(self) -> None:
        """Every failure message must stay positional.

        The caller masks the captured string only after the parser returns, so
        a diagnostic that quoted the value would have already printed it.
        """

        secretish = "delivery_canary=internal,admin_portal=internal,admin_portal=on"
        for payload in (
            _workflow(secretish),
            _workflow(secretish, extra=_workflow(secretish)),
            _workflow("delivery_canary"),
        ):
            with self.subTest(payload=payload):
                message = self._assert_rejected(payload)
                leaks = [secretish, *secretish.split(","), "delivery_canary"]
                for leak in leaks:
                    self.assertNotIn(leak, message, f"{leak!r} leaked into a diagnostic")


if __name__ == "__main__":
    unittest.main()
