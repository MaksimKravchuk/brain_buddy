#!/usr/bin/env python3
"""Validate the verified-trunk serial landing and production deploy contract.

Companion to ``validate_ci_artifacts.py`` (which owns the general CI artifact
contract). This validator fails closed when the ADR-0008 guards are missing.

The central architectural invariant: candidate-controlled CI
(``.github/workflows/ci.yml`` runs from the pushed ref) must NEVER be able to
promote ``main``. It therefore must hold no write permission, push nothing,
and reference neither the landing identity nor the ``landing`` or
``production`` GitHub environments; it only runs the full required job set
(with skipped required jobs failing, never passing) for
``trunk-candidate/**`` refs.

Landing is owned exclusively by the DEFAULT-BRANCH release workflow
(``deploy-fly-production.yml``, consumed via ``workflow_run`` so the
definition always comes from ``main``): a ``land`` job with a READ-ONLY
token (``contents: read`` — no job anywhere holds GITHUB_TOKEN write) that
runs in the GitHub ``landing`` environment and authenticates its pushes with
the dedicated SSH deploy key secret ``TRUNK_LANDING_SSH_KEY`` (checked out
via ``ssh-key`` with ``persist-credentials: true``; the environment's branch
policy restricts the secret to ``main``, which candidate-controlled push CI
can never satisfy). It verifies a single fresh parent on the current
``origin/main``, re-runs the trusted ``origin/main`` copy of the path-risk
classifier over NUL-separated ``--no-renames`` changed paths, fast-forwards
the exact tested SHA with a plain (never force) push, best-effort deletes the
candidate ref, and — for EVERY consumed run, candidate and ``main`` alike —
proves ``origin/main`` equals the tested SHA. The ``deploy`` job needs the
landing proof, runs with ``contents: read`` in the ``production``
environment, re-verifies the exact main head before any Fly mutation, then
captures rollback images, verifies the smoke identity preflight, stages the
smoke identity, deploys, smokes, and rolls back verified, never masked.
No manual dispatch exists anywhere. Uses only the standard library so it can
run before any dependencies are installed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TRUNK_CI_REQUIREMENTS = (
    (
        "candidate push trigger",
        "trunk-candidate/**",
        "push CI must run for trunk-candidate/** refs",
    ),
    (
        "read-only workflow token",
        "contents: read",
        "candidate-controlled CI runs with a read-only token only",
    ),
    (
        "no-skip full CI gate",
        "contains(needs.*.result, 'skipped')",
        "a skipped required job must fail Full CI, never count as success",
    ),
)

TRUNK_CI_FORBIDDEN = (
    (
        "write permission",
        "contents: write",
        "candidate-controlled CI must never hold contents: write; landing is "
        "owned by the default-branch release workflow (ADR-0008)",
    ),
    (
        "git push",
        "git push",
        "candidate-controlled CI must never push anything, least of all main",
    ),
    (
        "promotion job",
        "trunk-promotion",
        "the promotion machinery must not live in candidate-controlled CI",
    ),
    (
        "force push",
        "--force",
        "nothing in CI may force-push; a non-fast-forward push fails closed",
    ),
    (
        "pull request creation",
        "gh pr create",
        "verified trunk landing must not create a PR",
    ),
    (
        "promotion PAT",
        "TRUNK_PROMOTION_TOKEN",
        "landing uses the dedicated SSH deploy key in the release workflow, "
        "never a PAT secret",
    ),
    (
        "landing deploy key",
        "TRUNK_LANDING_SSH_KEY",
        "candidate-controlled CI must never reference the landing deploy "
        "key; it lives only in the landing environment, whose branch policy "
        "restricts it to main",
    ),
    (
        "landing environment",
        "environment: landing",
        "candidate-controlled CI must never request the landing environment",
    ),
    (
        "production environment",
        "environment: production",
        "candidate-controlled CI must never request the production "
        "environment; production credentials (FLY_API_TOKEN, smoke "
        "identity, internal cohort) are environment secrets readable only "
        "by the deploy job of the default-branch release workflow, behind "
        "the environment's main-only branch policy",
    ),
)

DEPLOY_REQUIREMENTS = (
    (
        "read-only default permissions",
        "permissions:\n  contents: read",
        "the workflow-level token must be read-only; only the land job "
        "elevates, job-scoped",
    ),
    (
        "landing job",
        "  land:",
        "the default-branch release workflow must own landing in a dedicated "
        "secret-free land job",
    ),
    (
        "deploy gated on landing proof",
        "needs: land",
        "the deploy job must run only after the land job proved the landing",
    ),
    (
        "landing environment",
        "environment: landing",
        "the land job must run in the GitHub landing environment, whose "
        "deployment branch policy restricts the deploy-key secret to main",
    ),
    (
        "dedicated landing deploy key",
        "ssh-key: ${{ secrets.TRUNK_LANDING_SSH_KEY }}",
        "the fast-forward push must authenticate with the dedicated landing "
        "SSH deploy key, never the default workflow token",
    ),
    (
        "persisted landing push credentials",
        "persist-credentials: true",
        "checkout must persist the SSH deploy key so the fast-forward push "
        "authenticates as the dedicated landing identity",
    ),
    (
        "full-history candidate checkout",
        "fetch-depth: 0",
        "the land job needs history to verify parents against origin/main",
    ),
    (
        "single-parent verification",
        "rev-list --parents",
        "the candidate must be verified to have exactly one parent",
    ),
    (
        "current-base verification",
        'git rev-parse "${TESTED_SHA}^"',
        "the candidate parent must be compared against current origin/main",
    ),
    (
        "ASK-class path gate",
        "classify_path_risk.py",
        "landing must fail closed before pushing main when the candidate "
        "touches ASK-class paths (mechanical Ship/Show/Ask enforcement)",
    ),
    (
        "trusted classifier copy",
        "git show refs/remotes/origin/main:scripts/classify_path_risk.py",
        "the land job must run the origin/main copy of the classifier so a "
        "candidate cannot weaken the gate on itself",
    ),
    (
        "rename-safe NUL path listing",
        "--no-renames --name-only -z",
        "changed paths must be listed NUL-separated without rename folding "
        "so quoted/non-ASCII names classify on their real bytes and a "
        "rename away from an ASK path still surfaces as its deletion",
    ),
    (
        "NUL classifier input mode",
        "--null",
        "the classifier must consume the NUL-separated listing explicitly",
    ),
    (
        "exact-SHA fast-forward",
        ':refs/heads/main"',
        "landing must fast-forward the exact tested SHA to main",
    ),
    (
        "own-candidate cleanup",
        "--delete",
        "landing must delete only its own candidate ref after success",
    ),
    (
        "non-blocking candidate cleanup",
        "continue-on-error: true",
        "candidate-ref deletion is cleanup after the main mutation and must "
        "never fail the run or suppress the production deploy",
    ),
    (
        "candidate-gated landing steps",
        "startsWith(github.event.workflow_run.head_branch, 'trunk-candidate/')",
        "mutating landing steps must run only for candidate runs",
    ),
    (
        "universal landing proof",
        "Prove origin/main equals the tested revision",
        "the land job must prove the landing for EVERY consumed run "
        "(candidate and main) so stale runs fail closed before deploy",
    ),
    (
        "GitHub production environment",
        "environment: production",
        "the deploy job must run in the production environment",
    ),
    (
        "candidate CI run trigger",
        "trunk-candidate/**",
        "the workflow must consume the completed exact-SHA candidate CI run",
    ),
    (
        "landing verification",
        "git rev-parse origin/main",
        "every deploy (candidate and main) must prove origin/main equals "
        "the tested SHA before any remote mutation",
    ),
    (
        "unconditional main-head verification",
        "Verify the tested revision is the exact current main head",
        "the deploy job must re-verify the exact main head immediately "
        "before any Fly mutation, for every consumed CI run",
    ),
    (
        "smoke identity cohort gate",
        "check_smoke_identity_cohort.py",
        "the smoke identity must pass the backend-startup-mirroring "
        "preflight before any remote mutation",
    ),
    (
        "smoke email mapping",
        "BRAIN_BUDDY_SMOKE_EMAIL",
        "the smoke script must receive the provisioned identity",
    ),
    (
        "smoke password mapping",
        "BRAIN_BUDDY_SMOKE_PASSWORD",
        "the smoke script must receive the provisioned identity",
    ),
    (
        "admin email provisioning",
        "BRAIN_BUDDY_ADMIN_EMAIL",
        "the smoke identity must be seeded from the production environment "
        "secrets and missing secrets must fail before any deploy mutation",
    ),
    (
        "admin password provisioning",
        "BRAIN_BUDDY_ADMIN_PASSWORD",
        "the smoke identity must be seeded from the production environment "
        "secrets and missing secrets must fail before any deploy mutation",
    ),
    (
        "internal cohort provisioning",
        "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS",
        "the internal rollout cohort must be provisioned during deploy",
    ),
    (
        "staged secret provisioning",
        "flyctl secrets set --stage",
        "identity and flags must be staged so the deploy release applies them",
    ),
    (
        "internal canary rollout",
        "delivery_canary=internal",
        "the delivery canary must be pinned to the internal cohort",
    ),
    (
        "operator allow-list bound to the seeded admin identity",
        'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_EMAIL}"',
        "spec 009 PD-2/009-FR-001: production operator authority is exactly "
        "the seeded admin identity, restaged on every release — drift or "
        "removal of this binding silently changes who can look up any account "
        "and revoke its sessions",
    ),
    (
        "documented release image capture",
        "--image --json",
        "rollback capture must use the documented flyctl releases form",
    ),
    (
        "tested release image parser",
        "capture_fly_release_image.py",
        "release JSON must be parsed by the unit-tested casing-tolerant helper",
    ),
    (
        "rollback image capture validation",
        "registry.fly.io/",
        "captured rollback images must be validated before deploying",
    ),
    (
        "authenticated production smoke",
        "scripts/production_smoke.sh",
        "post-deploy verification must run the authenticated smoke script",
    ),
    (
        "frontend rollback image",
        "PREVIOUS_FRONTEND_IMAGE",
        "rollback must redeploy the captured frontend image",
    ),
    (
        "backend rollback image",
        "PREVIOUS_BACKEND_IMAGE",
        "rollback must redeploy the captured backend image",
    ),
    (
        "exact tested revision checkout",
        "workflow_run.head_sha",
        "the workflow must operate on the exact CI-tested revision",
    ),
    (
        "successful push CI gate",
        "github.event.workflow_run.conclusion == 'success'",
        "landing/deploy must require a successful CI conclusion",
    ),
    (
        "push-event gate",
        "github.event.workflow_run.event == 'push'",
        "landing/deploy must trigger only from push CI runs",
    ),
    (
        "main-branch gate",
        "github.event.workflow_run.head_branch == 'main'",
        "main CI runs must be consumed (proof-only, no push)",
    ),
)

DEPLOY_FORBIDDEN = (
    (
        "masked failure",
        "|| true",
        "rollback/verification must never be masked with unconditional success",
    ),
    (
        "manual dispatch",
        "workflow_dispatch",
        "an ungated manual production deploy has no deterministic "
        "exact-tested-SHA proof",
    ),
    (
        "force push",
        "--force",
        "landing must never force-push; a non-fast-forward push fails closed",
    ),
    (
        "promotion PAT",
        "TRUNK_PROMOTION_TOKEN",
        "landing must use the dedicated SSH deploy key, never a PAT secret",
    ),
    (
        "GITHUB_TOKEN write scope",
        "contents: write",
        "no job may hold GITHUB_TOKEN write; the main ruleset keeps the "
        "default token unable to push main (restrict_updates) and the "
        "landing push authenticates with the dedicated SSH deploy key",
    ),
    (
        "candidate-only main-head verification",
        "- name: Verify the tested revision is the exact current main head\n"
        "        if:",
        "exact-main verification must run for every consumed workflow run "
        "(candidate and main), never only for candidates",
    ),
    (
        "candidate-only landing proof",
        "- name: Prove origin/main equals the tested revision\n"
        "        if:",
        "the landing proof must run for every consumed workflow run "
        "(candidate and main), never only for candidates",
    ),
)


def _check(
    workflow: Path,
    label: str,
    requirements: tuple[tuple[str, str, str], ...],
    forbidden: tuple[tuple[str, str, str], ...],
    extra_errors: list[str] | None = None,
) -> int:
    if not workflow.is_file():
        print(f"error: {label}: workflow does not exist: {workflow}", file=sys.stderr)
        return 1

    text = workflow.read_text(encoding="utf-8")
    errors: list[str] = []
    for name, snippet, reason in requirements:
        if snippet not in text:
            errors.append(f"missing {name} ({snippet!r}): {reason}")
    for name, snippet, reason in forbidden:
        if snippet in text:
            errors.append(f"forbidden {name} ({snippet!r}): {reason}")
    errors.extend(extra_errors or [])

    if errors:
        for error in errors:
            print(f"error: {label}: {error}", file=sys.stderr)
        return 1

    print(f"{label} validation passed: {workflow}")
    return 0


#: The flag names the released image a rollback restores can parse. A staged
#: secret survives the image swap, and that image raises at startup on a name
#: it does not know — so staging a newer flag turns rollback into a crash loop.
#:
#: Provenance is the deployed image, not a source SHA: the captured rollback
#: target is
#: registry.fly.io/brain-buddy-backend:deployment-01M00243625JAFN5S6G4CVZ7DH,
#: the healthy release left by the default-OFF baseline deployment (run
#: 31798252344 for exact main d9ec122f, authenticated production smoke passed).
#: Built from the 009 revision, it parses `admin_portal` and
#: `external_agent_relay` too — unlike the pre-009 image that crash-looped on
#: `external_agent_relay` in deploy run 31775660872. Widen this only after a
#: successful deployment has made a newer, known-compatible image the captured
#: rollback target, as that baseline release did; agreeing with the candidate
#: tree instead is what caused the incident.
#:
#: This is a safety allow-list only. Parseable is not authorized — see
#: `AUTHORIZED_STAGED_FEATURE_FLAGS`.
ROLLBACK_KNOWN_FEATURE_FLAGS = frozenset(
    {
        "delivery_canary",
        "mobile_task_classification",
        "voice_brain_dump",
        "external_agent_relay",
        "admin_portal",
    }
)

#: The exact rollout the release is authorized to stage. Kept separate from the
#: allow-list above so that widening compatibility can never quietly enable a
#: product: `external_agent_relay` is parseable by the rollback image and is
#: still absent here, because spec 007's rollout is separately governed and
#: omission is the OFF state every image agrees on. Changing this string is an
#: ASK-class rollout decision.
AUTHORIZED_STAGED_FEATURE_FLAGS = (
    "delivery_canary=internal,voice_brain_dump=on,admin_portal=internal"
)


def _staged_feature_flag_errors(text: str) -> list[str]:
    """The staged rollout must be rollback-parseable *and* the authorized one."""

    match = re.search(r'BRAIN_BUDDY_FEATURE_FLAGS="([^"]*)"', text)
    if match is None:
        return [
            "the deploy job must stage BRAIN_BUDDY_FEATURE_FLAGS as the "
            "authoritative rollout state"
        ]
    staged = match.group(1)
    errors: list[str] = []
    names = {
        entry.split("=", 1)[0].strip() for entry in staged.split(",") if entry.strip()
    }
    unknown = sorted(names - ROLLBACK_KNOWN_FEATURE_FLAGS)
    if unknown:
        errors.append(
            f"staged feature flag(s) {unknown} are unknown to the image a "
            "rollback restores; a staged secret survives the image swap and "
            "that image fails startup on an unknown flag name. Ship the "
            "release with the flag omitted (omission is OFF) and name it here "
            "only once the rollback target already knows it"
        )
    if staged != AUTHORIZED_STAGED_FEATURE_FLAGS:
        errors.append(
            f"the staged rollout {staged!r} is not the authorized rollout "
            f"{AUTHORIZED_STAGED_FEATURE_FLAGS!r}; this line is the "
            "authoritative production flag state, so adding a name, dropping "
            "one or restaging one at another state is an ASK-class decision "
            "that must change that constant deliberately. A name being "
            "rollback-parseable does not make it authorized"
        )
    return errors


def _landing_job_errors(raw_text: str) -> list[str]:
    """Structural checks the flat snippet lists cannot express.

    Comments are stripped first so documentation may mention the guarded
    literals without weakening or tripping the structural checks.
    """

    text = "\n".join(
        line
        for line in raw_text.splitlines()
        if not line.lstrip().startswith("#")
    )
    errors: list[str] = _staged_feature_flag_errors(text)
    if "contents: write" in text:
        errors.append(
            "no job may hold GITHUB_TOKEN contents: write; the landing push "
            "authenticates with the dedicated SSH deploy key instead"
        )
    start = text.find("\n  land:")
    end = text.find("\n  deploy:")
    if start == -1 or end == -1 or end < start:
        errors.append(
            "the workflow must define the land job followed by the deploy job"
        )
        return errors
    land_block = text[start:end]
    deploy_block = text[end:]
    if "secrets." in land_block.replace("secrets.TRUNK_LANDING_SSH_KEY", ""):
        errors.append(
            "the land job may reference no secret other than "
            "TRUNK_LANDING_SSH_KEY; production credentials belong "
            "exclusively to the deploy job"
        )
    if "environment: landing" not in land_block:
        errors.append(
            "the land job must run in the landing environment so its deploy "
            "key stays behind the environment's main-only branch policy"
        )
    if "contents: read" not in land_block:
        errors.append(
            "the land job must pin its token permissions to contents: read"
        )
    if "ssh-key: ${{ secrets.TRUNK_LANDING_SSH_KEY }}" not in land_block:
        errors.append(
            "the land job checkout must authenticate with the "
            "TRUNK_LANDING_SSH_KEY deploy key"
        )
    if "persist-credentials: true" not in land_block:
        errors.append(
            "the land job checkout must persist the deploy-key credentials "
            "for the fast-forward push"
        )
    if "environment: production" in land_block:
        errors.append(
            "the land job must not run in the production environment; it "
            "must stay free of production credentials"
        )
    if "TRUNK_LANDING_SSH_KEY" in deploy_block:
        errors.append(
            "the landing deploy key is scoped to the land job; the deploy "
            "job must never reference it"
        )
    return errors


def validate_trunk_ci(workflow: Path) -> int:
    return _check(workflow, "trunk-ci", TRUNK_CI_REQUIREMENTS, TRUNK_CI_FORBIDDEN)


def validate_deploy_workflow(workflow: Path) -> int:
    extra: list[str] = []
    if workflow.is_file():
        extra = _landing_job_errors(workflow.read_text(encoding="utf-8"))
    return _check(
        workflow, "trunk-deploy", DEPLOY_REQUIREMENTS, DEPLOY_FORBIDDEN, extra
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    trunk = subparsers.add_parser(
        "trunk-ci",
        help="validate that candidate-controlled CI can never promote main",
    )
    trunk.add_argument("--ci", type=Path, required=True)

    deploy = subparsers.add_parser(
        "deploy",
        help="validate the default-branch landing + production deploy contract",
    )
    deploy.add_argument("--workflow", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "trunk-ci":
        return validate_trunk_ci(args.ci)
    if args.command == "deploy":
        return validate_deploy_workflow(args.workflow)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
