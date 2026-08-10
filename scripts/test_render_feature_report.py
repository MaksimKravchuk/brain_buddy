"""Contract tests for the end-to-end delivery report renderer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "render_feature_report.py"

STANDARD_ROLES = (
    "requirements-consistency",
    "architecture-consistency",
    "testability-evidence",
    "privacy-consent-security",
    "ux-accessibility-mobile",
)

CODEX_LENSES = ("requirements-consistency", "testability-evidence")


def load_module():
    spec = importlib.util.spec_from_file_location("render_feature_report", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reviewer(role: str, oracle: dict[str, Any] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "role": role,
        "verdict": "pass",
        "summary": f"{role} found nothing blocking.",
    }
    if oracle is not None:
        entry["oracle"] = oracle
    return entry


def clean_oracle(integration: str, model: str) -> dict[str, Any]:
    return {"integration": integration, "model": model, "degraded": False}


def fallback_oracle() -> dict[str, Any]:
    return {
        "integration": "claude",
        "model": "sonnet",
        "degraded": True,
        "reason": "the codex CLI is not installed",
        "configured_integration": "codex",
        "configured_model": "gpt-5.6-sol",
    }


# The three notes `aggregate_reviews` appends to the next action, verbatim.
PANEL_NOTE = (
    " Panel note: requirements-consistency ran on a fallback oracle because "
    "the configured runtime was unavailable. Those lenses are less independent "
    "than configured; treat their agreement with the other Claude lenses as "
    "weaker corroboration than it looks."
)
SINGLE_PROVIDER_NOTE = (
    " Every lens that produced evidence ran on one provider, so this panel's "
    "agreement is one vendor's opinion counted several times."
)
PROVENANCE_NOTE = (
    " Provenance note: testability-evidence carry no record of which runtime "
    "produced them. Their independence is unmeasured, not verified."
)
APPROVED_ACTION = (
    "Architect may finalize tasks.md, analyze, and the compact Kanban handoff."
)


class RendersSectionFive:
    """Renders section 5 against a throwaway repo root holding one run."""

    def setUp(self) -> None:
        self.module = load_module()

    def render(self, summary: dict[str, Any]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature_dir = root / "specs" / "006-example"
            feature_dir.mkdir(parents=True)
            run_dir = root / ".specify" / "workflows" / "runs" / "20260810-000000"
            run_dir.mkdir(parents=True)
            (run_dir / "planning-context.json").write_text(
                json.dumps({"feature_dir": str(feature_dir)}), encoding="utf-8"
            )
            (run_dir / "planning-review-summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
            with mock.patch.object(self.module, "REPO_ROOT", root), mock.patch.object(
                self.module, "RUNS_DIR", run_dir.parent
            ):
                return self.module.section_review(feature_dir)


class ReviewSectionTests(RendersSectionFive, unittest.TestCase):
    """The review section is where a degraded campaign is either seen or lost.

    ADR-0014 does not block the gate on degradation; it argues the human will
    read about it in the report. These tests are what makes that argument true.
    """

    def test_clean_panel_renders_exactly_as_before(self) -> None:
        """A panel that ran as configured gains nothing and loses nothing."""
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [
                    reviewer(role, clean_oracle("codex", "gpt-5.6-sol"))
                    if role in CODEX_LENSES
                    else reviewer(role, clean_oracle("claude", "opus"))
                    for role in STANDARD_ROLES
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": [],
                "oracle_unknown_lenses": [],
                "panel_correlated": False,
                "panel_oracles": {"codex/gpt-5.6-sol": 2, "claude/opus": 3},
                "panel_providers": {"codex": 2, "claude": 3},
                "single_provider_panel": False,
                "stale_reviews": [],
            }
        )

        self.assertIn("**Verdict**: `approved`  ", text)
        self.assertIn("All five standard lenses ran.", text)
        self.assertNotIn("fallback oracle", text)
        self.assertNotIn("unknown provenance", text)
        self.assertNotIn("Panel correlated", text)
        self.assertNotIn("Panel oracles", text)
        self.assertNotIn("superseded", text)

    def test_fully_degraded_single_provider_panel_is_not_reported_as_clean(self) -> None:
        """The regression: five reviews from one provider used to read clean.

        Before the fallback, a codex-less campaign at least said two lenses did
        not run. Once every lens produces a review, "all five ran" is the only
        sentence left, and it is true of the most degraded panel there is.
        """
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [
                    reviewer(role, fallback_oracle())
                    if role in CODEX_LENSES
                    else reviewer(role, clean_oracle("claude", "opus"))
                    for role in STANDARD_ROLES
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": list(CODEX_LENSES),
                "oracle_unknown_lenses": [],
                "panel_correlated": True,
                "panel_oracles": {"claude/opus": 3, "claude/sonnet": 2},
                "panel_providers": {"claude": 5},
                "single_provider_panel": True,
            }
        )

        self.assertNotIn("**Verdict**: `approved`  ", text)
        self.assertIn("degraded panel", text)
        self.assertIn("single-provider panel", text)
        self.assertIn("correlated oracles", text)
        self.assertIn("**Lenses that ran on a fallback oracle**", text)
        self.assertIn("`requirements-consistency`", text)
        self.assertIn("`testability-evidence`", text)
        self.assertIn("weaker result", text)
        self.assertIn("The panel collapsed to a single provider.", text)
        self.assertIn("**Panel oracles**: `claude/opus` x3, `claude/sonnet` x2", text)
        self.assertIn("**Panel providers**: `claude` x5", text)
        self.assertIn("All five standard lenses ran.", text)

    def test_degraded_lens_names_configured_versus_actual_oracle(self) -> None:
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [
                    reviewer("requirements-consistency", fallback_oracle()),
                    reviewer("architecture-consistency", clean_oracle("claude", "opus")),
                    reviewer("testability-evidence", clean_oracle("codex", "gpt-5.6-sol")),
                    reviewer("privacy-consent-security", clean_oracle("claude", "opus")),
                    reviewer("ux-accessibility-mobile", clean_oracle("claude", "sonnet")),
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": ["requirements-consistency"],
                "oracle_unknown_lenses": [],
                "panel_correlated": False,
                "panel_oracles": {
                    "claude/opus": 2,
                    "claude/sonnet": 2,
                    "codex/gpt-5.6-sol": 1,
                },
                "panel_providers": {"claude": 4, "codex": 1},
                "single_provider_panel": False,
            }
        )

        self.assertIn(
            "- `requirements-consistency`: configured `codex/gpt-5.6-sol`, "
            "actually ran `claude/sonnet` — the codex CLI is not installed",
            text,
        )
        self.assertIn("degraded panel", text)
        self.assertNotIn("single-provider panel", text)
        self.assertNotIn("correlated oracles", text)
        # A partially degraded panel is still not a clean one, so the "no strict
        # majority" fact must not read as an all-clear on its own.
        self.assertIn("does not cancel anything above it", text)

    def test_unknown_provenance_is_reported_as_unknown_not_clean(self) -> None:
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [
                    reviewer("requirements-consistency"),
                    reviewer("architecture-consistency", clean_oracle("claude", "opus")),
                    reviewer("testability-evidence"),
                    reviewer("privacy-consent-security", clean_oracle("claude", "opus")),
                    reviewer("ux-accessibility-mobile", clean_oracle("claude", "sonnet")),
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": [],
                "oracle_unknown_lenses": list(CODEX_LENSES),
                # `summarize` nulls the correlation once any lens is unknown,
                # because a majority over a subset is not a measured panel.
                "panel_correlated": None,
                "panel_oracles": {"claude/opus": 2, "claude/sonnet": 1},
                "panel_providers": {"claude": 3},
                "single_provider_panel": True,
            }
        )

        self.assertIn("**Lenses with unknown provenance**", text)
        self.assertIn("`requirements-consistency`, `testability-evidence`", text)
        self.assertIn("not evidence that a lens ran as configured", text)
        self.assertIn("unknown provenance", text)
        self.assertIn("**Panel correlated**: not recorded.", text)
        self.assertNotIn("**Verdict**: `approved`  ", text)
        self.assertNotIn("**Lenses that ran on a fallback oracle**", text)

    def test_degraded_lens_without_a_recorded_oracle_says_so(self) -> None:
        """`degraded_lenses` without the matching reviewer block invents nothing."""
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [reviewer(role) for role in STANDARD_ROLES],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": ["testability-evidence"],
            }
        )

        self.assertIn(
            "- `testability-evidence`: listed as degraded, but no oracle was "
            "recorded for it",
            text,
        )
        self.assertIn("**Panel correlated**: not recorded.", text)
        self.assertNotIn("**Panel oracles**", text)

    def test_summary_predating_provenance_is_reported_as_unrecorded(self) -> None:
        """Old summaries carry none of these keys and must not read as clean."""
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [reviewer(role) for role in STANDARD_ROLES],
                "technical_findings": [],
                "product_decisions": [],
            }
        )

        self.assertIn("**Verdict**: `approved` — panel provenance not recorded", text)
        self.assertIn("**Panel provenance**: not recorded.", text)
        self.assertIn("Unknown is not the same as clean.", text)

    def test_missing_lenses_still_reported_when_reviews_are_absent(self) -> None:
        """The pre-existing partial-campaign warning is untouched by provenance."""
        text = self.render(
            {
                "status": "escalated",
                "risk": "medium",
                "reviewers": [
                    reviewer(role, clean_oracle("claude", "opus"))
                    for role in STANDARD_ROLES[:3]
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": [],
                "oracle_unknown_lenses": [],
                "panel_correlated": True,
                "panel_oracles": {"claude/opus": 3},
                "panel_providers": {"claude": 3},
                "single_provider_panel": True,
            }
        )

        self.assertIn("**Lenses that did NOT run**", text)
        self.assertIn("`privacy-consent-security`", text)
        self.assertIn("`ux-accessibility-mobile`", text)
        self.assertIn("This was a partial campaign, not a clean one.", text)
        self.assertIn("The panel collapsed to a single provider.", text)


class StaleReviewTests(RendersSectionFive, unittest.TestCase):
    """`escalated` names none of its four causes; the report has to."""

    def test_stale_reviews_name_the_lenses_and_the_superseded_content(self) -> None:
        text = self.render(
            {
                "status": "escalated",
                "risk": "medium",
                "reviewers": [
                    reviewer(
                        role,
                        dict(
                            clean_oracle("claude", "opus"),
                            artifacts_digest=(
                                "0000oldoldold" if role in CODEX_LENSES else "ffffnewnewnew"
                            ),
                        ),
                    )
                    for role in STANDARD_ROLES
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": [],
                "oracle_unknown_lenses": [],
                "panel_correlated": True,
                "panel_oracles": {"claude/opus": 5},
                "panel_providers": {"claude": 5},
                "single_provider_panel": True,
                "stale_reviews": list(CODEX_LENSES),
                "artifacts_digest": "ffffnewnewnew",
                "artifacts_changed_since_preflight": True,
            }
        )

        self.assertIn("**Verdict**: `escalated` — stale reviews", text)
        self.assertIn("**Reviews describing superseded artifacts**", text)
        self.assertIn("`requirements-consistency`, `testability-evidence`", text)
        self.assertIn("this is on its own an escalation cause", text)
        self.assertIn(
            "- `requirements-consistency`: reviewed `0000oldoldol`, artifacts "
            "now `ffffnewnewne`",
            text,
        )

    def test_stale_reviews_survive_a_summary_with_no_provenance_keys(self) -> None:
        """Stale reviews are reported even when nothing else was measured."""
        text = self.render(
            {
                "status": "escalated",
                "risk": "medium",
                "reviewers": [reviewer(role) for role in STANDARD_ROLES],
                "technical_findings": [],
                "product_decisions": [],
                "stale_reviews": ["architecture-consistency"],
            }
        )

        self.assertIn(
            "**Verdict**: `escalated` — stale reviews, panel provenance not recorded",
            text,
        )
        self.assertIn("**Reviews describing superseded artifacts**", text)
        self.assertIn(
            "- `architecture-consistency`: reviewed not recorded, artifacts "
            "now not recorded",
            text,
        )
        self.assertIn("**Panel provenance**: not recorded.", text)


class NextActionTests(RendersSectionFive, unittest.TestCase):
    def test_next_action_renders_whole_when_no_notes_are_appended(self) -> None:
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [
                    reviewer(role, clean_oracle("claude", "opus"))
                    for role in STANDARD_ROLES
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": [],
                "oracle_unknown_lenses": [],
                "panel_correlated": False,
                "panel_oracles": {"claude/opus": 3, "codex/gpt-5.6-sol": 2},
                "panel_providers": {"claude": 3, "codex": 2},
                "single_provider_panel": False,
                "stale_reviews": [],
                "architect_action": APPROVED_ACTION,
            }
        )

        self.assertIn(f"**Next action for the architect**: {APPROVED_ACTION}", text)

    def test_appended_notes_are_cut_and_not_printed_twice(self) -> None:
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [
                    reviewer("requirements-consistency", fallback_oracle()),
                    reviewer("architecture-consistency", clean_oracle("claude", "opus")),
                    reviewer("testability-evidence"),
                    reviewer("privacy-consent-security", clean_oracle("claude", "opus")),
                    reviewer("ux-accessibility-mobile", clean_oracle("claude", "sonnet")),
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": ["requirements-consistency"],
                "oracle_unknown_lenses": ["testability-evidence"],
                "panel_correlated": None,
                "panel_oracles": {"claude/opus": 2, "claude/sonnet": 2},
                "panel_providers": {"claude": 4},
                "single_provider_panel": True,
                "stale_reviews": [],
                "architect_action": (
                    APPROVED_ACTION + PANEL_NOTE + SINGLE_PROVIDER_NOTE + PROVENANCE_NOTE
                ),
            }
        )

        self.assertIn(f"**Next action for the architect**: {APPROVED_ACTION}", text)
        self.assertNotIn("Panel note:", text)
        self.assertNotIn("Provenance note:", text)
        self.assertNotIn("one vendor's opinion counted several times", text)
        # Cutting the notes must not cost the reader the facts they carried.
        self.assertIn("**Lenses that ran on a fallback oracle**", text)
        self.assertIn("**Lenses with unknown provenance**", text)
        self.assertIn("The panel collapsed to a single provider.", text)

    def test_each_sentinel_is_cut_on_its_own(self) -> None:
        for note in (PANEL_NOTE, SINGLE_PROVIDER_NOTE, PROVENANCE_NOTE):
            with self.subTest(note=note[:24]):
                self.assertEqual(
                    self.module.next_action({"architect_action": APPROVED_ACTION + note}),
                    APPROVED_ACTION,
                )

    def test_action_without_any_note_is_returned_unchanged(self) -> None:
        self.assertEqual(
            self.module.next_action({"architect_action": APPROVED_ACTION}),
            APPROVED_ACTION,
        )

    def test_absent_malformed_or_note_only_action_yields_nothing(self) -> None:
        """Nothing is invented when there is no next action to report."""
        for summary in (
            {},
            {"architect_action": None},
            {"architect_action": ["not", "a", "string"]},
            {"architect_action": "   "},
            {"architect_action": PANEL_NOTE},
        ):
            with self.subTest(summary=summary):
                self.assertIsNone(self.module.next_action(summary))

    def test_no_next_action_line_when_the_field_is_absent(self) -> None:
        text = self.render(
            {
                "status": "approved",
                "risk": "medium",
                "reviewers": [
                    reviewer(role, clean_oracle("claude", "opus"))
                    for role in STANDARD_ROLES
                ],
                "technical_findings": [],
                "product_decisions": [],
                "degraded_lenses": [],
                "oracle_unknown_lenses": [],
                "panel_correlated": False,
                "panel_oracles": {"claude/opus": 3, "codex/gpt-5.6-sol": 2},
                "panel_providers": {"claude": 3, "codex": 2},
                "single_provider_panel": False,
                "stale_reviews": [],
            }
        )

        self.assertNotIn("**Next action for the architect**", text)


class PanelProvenanceTests(RendersSectionFive, unittest.TestCase):
    def test_clean_panel_produces_no_caveat_and_no_block(self) -> None:
        caveat, lines = self.module.panel_provenance(
            {
                "reviewers": [],
                "degraded_lenses": [],
                "oracle_unknown_lenses": [],
                "panel_correlated": False,
                "panel_oracles": {"codex/gpt-5.6-sol": 2, "claude/opus": 3},
                "single_provider_panel": False,
                "stale_reviews": [],
            }
        )

        self.assertEqual(caveat, "")
        self.assertEqual(lines, [])

    def test_absent_new_keys_do_not_crash_and_do_not_invent(self) -> None:
        caveat, lines = self.module.panel_provenance({"status": "approved"})

        self.assertIn("not recorded", caveat)
        self.assertEqual(len(lines), 1)

    def test_null_and_malformed_values_are_tolerated(self) -> None:
        """`panel_correlated` may be null, and old files may hold any shape."""
        caveat, lines = self.module.panel_provenance(
            {
                "reviewers": "not a list",
                "degraded_lenses": None,
                "oracle_unknown_lenses": ["ux-accessibility-mobile"],
                "panel_correlated": None,
                "panel_oracles": [],
                "panel_providers": {},
                "single_provider_panel": None,
                "stale_reviews": "not a list",
            }
        )

        self.assertEqual(caveat, " — unknown provenance")
        rendered = "\n".join(lines)
        self.assertIn("**Lenses with unknown provenance**", rendered)
        self.assertIn("**Panel correlated**: not recorded.", rendered)
        self.assertNotIn("**Panel oracles**", rendered)
        self.assertNotIn("**Panel providers**", rendered)


if __name__ == "__main__":
    unittest.main()
