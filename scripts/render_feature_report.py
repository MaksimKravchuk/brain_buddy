#!/usr/bin/env python3
"""Render the end-to-end delivery report for a feature.

The human handed over an abstract ask and has not watched the stages since.
This aggregates what is on disk into one document they can read.

Design rule: **never invent a value.** Every field is either read from an
artifact or reported as absent. A stage that did not run is printed as "not
run", never omitted — an omitted stage reads as a completed one, and that is
exactly the misreport this whole pipeline exists to prevent.

    python3 scripts/render_feature_report.py specs/006-example
    python3 scripts/render_feature_report.py specs/006-example --stdout
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / ".specify" / "workflows" / "runs"

ABSENT = "_not run_"

# Absent, these keys mean the campaign never measured its own provenance. That
# is reported as unknown, never as a clean panel.
PROVENANCE_KEYS = (
    "degraded_lenses",
    "oracle_unknown_lenses",
    "panel_correlated",
    "panel_oracles",
    "panel_providers",
    "single_provider_panel",
)

# `architect_action` is the next action with panel notes appended. This report
# renders those notes from the structured fields they were built from, so the
# notes are cut here to keep the same degradation from being printed twice.
NEXT_ACTION_NOTES = (
    " Panel note: ",
    " Provenance note: ",
    " Every lens that produced evidence ran on one provider",
)

DEFINITION_RE = re.compile(r"^\s*[-*]\s*\*\*((?:FR|SC)-\d+)\*\*", re.MULTILINE)
SCREEN_ID_RE = re.compile(r"\b([DM]-\d{2})\b")
VERDICT_RE = re.compile(r"\*\*VERDICT\*\*:\s*(\w+)|^VERDICT:\s*(\w+)", re.MULTILINE)


def read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def latest_review_summary(feature_dir: Path) -> tuple[Path, dict[str, Any]] | None:
    """The most recent campaign summary **for this feature**.

    Runs live in one flat directory shared by every feature, so picking the
    globally newest summary would splice another feature's verdict, findings
    and product decisions into this report — the precise misreport this module
    exists to prevent. `preflight` records `feature_dir` in
    `planning-context.json`; a run whose context is missing or names a
    different feature is not this feature's evidence and is skipped.
    """
    if not RUNS_DIR.is_dir():
        return None

    wanted = feature_dir.resolve()
    candidates = sorted(
        RUNS_DIR.glob("*/planning-review-summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        context_path = candidate.parent / "planning-context.json"
        if not context_path.is_file():
            continue
        try:
            context = json.loads(context_path.read_text(encoding="utf-8"))
            if Path(str(context.get("feature_dir", ""))).resolve() != wanted:
                continue
            return candidate, json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return None


def git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, text=True, capture_output=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def section_intake(feature_dir: Path) -> str:
    text = read(feature_dir / "intake.md")
    if text is None:
        return (
            "### 1-2. The ask and what was agreed\n\n"
            f"{ABSENT} — no `intake.md`. This feature did not go through "
            "`/speckit-interview`, so there is no record of the original ask, "
            "the agreed scope boundary, or the non-goals.\n"
        )
    lines = ["### 1-2. The ask and what was agreed\n", "`intake.md` is present.\n"]
    for heading in ("## The ask, as given", "## 4. Scope boundary", "## 3. Business objective and KPI"):
        block = extract_section(text, heading)
        if block:
            lines.append(f"**{heading.lstrip('# ').strip()}**\n\n{block}\n")
    return "\n".join(lines)


def extract_section(text: str, heading: str) -> str | None:
    start = text.find(heading)
    if start == -1:
        return None
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return rest[: end if end != -1 else None].strip() or None


def _role_list(value: object) -> list[str]:
    """Role names from a summary key that may be absent, null or malformed."""
    return [str(item) for item in value] if isinstance(value, list) else []


def _histogram(value: object) -> str | None:
    """`{"claude/sonnet": 3}` as ``claude/sonnet x3``, or nothing to print."""
    if not isinstance(value, dict) or not value:
        return None
    return ", ".join(f"`{key}` x{count}" for key, count in sorted(value.items()))


def _oracle_label(integration: object, model: object) -> str:
    """``integration/model``, without filling in a half that was not recorded."""
    if integration is None and model is None:
        return "not recorded"
    return f"`{integration or '?'}/{model or '?'}`"


def _digest(value: object) -> str:
    """A digest short enough to compare by eye, or the fact there is none."""
    text = str(value or "")
    return f"`{text[:12]}`" if text else "not recorded"


def panel_provenance(summary: dict[str, Any]) -> tuple[str, list[str]]:
    """The verdict caveat and the panel-composition block, from provenance only.

    ADR-0013 deliberately lets a degraded campaign reach `approved`, and rests
    that entire choice on the human seeing the degradation. Printing five
    verdicts without saying which oracles produced them makes a fully degraded
    single-provider panel indistinguishable from the configured one, which
    leaves that justification with nothing behind it — the report would be
    strictly less honest than when the missing lenses simply failed to run.

    Every key read here postdates summaries that may already be on disk, so an
    absent key is reported as unknown provenance and never as a clean panel.
    """
    stale = _role_list(summary.get("stale_reviews"))
    degraded = _role_list(summary.get("degraded_lenses"))
    unknown = _role_list(summary.get("oracle_unknown_lenses"))
    correlated = summary.get("panel_correlated")
    single_provider = summary.get("single_provider_panel")
    recorded = any(key in summary for key in PROVENANCE_KEYS)

    caveats: list[str] = []
    if stale:
        caveats.append("stale reviews")
    if not recorded:
        caveats.append("panel provenance not recorded")
    if degraded:
        caveats.append("degraded panel")
    if unknown:
        caveats.append("unknown provenance")
    if single_provider is True:
        caveats.append("single-provider panel")
    if correlated is True:
        caveats.append("correlated oracles")
    if not caveats:
        return "", []

    lines: list[str] = []
    # Stale reviews lead the block. `escalated` has four causes and the status
    # names none of them, and this is the cause a reader is least likely to
    # guess: the run context says the artifacts are unchanged because a second
    # preflight on the same run id rewrote it.
    if stale:
        lines.append(
            "**Reviews describing superseded artifacts**: "
            + ", ".join(f"`{role}`" for role in stale)
            + ". These lenses stamped a different artifacts digest than the "
            "artifacts now on disk, so their verdicts are about content that "
            "has since changed. A verdict on superseded content is not "
            "evidence about the artifacts as they now stand, and this is on "
            "its own an escalation cause.\n"
        )
        for role in stale:
            oracle = summary_oracle(summary, role) or {}
            lines.append(
                f"- `{role}`: reviewed "
                f"{_digest(oracle.get('artifacts_digest'))}, artifacts now "
                f"{_digest(summary.get('artifacts_digest'))}"
            )
        lines.append("")

    if not recorded:
        lines.append(
            "**Panel provenance**: not recorded. This summary predates "
            "per-lens oracle provenance, so which model reviewed this feature "
            "is unknown. Unknown is not the same as clean.\n"
        )
        return " — " + ", ".join(caveats), lines

    if degraded:
        lines.append(
            "**Lenses that ran on a fallback oracle**: "
            + ", ".join(f"`{role}`" for role in degraded)
            + ". These lenses produced a review, but not from the oracle they "
            "are configured for. The same verdict from this panel is a weaker "
            "result than it would be from a clean one.\n"
        )
        for role in degraded:
            oracle = summary_oracle(summary, role)
            if oracle is None:
                lines.append(
                    f"- `{role}`: listed as degraded, but no oracle was "
                    "recorded for it — what it ran on is unknown."
                )
                continue
            detail = (
                f"- `{role}`: configured "
                + _oracle_label(
                    oracle.get("configured_integration"), oracle.get("configured_model")
                )
                + ", actually ran "
                + _oracle_label(oracle.get("integration"), oracle.get("model"))
            )
            reason = oracle.get("reason")
            if isinstance(reason, str) and reason.strip():
                detail += f" — {reason.strip()}"
            lines.append(detail)
        lines.append("")

    if unknown:
        lines.append(
            "**Lenses with unknown provenance**: "
            + ", ".join(f"`{role}`" for role in unknown)
            + ". No oracle was recorded for these reviews, so which model "
            "produced them is unknown. An absent record is not evidence that a "
            "lens ran as configured.\n"
        )

    if single_provider is True:
        lines.append(
            "**The panel collapsed to a single provider.** Every lens whose "
            "provenance is known ran on one vendor, so its agreement is one "
            "provider's opinion counted several times, not several "
            "independent ones.\n"
        )
    elif single_provider is False:
        lines.append(
            "**Single-provider panel**: no — more than one provider is "
            "represented among the lenses whose provenance is known.\n"
        )

    # The histograms are printed with the correlation claim rather than instead
    # of it, so a reader can check the majority rather than trust it.
    if correlated is True:
        lines.append(
            "**Panel correlated**: yes — one oracle holds a strict majority of "
            "the lenses whose provenance is known.\n"
        )
    elif correlated is False:
        lines.append(
            "**Panel correlated**: no — no single oracle holds a strict "
            "majority. This does not cancel anything above it; correlation and "
            "degradation answer different questions.\n"
        )
    else:
        lines.append("**Panel correlated**: not recorded.\n")

    for label, key in (
        ("Panel oracles", "panel_oracles"),
        ("Panel providers", "panel_providers"),
    ):
        rendered = _histogram(summary.get(key))
        if rendered:
            lines.append(f"**{label}**: {rendered}\n")

    return " — " + ", ".join(caveats), lines


def next_action(summary: dict[str, Any]) -> str | None:
    """What the architect does next, with the appended panel notes cut off.

    Section 5 reported five verdicts and then stopped, so the one field saying
    what to do about them never reached the human at all. It cannot be printed
    whole: the notes appended to it restate the degradation this section
    already spells out from the structured fields, and a reader who meets the
    same paragraph twice learns to skip the place it is explained.

    Only the leading next action survives the cut. A field that is nothing but
    notes yields nothing rather than an invented instruction.
    """
    action = summary.get("architect_action")
    if not isinstance(action, str):
        return None
    cuts = [action.find(note) for note in NEXT_ACTION_NOTES]
    found = [index for index in cuts if index != -1]
    if found:
        action = action[: min(found)]
    return action.strip() or None


def summary_oracle(summary: dict[str, Any], role: str) -> dict[str, Any] | None:
    """The `oracle` block a reviewer entry carries, or None if it carries none."""
    reviewers = summary.get("reviewers")
    if not isinstance(reviewers, list):
        return None
    for reviewer in reviewers:
        if not isinstance(reviewer, dict) or str(reviewer.get("role")) != role:
            continue
        oracle = reviewer.get("oracle")
        return oracle if isinstance(oracle, dict) else None
    return None


def section_review(feature_dir: Path) -> str:
    found = latest_review_summary(feature_dir)
    if found is None:
        return (
            "### 5. What review found\n\n"
            f"{ABSENT} — no `planning-review-summary.json` under "
            "`.specify/workflows/runs/` whose `planning-context.json` names "
            f"`{feature_dir.name}`. This feature was not put through the "
            "five-lens review gate.\n"
        )
    path, summary = found
    status = summary.get("status", "unknown")
    reviewers = summary.get("reviewers", [])
    findings = summary.get("technical_findings", [])
    decisions = summary.get("product_decisions", [])

    by_severity: dict[str, int] = {}
    for finding in findings:
        key = str(finding.get("severity", "unknown"))
        by_severity[key] = by_severity.get(key, 0) + 1

    # The verdict is the one line every reader takes away, so it does not stand
    # alone when the panel behind it was degraded or was never measured.
    caveat, panel_lines = panel_provenance(summary)

    lines = [
        "### 5. What review found\n",
        f"**Verdict**: `{status}`{caveat}  ",
        f"**Risk**: `{summary.get('risk', 'unknown')}`  ",
        f"**Summary**: `{path.relative_to(REPO_ROOT)}`\n",
        "| reviewer | verdict | summary |",
        "|---|---|---|",
    ]
    for reviewer in reviewers:
        # Escape pipes so a reviewer summary cannot break the markdown table.
        cell = str(reviewer.get("summary", "")).replace("|", r"\|")
        lines.append(
            f"| `{reviewer.get('role', '?')}` | {reviewer.get('verdict', '?')} | {cell} |"
        )

    ran = {str(reviewer.get("role")) for reviewer in reviewers}
    expected = {
        "requirements-consistency",
        "architecture-consistency",
        "testability-evidence",
        "privacy-consent-security",
        "ux-accessibility-mobile",
    }
    missing = sorted(expected - ran)
    lines.append("")
    if missing:
        lines.append(
            f"**Lenses that did NOT run**: {', '.join(f'`{role}`' for role in missing)}. "
            "This was a partial campaign, not a clean one.\n"
        )
    else:
        lines.append("All five standard lenses ran.\n")

    # "All five ran" is true of a fully degraded panel too, so what they ran on
    # follows immediately rather than being buried after the findings.
    lines.extend(panel_lines)

    lines.append(
        "**Findings**: "
        + (
            ", ".join(f"{count} {severity}" for severity, count in sorted(by_severity.items()))
            or "none"
        )
        + "\n"
    )

    if decisions:
        lines.append(f"**Product decisions raised for the human**: {len(decisions)}\n")
        for decision in decisions:
            lines.append(
                f"- [{decision.get('category', '?')}] {decision.get('question', '?')}"
            )
        lines.append("")

    # A verdict with no next action leaves the reader to infer what a status
    # obliges them to do, which is the inference this report exists to remove.
    action = next_action(summary)
    if action:
        lines.append(f"**Next action for the architect**: {action}\n")

    if status == "founder-accepted":
        acceptance = summary.get("founder_acceptance")
        lines.append(
            "**Closed by founder acceptance.** This is not an approval; the "
            "full record follows.\n"
        )
        lines.append("```json")
        lines.append(json.dumps(acceptance, indent=2, ensure_ascii=False))
        lines.append("```\n")

    return "\n".join(lines)


def section_simple(title: str, feature_dir: Path, filename: str, note: str) -> str:
    text = read(feature_dir / filename)
    if text is None:
        return f"### {title}\n\n{ABSENT} — no `{filename}`. {note}\n"
    return f"### {title}\n\n`{filename}` is present ({len(text.splitlines())} lines).\n"


def render(feature_dir: Path) -> str:
    slug = feature_dir.name
    spec = read(feature_dir / "spec.md")
    design = read(feature_dir / "design.md")
    acceptance = read(feature_dir / "acceptance.md")

    requirement_ids = sorted(set(DEFINITION_RE.findall(spec))) if spec else []
    screen_ids = sorted(set(SCREEN_ID_RE.findall(design))) if design else []

    acceptance_verdict = ABSENT
    if acceptance:
        match = VERDICT_RE.search(acceptance)
        if match:
            acceptance_verdict = f"`{match.group(1) or match.group(2)}`"

    head_sha = git("rev-parse", "--short", "HEAD") or "unknown"
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"

    parts = [
        f"# Delivery report: {slug}\n",
        f"**Branch**: `{branch}`  **HEAD**: `{head_sha}`\n",
        "> Generated by `scripts/render_feature_report.py`. Every field below is "
        "read from an artifact on disk. A stage that did not run is marked "
        f"{ABSENT} rather than omitted.\n",
        "---\n",
        section_intake(feature_dir),
        "",
        "### 3-4. What was specified and designed\n",
        (
            f"**Spec**: `{slug}/spec.md` — {len(requirement_ids)} requirements "
            f"({', '.join(requirement_ids) if requirement_ids else 'none defined'})\n"
            if spec
            else f"**Spec**: {ABSENT}\n"
        ),
        (
            f"**Design**: `{slug}/design.md` — {len(screen_ids)} screen/state ids "
            f"({', '.join(screen_ids) if screen_ids else 'none assigned'})\n"
            if design
            else f"**Design**: {ABSENT} — no `design.md`. The plan could not have "
            "cited it, and acceptance has no screen ids to trace.\n"
        ),
        section_simple(
            "Technical plan",
            feature_dir,
            "plan.md",
            "Planning did not complete.",
        ),
        "",
        section_review(feature_dir),
        "",
        section_simple(
            "6. Task decomposition", feature_dir, "tasks.md", "No task breakdown exists."
        ),
        "",
        "### 7-8. What was built and verified\n",
        "_Fill from the implementer and verifier reports; this script cannot "
        "read a subagent transcript. Record commit SHAs, coverage against the "
        "95% floors, and which suites were skipped and why._\n",
        "",
        f"### 9. Acceptance\n\n**Verdict**: {acceptance_verdict}\n",
        (
            f"Matrix: `{slug}/traceability.md`\n"
            if (feature_dir / "traceability.md").is_file()
            else f"Matrix: {ABSENT}\n"
        ),
        "",
        "### 10. How it landed\n",
        "_Trunk candidate SHA and CI run URL, or the PR link for an ASK-class "
        "change. When the mainline SHIP/SHOW path was used, write: "
        '"No PR object exists (SHIP/SHOW verified-trunk landing)" — a blank '
        "field reads as an oversight._\n",
        "",
        "### 11. Still open\n",
        "_Deferred lanes, advisory findings not acted on, known gaps. Do not "
        "soften this section and do not omit it when it is uncomfortable._\n",
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_dir", help="path to specs/NNN-<slug>")
    parser.add_argument(
        "--stdout", action="store_true", help="print instead of writing report.md"
    )
    args = parser.parse_args(argv)

    feature_dir = Path(args.feature_dir)
    if not feature_dir.is_absolute():
        feature_dir = REPO_ROOT / feature_dir
    if not feature_dir.is_dir():
        raise SystemExit(f"{args.feature_dir}: not a directory")

    report = render(feature_dir)
    if args.stdout:
        print(report)
        return 0

    target = feature_dir / "report.md"
    target.write_text(report, encoding="utf-8")
    print(target.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
