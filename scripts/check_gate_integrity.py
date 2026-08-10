#!/usr/bin/env python3
"""Stop an actor from silently weakening the gates it is judged by.

The delivery policy is blunt about this: *no actor may silently weaken its own
acceptance conditions, mandatory checks, permissions, or this agreement*. An
agent that can edit `aggregate_reviews`, widen the permission allowlist, or
drop a validator from `make check-specs` can quietly make itself pass.

This script cannot prevent those edits — nothing can, since the files must
stay editable. It removes the word **silently**, in two layers:

1. **Invariants** that must hold no matter what. These are not waivable: they
   assert the shape of the gate, not its bytes. Deleting the verdict check in
   the aggregator, or granting blanket `Bash` permission, fails here and no
   manifest update can quiet it.

2. **A hash manifest** of the guarded files. Any edit fails the check until
   `--update` is run, which puts the new hash in the diff where a reviewer
   sees it. Changing a gate stays possible; changing one unnoticed does not.

Layer 2 alone is defeated by updating the hash in the same commit, which is
exactly why layer 1 exists.

    python3 scripts/check_gate_integrity.py
    python3 scripts/check_gate_integrity.py --update    # deliberate re-record
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / ".specify" / "gate-integrity.json"

GUARDED_FILES: tuple[str, ...] = (
    "scripts/spec_kit_planning_review.py",
    "scripts/check_spec_kit_specs.py",
    "scripts/check_speckit_manifests.py",
    "scripts/check_requirement_coverage.py",
    "scripts/classify_path_risk.py",
    "scripts/check_gate_integrity.py",
    # Guarded from the moment they stopped being advisory: since ADR-0004's
    # promotion this script can fail a pull request, and this list decides which
    # modules it can fail one over. Editing either changes what "passing" means.
    "scripts/mutation_gate.py",
    "backend/mutation-enforced-scope.txt",
    ".claude/settings.json",
    ".specify/workflows/speckit/workflow.yml",
    ".specify/workflows/speckit/review.schema.json",
    ".specify/workflows/speckit/handoff.schema.json",
    ".specify/extensions.yml",
    "Makefile",
)


class Invariant:
    """A gate property that must hold regardless of how the file changes."""

    def __init__(self, path: str, name: str, why: str) -> None:
        self.path = path
        self.name = name
        self.why = why

    def check(self, text: str) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError


class MustMatch(Invariant):
    def __init__(self, path: str, name: str, pattern: str, why: str) -> None:
        super().__init__(path, name, why)
        self.pattern = re.compile(pattern, re.MULTILINE | re.DOTALL)

    def check(self, text: str) -> bool:
        return self.pattern.search(text) is not None


class MustNotMatch(Invariant):
    def __init__(self, path: str, name: str, pattern: str, why: str) -> None:
        super().__init__(path, name, why)
        self.pattern = re.compile(pattern, re.MULTILINE)

    def check(self, text: str) -> bool:
        return self.pattern.search(text) is None


INVARIANTS: tuple[Invariant, ...] = (
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "aggregation honors reviewer verdicts",
        r"verdicts\s*=\s*\{[^}]*review\[.verdict.\]",
        "The gate must read each reviewer's verdict, not only finding "
        "severity. Removing this reintroduces the defect where "
        "changes-required with only important findings became approved.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "changes-required blocks the gate",
        r'"changes-required"\s+in\s+verdicts',
        "A reviewer verdict of changes-required must block on its own.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "unknown risk defaults to medium",
        r'DEFAULT_RISK\s*=\s*"medium"',
        "An unclassifiable change takes the middle class. Defaulting to low "
        "would let the riskiest unknown work take the cheapest path.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "risk derivation can only raise the class",
        r'DERIVABLE_RISKS:\s*tuple\[str, \.\.\.\]\s*=\s*\("high",\)',
        "Derivation reads which paths the artifacts mention, and a mention is "
        "not a change. Letting it infer `low` produced a false low on an auth "
        "change that merely cited docs/auth.md. Lowering a class is an "
        "accountable human declaration, never a regex over prose.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "missing mandatory evidence escalates",
        r"if missing_roles:\s*\n\s*status\s*=\s*\"escalated\"",
        "Missing review evidence must escalate, never resolve to a pass.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "human sign-off is a run-bound record, not a caller flag",
        r"signoff_record\s*=\s*load_human_signoff\(",
        "A caller-controlled boolean lets the same automated actor that runs "
        "the campaign self-certify the human gate on exactly the ASK-class "
        "surfaces the gate protects. The sign-off must be a separate record "
        "bound to the run id and a digest of the reviewed artifacts.",
    ),
    MustNotMatch(
        ".specify/workflows/speckit/workflow.yml",
        "no caller-supplied human_signoff input",
        r"^\s{2}human_signoff:",
        "Re-introducing this input would let the campaign caller assert its own "
        "human approval.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "the artifact digest is recomputed, not trusted from preflight",
        r"current_digest\s*=\s*review_artifacts_digest\(feature_dir\)",
        "Comparing a sign-off against the digest stored at preflight defeats "
        "the mechanism with its own cache: edit the spec afterwards and the "
        "stale stored digest still matches, approving unreviewed content.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "artifact drift after preflight escalates",
        r"if artifacts_changed:\s*\n\s*status\s*=\s*\"escalated\"",
        "Reviews describe the artifacts as they stood when they ran. If those "
        "moved, every verdict in the run is about different content.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "high-risk handoffs require the sign-off record",
        r"if risk == HUMAN_SIGNOFF_REQUIRED_AT:\s*\n\s*if not isinstance\(signoff, dict\):",
        "Adding the shape to handoff.schema.json without checking it here left "
        "a CI-reachable bypass: a hand-written high-risk handoff marked "
        "approved validated with no approval record at all.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "founder acceptance is time-bounded",
        r"founder_acceptance\.expires_on",
        "A risk acceptance with no expiry is a permanent hole in the gate.",
    ),
    MustNotMatch(
        ".claude/settings.json",
        "no blanket shell permission",
        r'"Bash"\s*,|"Bash\(\*\)"|"Bash\(:\*\)"',
        "A wildcard Bash grant makes the allowlist decorative and lets an "
        "agent run anything, including the commands that weaken these gates.",
    ),
    MustNotMatch(
        ".claude/settings.json",
        "landing and push stay gated",
        r'"allow"[^]]*"Bash\(git push',
        "git push and trunk submission must never be pre-approved: landing is "
        "the one action an agent must not take unattended.",
    ),
    # Scoped to the recipe block (`check-specs:` followed by tab-indented
    # lines). A DOTALL `.*?` would happily match a mention anywhere later in
    # the file, so dropping the line from check-specs would still "pass" — a
    # guard that does not actually guard.
    MustMatch(
        "Makefile",
        "check-specs runs the spec and manifest guards",
        r"^check-specs:(?:\n\t[^\n]*)*?\n\tpython3 scripts/check_spec_kit_specs\.py"
        r"(?:\n\t[^\n]*)*?\n\tpython3 scripts/check_speckit_manifests\.py",
        "Dropping either validator from check-specs removes the only "
        "CI-enforced spec gate.",
    ),
    MustMatch(
        "Makefile",
        "check-specs runs this integrity guard",
        r"^check-specs:(?:\n\t[^\n]*)*?\n\tpython3 scripts/check_gate_integrity\.py",
        "The guard must run in CI, or it guards nothing.",
    ),
    MustMatch(
        "scripts/mutation_gate.py",
        "the mutation bar stays at 95%",
        r"DEFAULT_THRESHOLD\s*=\s*0\.95",
        "ADR-0004 set 95% and the enforced tier was calibrated against it. "
        "Lowering the constant is the cheapest way to make a failing gate "
        "pass, and it must not be possible to do it quietly.",
    ),
    MustMatch(
        "scripts/mutation_gate.py",
        "a campaign that checked nothing fails",
        r"if checked == 0:",
        "A campaign that mutates nothing reports a perfect score. Without "
        "this the gate passes hardest exactly when it ran least.",
    ),
    MustMatch(
        "scripts/mutation_gate.py",
        "the base revision comparison survives",
        r"base_checked and score < base_score",
        "ADR-0004 requirement 2. The absolute floor alone lets a module at "
        "99% shed four points one pull request at a time.",
    ),
    MustMatch(
        "backend/mutation-enforced-scope.txt",
        "the enforced tier keeps all six calibrated modules",
        r"(?m)^app/services/tree_service\.py$.*"
        r"^app/services/version_service\.py$.*"
        r"^app/services/relation_service\.py$.*"
        r"^app/repositories/tree\.py$.*"
        r"^app/repositories/version\.py$.*"
        r"^app/repositories/index\.py$",
        "ADR-0004 requirement 5: the allow-list changes only for a behavioural "
        "reason an ADR gives. Dropping a module is the other cheap way to make "
        "a failing gate pass, and it looks like housekeeping in a diff.",
    ),
    MustMatch(
        ".specify/workflows/speckit/review.schema.json",
        "both mandatory lenses stay in the role enum",
        r'"privacy-consent-security".*?"ux-accessibility-mobile"',
        "The privacy and UX lenses cover constitution principles I and V. "
        "Removing either leaves a principle with no reviewer.",
    ),
    # The fallback exists so an absent runtime cannot lock the gate shut. That
    # is only acceptable while the substitution stays visible: a fallback that
    # stops recording degradation is a panel silently running on one oracle
    # while reporting the diversity it was configured with.
    # Every pattern below is right-bounded to the enclosing function with
    # `(?:(?!\ndef ).)*?`. An unbounded DOTALL `.*?` runs to the end of the
    # file and happily terminates on an identical token in an unrelated
    # function — the exact hazard flagged for the Makefile invariants above,
    # and one these reintroduced on their first draft: deleting run_review's
    # own `raise` still matched `preflight`'s three hundred lines later.
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "a fallback oracle is recorded as degraded",
        r'def resolve_oracle\((?:(?!\ndef ).)*?"degraded":\s*True',
        "Substituting a reviewer runtime without marking it degraded hides a "
        "correlated panel behind a configuration that no longer describes it.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "both codex lenses keep a fallback",
        r'"fallback":\s*CODEX_FALLBACK(?:(?!\ndef ).)*?"fallback":\s*CODEX_FALLBACK',
        "Removing a fallback returns that lens to writing no review when its "
        "CLI is absent, which is the permanent `escalated` ADR-0014 removed.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "the harness stamps reviewer provenance",
        r'review\["oracle"\]\s*=\s*oracle',
        "Provenance must be written by the harness. Dropping the stamp leaves "
        "no record of which runtime produced a verdict.",
    ),
    # Guards the call site, not the resolver. `resolve_oracle` can be left
    # perfectly correct and its verdict overwritten one line later.
    MustNotMatch(
        "scripts/spec_kit_planning_review.py",
        "resolved provenance is not rewritten after the fact",
        r"oracle\s*=\s*\{\*\*oracle",
        "Rebuilding the oracle after resolution can flip `degraded` without "
        "touching the resolver any invariant is watching.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "degradation reaches the summary",
        r'summary\["degraded_lenses"\]\s*=\s*degraded',
        "A degradation recorded on the review but absent from the summary is "
        "invisible to every consumer of the gate. Bound to the collected list "
        "so assigning a constant empty list does not satisfy it.",
    ),
    # Anchored inside run_review on purpose, and bounded on both sides. The
    # first draft bounded only the left edge, so deleting run_review's raise
    # let the match run on to preflight's — seeing the hazard and fixing half
    # of it.
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "a failing reviewer is not routed to a fallback",
        r"def run_review\((?:(?!\ndef ).)*?if result\.returncode != 0:"
        r"(?:(?!\ndef ).)*?raise ReviewError",
        "Only an absent runtime may be substituted. Retrying a failed "
        "reviewer on another oracle launders a defect into a clean verdict.",
    ),
    # ADR-0014 trades blocking for visibility: a degraded campaign may reach
    # `approved` because the human will see the degradation. After that trade
    # the seeing happens here, so the renderer became load-bearing for the
    # decision not to block. Four invariants assert `summarize` *writes* the
    # facts; none asserted anything *reads* them, and the cheapest future edit
    # — keep the write, drop the render — restores the exact defect in a diff
    # nobody would flag.
    #
    # An invariant rather than a hashed file, for the same reason as ci.yml:
    # this file changes for ordinary reporting reasons.
    MustMatch(
        "scripts/render_feature_report.py",
        "the report renders panel provenance",
        r'"degraded_lenses"(?:.*?)"oracle_unknown_lenses"(?:.*?)"stale_reviews"',
        "A degradation written to the summary and never rendered is invisible "
        "to the human whose reading is the whole justification for letting a "
        "degraded campaign pass.",
    ),
    # Found by review on this PR's own second commit, and the same shape as
    # the `panel_correlated` correction one field over: an insufficiency
    # rendered as a finding. With fewer than two lenses carrying provenance
    # there is nothing to answer "did the panel span providers" with, and the
    # answer must not be the one a verified cross-provider panel gets.
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "the single-provider flag is tri-state, not two-valued",
        r"None if known_oracles < 2",
        "`len(providers) == 1 and known > 1` reports both a diverse panel and "
        "an unmeasured one as `false`, and the report renders `false` as "
        "'more than one provider is represented'.",
    ),
    MustMatch(
        "scripts/render_feature_report.py",
        "an unmeasurable provider question is rendered, not skipped",
        r"\*\*Single-provider panel\*\*: not recorded",
        "Silence on the third state leaves the reader to infer a diverse "
        "panel from an absent line, which is the false claim this branch "
        "exists to replace.",
    ),
    MustMatch(
        "scripts/spec_kit_planning_review.py",
        "high-risk handoffs must state panel provenance",
        r"a high-risk planning_review must state planning_review\.\{field\}",
        "The gate measures degradation and unknown provenance; a handoff that "
        "may omit them lets an authorized high-risk change be indistinguishable "
        "from one reviewed by a panel that ran as configured.",
    ),
    # The Makefile invariants above assert that `check-specs` runs the guards.
    # They said nothing about whether anything runs `check-specs`, and the CI
    # spec-kit job ran only the feature-spec validator — so this guard, its
    # invariants and the preserved-override check were absent from every build.
    # An actor could weaken its own gate and watch CI go green. Guarding the
    # Makefile without guarding the caller is a guard with no reader.
    #
    # Deliberately an invariant and not a hashed file: ci.yml changes for
    # unrelated reasons constantly, and a hash here would spend the manifest's
    # friction budget on noise instead of on the gate.
    MustMatch(
        ".github/workflows/ci.yml",
        "CI runs the gate-integrity guard",
        r"python3 scripts/check_gate_integrity\.py",
        "A guard that never executes in CI protects nothing. The Makefile "
        "target is only enforcement if something actually invokes it.",
    ),
    MustMatch(
        ".github/workflows/ci.yml",
        "CI runs the preserved-override guard",
        r"python3 scripts/check_speckit_manifests\.py",
        "Preserved Spec Kit overrides can otherwise be reverted by an "
        "integration upgrade with no build failure.",
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> dict[str, str]:
    if not MANIFEST_PATH.is_file():
        return {}
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = data.get("files", {})
    return {str(key): str(value) for key, value in files.items()}


def write_manifest(hashes: dict[str, str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "comment": (
                    "Hashes of the files that define this repository's delivery "
                    "gates. Regenerate deliberately with "
                    "`python3 scripts/check_gate_integrity.py --update`, and "
                    "expect a reviewer to ask what changed and why."
                ),
                "files": dict(sorted(hashes.items())),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def check_invariants(root: Path) -> list[str]:
    failures: list[str] = []
    cache: dict[str, str] = {}
    for invariant in INVARIANTS:
        path = root / invariant.path
        if not path.is_file():
            failures.append(f"{invariant.path}: MISSING (guards {invariant.name})")
            continue
        if invariant.path not in cache:
            cache[invariant.path] = path.read_text(encoding="utf-8")
        if not invariant.check(cache[invariant.path]):
            failures.append(
                f"{invariant.path}: invariant '{invariant.name}' no longer holds.\n"
                f"      why it exists: {invariant.why}"
            )
    return failures


def check_hashes(root: Path) -> tuple[list[str], dict[str, str]]:
    manifest = load_manifest()
    current: dict[str, str] = {}
    failures: list[str] = []

    for relative in GUARDED_FILES:
        path = root / relative
        if not path.is_file():
            failures.append(f"{relative}: MISSING but guarded")
            continue
        current[relative] = sha256(path)

    if not manifest:
        failures.append(
            "no gate-integrity manifest recorded; run "
            "`python3 scripts/check_gate_integrity.py --update`"
        )
        return failures, current

    for relative, digest in sorted(current.items()):
        recorded = manifest.get(relative)
        if recorded is None:
            failures.append(f"{relative}: guarded but absent from the manifest")
        elif recorded != digest:
            failures.append(
                f"{relative}: changed since the manifest was recorded. If the "
                "change is intended, re-record it in the same commit so the "
                "new hash is visible in the diff."
            )
    for relative in sorted(set(manifest) - set(current)):
        failures.append(f"{relative}: in the manifest but no longer guarded")

    return failures, current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="re-record the hash manifest (invariants must still pass)",
    )
    args = parser.parse_args(argv)

    # Invariants are checked first and always. --update re-records hashes; it
    # never waives an invariant, because that is the layer a self-weakening
    # actor would otherwise route around.
    invariant_failures = check_invariants(REPO_ROOT)
    if invariant_failures:
        print("Gate integrity FAILED — a gate invariant no longer holds:", file=sys.stderr)
        for failure in invariant_failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "\nThese are not waivable by --update. Restore the property, or "
            "change the policy deliberately and update this guard in a change "
            "a human reviews.",
            file=sys.stderr,
        )
        return 1

    hash_failures, current = check_hashes(REPO_ROOT)

    if args.update:
        write_manifest(current)
        print(f"Recorded {len(current)} gate file hashes in {MANIFEST_PATH.name}")
        return 0

    if hash_failures:
        print("Gate integrity FAILED — guarded files changed:", file=sys.stderr)
        for failure in hash_failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"Gate integrity intact ({len(GUARDED_FILES)} files, "
        f"{len(INVARIANTS)} invariants)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
