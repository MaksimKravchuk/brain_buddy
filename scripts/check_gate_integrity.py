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
        ".specify/workflows/speckit/review.schema.json",
        "both mandatory lenses stay in the role enum",
        r'"privacy-consent-security".*?"ux-accessibility-mobile"',
        "The privacy and UX lenses cover constitution principles I and V. "
        "Removing either leaves a principle with no reviewer.",
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
