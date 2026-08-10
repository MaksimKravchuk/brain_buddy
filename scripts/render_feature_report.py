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

    lines = [
        "### 5. What review found\n",
        f"**Verdict**: `{status}`  ",
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
