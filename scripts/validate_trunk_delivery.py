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
        "operator allow-list secret mapping",
        "secrets.BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS",
        "the production operator allow-list must come from its dedicated "
        "production environment secret",
    ),
    (
        "dedicated operator allow-list staging",
        'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS}"',
        "the durable production operator allow-list must be staged from its "
        "dedicated secret on every release",
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
        "prior-revision rollout authority",
        'git show "${TESTED_SHA}^:.github/workflows/deploy-fly-production.yml"',
        "the previous feature-flag rollout must be read from the previous "
        "revision of this workflow — never scraped from the live app (which "
        "reports what the failing release staged) and never hard-coded",
    ),
    (
        "tested rollout parser",
        "extract_staged_feature_flags.py",
        "the prior rollout must be parsed by the unit-tested fail-closed "
        "helper, so an ambiguous or malformed prior assignment aborts the run "
        "instead of the rollback",
    ),
    (
        "masked captured rollout",
        "::add-mask::",
        "the captured prior rollout must be masked before it is exported",
    ),
    (
        "exported captured rollout",
        "PREVIOUS_FEATURE_FLAGS=",
        "the captured prior rollout must be exported for the rollback step",
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
        "operator allow-list alias to smoke identity",
        'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_EMAIL}"',
        "the durable operator allow-list must not be replaced by the rotating "
        "smoke admin identity",
    ),
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


#: The deploy-job steps whose bodies carry structural obligations. Checks are
#: scoped to these blocks rather than to the whole file, so a guard that moved
#: into the wrong step — or into prose — still fails.
STAGE_ROLLOUT_STEP = "Stage the smoke identity and feature-flag rollout"
CAPTURE_PREVIOUS_ROLLOUT_STEP = "Capture the previous release's feature-flag rollout"
ROLLBACK_STEP = "Roll back to the captured images and verify"

#: The prior rollout is authoritative only because of where it is read from.
PRIOR_REVISION_READ = (
    'git show "${TESTED_SHA}^:.github/workflows/deploy-fly-production.yml"'
)
PREVIOUS_ROLLOUT_RESTORE = 'BRAIN_BUDDY_FEATURE_FLAGS="${PREVIOUS_FEATURE_FLAGS}"'
BACKEND_ROLLBACK_DEPLOY = '--image "${PREVIOUS_BACKEND_IMAGE}"'

#: Reading the live app back would report exactly the rollout the failing
#: release staged, which is the value the rollback exists to undo.
LIVE_SECRET_SCRAPES = ("flyctl secrets list", "flyctl ssh console")


def _step_block(text: str, step_name: str) -> str | None:
    """The body of one named deploy-job step, up to the next step at its indent."""

    marker = f"      - name: {step_name}\n"
    start = text.find(marker)
    if start == -1:
        return None
    end = text.find("\n      - name: ", start + len(marker))
    return text[start:] if end == -1 else text[start:end]


def _staged_feature_flag_errors(text: str) -> list[str]:
    """The staged rollout must be rollback-parseable *and* the authorized one."""

    # Scoped to the staging step so the rollback step's restore assignment can
    # never be read as the declared rollout.
    scope = _step_block(text, STAGE_ROLLOUT_STEP) or text
    match = re.search(r'BRAIN_BUDDY_FEATURE_FLAGS="([^"$]*)"', scope)
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


def _rollback_rollout_errors(text: str) -> list[str]:
    """Rolling the IMAGES back is not rolling the RELEASE back.

    Fly secrets are app-scoped and outlive an image swap, so the rollout this
    run staged is still pending when a rollback restores the old image. Unless
    the previous rollout is captured before anything is mutated and restaged
    before the previous BACKEND image is deployed, a failed enablement leaves
    the new flags live behind an old image. Order is checked positionally, so
    a guard that exists but runs too late fails here.
    """

    errors: list[str] = []
    capture = _step_block(text, CAPTURE_PREVIOUS_ROLLOUT_STEP)
    rollback = _step_block(text, ROLLBACK_STEP)
    if capture is None:
        errors.append(
            f"the deploy job must hold a {CAPTURE_PREVIOUS_ROLLOUT_STEP!r} step "
            "that reads the rollout the rollback target was released with"
        )
    if rollback is None:
        errors.append(
            f"the deploy job must hold a {ROLLBACK_STEP!r} step; without it "
            "nothing restores the previous release state"
        )
    if capture is None or rollback is None:
        return errors

    if PRIOR_REVISION_READ not in capture:
        errors.append(
            "the previous rollout must be read from the previous revision of "
            f"this workflow ({PRIOR_REVISION_READ!r}); a live read-back would "
            "report the rollout the failing release staged"
        )
    if "extract_staged_feature_flags.py" not in capture:
        errors.append(
            "the previous rollout must be parsed by the unit-tested "
            "fail-closed helper, not by an inline expression"
        )
    if "::add-mask::" not in capture:
        errors.append("the captured previous rollout must be masked")
    if 'PREVIOUS_FEATURE_FLAGS=' not in capture or "GITHUB_ENV" not in capture:
        errors.append(
            "the captured previous rollout must be exported as "
            "PREVIOUS_FEATURE_FLAGS via GITHUB_ENV for the rollback step"
        )

    # Capture must precede the first remote mutation anywhere in the workflow.
    capture_at = text.find(f"      - name: {CAPTURE_PREVIOUS_ROLLOUT_STEP}\n")
    mutations = [
        position
        for position in (text.find("flyctl secrets set"), text.find("flyctl deploy"))
        if position != -1
    ]
    if mutations and capture_at > min(mutations):
        errors.append(
            "the previous rollout must be captured BEFORE the first Fly "
            "mutation, so an unreadable prior rollout aborts the run rather "
            "than the rollback"
        )

    for scrape in LIVE_SECRET_SCRAPES:
        if scrape in rollback:
            errors.append(
                f"the rollback must not recover flags with {scrape!r}; the live "
                "app holds the rollout the failing release staged"
            )
    restore_at = rollback.find(PREVIOUS_ROLLOUT_RESTORE)
    if restore_at == -1:
        errors.append(
            f"the rollback must restage {PREVIOUS_ROLLOUT_RESTORE} — the value "
            "captured from the previous revision, never a literal rollout"
        )
    else:
        backend_at = rollback.find(BACKEND_ROLLBACK_DEPLOY)
        if backend_at == -1:
            errors.append(
                "the rollback must deploy the captured previous backend image"
            )
        elif restore_at > backend_at:
            errors.append(
                "the previous rollout must be restaged BEFORE the previous "
                "backend image is deployed; that deploy is the release which "
                "applies the pending secret, so restaging after it leaves the "
                "restored image running the failed release's flags"
            )
    for name in sorted(ROLLBACK_KNOWN_FEATURE_FLAGS):
        if f"{name}=" in rollback:
            errors.append(
                f"the rollback names {name!r} literally; the previous rollout "
                "is whatever the previous revision staged, so hard-coding one "
                "here reintroduces the guess this contract removed"
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
    errors.extend(_rollback_rollout_errors(text))
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
