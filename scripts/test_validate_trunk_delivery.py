#!/usr/bin/env python3
"""Contract tests for scripts/validate_trunk_delivery.py.

Verifies the verified-trunk landing contract on the real repository workflows
and proves the validator fails closed when a required guard is removed.

The architectural invariant under test: candidate-controlled CI
(.github/workflows/ci.yml) must never be able to promote main — no write
permission, no pushes, no access to the landing identity. Landing is owned
by the default-branch release workflow (deploy-fly-production.yml): a land
job with a read-only token (contents: read) that runs in the GitHub
``landing`` environment and authenticates its fast-forward push with the
dedicated SSH deploy key secret TRUNK_LANDING_SSH_KEY (via actions/checkout
``ssh-key`` + ``persist-credentials: true``), followed by a deploy job that
needs the landing proof and holds the production environment secrets. No
job anywhere holds GITHUB_TOKEN contents: write.
"""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "validate_trunk_delivery",
    Path(__file__).with_name("validate_trunk_delivery.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate_trunk_ci = _MODULE.validate_trunk_ci
validate_deploy_workflow = _MODULE.validate_deploy_workflow

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-fly-production.yml"
DEPLOY_CLASSIFIER = REPO_ROOT / "scripts" / "classify_deploy_paths.sh"

CI_REQUIRED_SNIPPETS = (
    "trunk-candidate/**",
    "contents: read",
    "contains(needs.*.result, 'skipped')",
)

DEPLOY_REQUIRED_SNIPPETS = (
    "permissions:\n  contents: read",
    "needs: land",
    "environment: landing",
    "ssh-key: ${{ secrets.TRUNK_LANDING_SSH_KEY }}",
    "persist-credentials: true",
    "fetch-depth: 0",
    "rev-list --parents",
    'git rev-parse "${TESTED_SHA}^"',
    "git show refs/remotes/origin/main:scripts/classify_path_risk.py",
    "--no-renames --name-only -z",
    "--null",
    ':refs/heads/main"',
    "--delete",
    "continue-on-error: true",
    "startsWith(github.event.workflow_run.head_branch, 'trunk-candidate/')",
    "Prove origin/main equals the tested revision",
    "environment: production",
    "trunk-candidate/**",
    "git rev-parse origin/main",
    "Verify the tested revision is the exact current main head",
    "check_smoke_identity_cohort.py",
    "BRAIN_BUDDY_SMOKE_EMAIL",
    "BRAIN_BUDDY_SMOKE_PASSWORD",
    "BRAIN_BUDDY_ADMIN_EMAIL",
    "BRAIN_BUDDY_ADMIN_PASSWORD",
    "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS",
    "flyctl secrets set --stage",
    "delivery_canary=internal",
    "secrets.BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS",
    'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS}"',
    "--image --json",
    "capture_fly_release_image.py",
    "registry.fly.io/",
    "scripts/production_smoke.sh",
    "PREVIOUS_FRONTEND_IMAGE",
    "PREVIOUS_BACKEND_IMAGE",
    "workflow_run.head_sha",
    "Detect the first SQLite-managed feature-flag transition",
    _MODULE.FIRST_TRANSITION_MARKER,
    "Stage the first-transition feature-flag seed",
    "Restage delivery-only rollout after a first-transition deploy",
    'RETIRED = {"admin_portal"}',
    'VALID_STATES = {"off", "internal", "on"}',
    "if name not in KNOWN:",
    "if state not in VALID_STATES:",
    "error: the captured previous rollout has an unrecognized flag name",
    "error: the captured previous rollout has an invalid flag state",
)


def _temp_workflow(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".yml", delete=False, encoding="utf-8"
    )
    handle.write(text)
    handle.close()
    return Path(handle.name)


def _mutated_copy(source: Path, remove: str) -> Path:
    text = source.read_text(encoding="utf-8")
    assert remove in text, f"fixture precondition: {remove!r} present in {source.name}"
    return _temp_workflow(text.replace(remove, ""))


class TrunkCiContractTest(unittest.TestCase):
    def test_repo_ci_workflow_passes(self) -> None:
        self.assertEqual(validate_trunk_ci(CI_WORKFLOW), 0)

    def test_missing_workflow_fails(self) -> None:
        self.assertEqual(validate_trunk_ci(Path("/nonexistent/ci.yml")), 1)

    def test_each_required_guard_is_enforced(self) -> None:
        for snippet in CI_REQUIRED_SNIPPETS:
            with self.subTest(snippet=snippet):
                mutated = _mutated_copy(CI_WORKFLOW, snippet)
                try:
                    self.assertEqual(
                        validate_trunk_ci(mutated),
                        1,
                        f"validator must fail without {snippet!r}",
                    )
                finally:
                    mutated.unlink()

    def test_repo_ci_workflow_holds_no_write_or_push_power(self) -> None:
        """The repo workflow itself must already be powerless to promote."""

        text = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("contents: write", text)
        self.assertNotIn("git push", text)
        self.assertNotIn("trunk-promotion", text)
        self.assertNotIn("TRUNK_LANDING_SSH_KEY", text)
        self.assertNotIn("environment: landing", text)
        self.assertNotIn("environment: production", text)

    def test_reintroduced_write_permission_is_rejected(self) -> None:
        """A candidate-controlled workflow that grants itself contents: write
        must fail validation — that is the self-promotion hole."""

        text = CI_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(
            text + "\n    permissions:\n      contents: write\n"
        )
        try:
            self.assertEqual(validate_trunk_ci(mutated), 1)
        finally:
            mutated.unlink()

    def test_reintroduced_promotion_push_is_rejected(self) -> None:
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(
            text + '\n      - run: git push origin "${SHA}:refs/heads/main"\n'
        )
        try:
            self.assertEqual(validate_trunk_ci(mutated), 1)
        finally:
            mutated.unlink()

    def test_reintroduced_promotion_concurrency_group_is_rejected(self) -> None:
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(text + "\n# group: trunk-promotion\n")
        try:
            self.assertEqual(validate_trunk_ci(mutated), 1)
        finally:
            mutated.unlink()

    def test_landing_secret_reference_is_rejected(self) -> None:
        """Candidate-controlled CI must never reference the landing deploy
        key; the landing environment's branch policy is the remote guard,
        this is the in-repo one."""

        text = CI_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(
            text + "\n#      ssh-key: ${{ secrets.TRUNK_LANDING_SSH_KEY }}\n"
        )
        try:
            self.assertEqual(validate_trunk_ci(mutated), 1)
        finally:
            mutated.unlink()

    def test_landing_environment_request_is_rejected(self) -> None:
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(text + "\n#    environment: landing\n")
        try:
            self.assertEqual(validate_trunk_ci(mutated), 1)
        finally:
            mutated.unlink()

    def test_production_environment_request_is_rejected(self) -> None:
        """Candidate-controlled CI must never request the production
        environment either: production credentials (FLY_API_TOKEN, the smoke
        identity, the internal cohort) are readable only by the deploy job of
        the default-branch release workflow. The environment's main-only
        branch policy is the remote guard; this is the in-repo one."""

        text = CI_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(text + "\n#    environment: production\n")
        try:
            self.assertEqual(validate_trunk_ci(mutated), 1)
        finally:
            mutated.unlink()

    def test_promotion_pat_is_rejected(self) -> None:
        """Reintroducing a PAT secret for promotion must fail validation."""

        text = CI_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(
            text + "\n# token: ${{ secrets.TRUNK_PROMOTION_TOKEN }}\n"
        )
        try:
            self.assertEqual(validate_trunk_ci(mutated), 1)
        finally:
            mutated.unlink()

    def test_main_push_ci_is_never_cancelled(self) -> None:
        """The push-CI concurrency policy must not be weakened."""

        text = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "cancel-in-progress: ${{ github.event_name == 'pull_request' }}", text
        )


class DeployContractTest(unittest.TestCase):
    def _classify(self, paths: tuple[str, ...], classifier: Path = DEPLOY_CLASSIFIER) -> str:
        result = subprocess.run(
            ["bash", str(classifier)],
            input="".join(f"{path}\0" for path in paths).encode(),
            capture_output=True,
            check=True,
        )
        return result.stdout.decode().strip()

    def test_deploy_classifier_covers_policy_and_fail_open_paths(self) -> None:
        policy_only = (
            "mobile/src/app.tsx",
            "docs/deploy.md",
            "specs/007-rollout/spec.md",
            ".claude/agents/reviewer.md",
            ".design-sync/manifest.json",
            ".github/CODEOWNERS",
            "README.md",
            ".specify/memory/constitution.md",
            "Makefile",
            ".gitignore",
            "LICENSE",
            ".env.example",
            "mobile/README.md",
            "docs/README.md",
            "specs/README.md",
        )
        self.assertEqual(self._classify(policy_only), "needed=false")

        deploy_relevant = (
            "backend/app/main.py",
            "frontend/src/App.tsx",
            "fly.toml",
            "docker-compose.yml",
            "Dockerfile",
            "compose.yaml",
            "auth-policy.txt",
            ".env.production",
            "unknown.bin",
        )
        for path in deploy_relevant:
            with self.subTest(path=path):
                self.assertEqual(self._classify((path,)), "needed=true")
        self.assertEqual(
            self._classify(("docs/README.md", "unknown.bin")), "needed=true"
        )
        self.assertEqual(self._classify(()), "needed=true")

    def test_deploy_classifier_mutant_fails_policy_only_assertion(self) -> None:
        text = DEPLOY_CLASSIFIER.read_text(encoding="utf-8")
        inert_arm = ".github/*|.specify/*|.claude/*|.design-sync/*|docs/*|specs/*|mobile/*|scripts/*|*.md|Makefile|.gitignore|LICENSE|.env.example)"
        self.assertIn(inert_arm, text)
        mutant = _temp_workflow(text.replace(inert_arm, inert_arm + "\n                needed=true", 1))
        try:
            policy_only = ("mobile/src/app.tsx", "docs/deploy.md")
            self.assertNotEqual(self._classify(policy_only, mutant), "needed=false")
        finally:
            mutant.unlink()

    def test_repo_deploy_workflow_passes(self) -> None:
        self.assertEqual(validate_deploy_workflow(DEPLOY_WORKFLOW), 0)

    def test_policy_only_landing_skips_runtime_deploy(self) -> None:
        """The deploy gate must not treat delivery machinery as image input."""

        self.assertEqual(self._classify(("docs/deploy.md", "mobile/app.tsx")), "needed=false")

    def test_deploy_gate_keeps_runtime_unknown_and_empty_fail_open(self) -> None:
        self.assertEqual(self._classify(("unknown.bin",)), "needed=true")
        self.assertEqual(self._classify(()), "needed=true")

    def test_missing_workflow_fails(self) -> None:
        self.assertEqual(validate_deploy_workflow(Path("/nonexistent/deploy.yml")), 1)

    def test_each_required_guard_is_enforced(self) -> None:
        for snippet in DEPLOY_REQUIRED_SNIPPETS:
            with self.subTest(snippet=snippet):
                mutated = _mutated_copy(DEPLOY_WORKFLOW, snippet)
                try:
                    self.assertEqual(
                        validate_deploy_workflow(mutated),
                        1,
                        f"validator must fail without {snippet!r}",
                    )
                finally:
                    mutated.unlink()

    def _staged_flag_mutant(self, replacement: str) -> Path:
        """Restage a different flag string, leaving the rest of the file alone."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = f'BRAIN_BUDDY_FEATURE_FLAGS="{_MODULE.AUTHORIZED_STAGED_FEATURE_FLAGS}"'
        self.assertIn(needle, text)
        return _temp_workflow(
            text.replace(needle, f'BRAIN_BUDDY_FEATURE_FLAGS="{replacement}"', 1)
        )

    def test_staging_a_flag_the_rollback_image_cannot_parse_fails(self) -> None:
        """A staged secret outlives the image, so it must stay parseable.

        Fly secrets are app-scoped: a flag named on this release is still
        pending when a rollback restores the captured image, and that image
        raises at startup on a name it has never heard of. Staging it would
        break the rollback lever at the moment it is needed.
        """

        mutated = self._staged_flag_mutant(
            f"{_MODULE.AUTHORIZED_STAGED_FEATURE_FLAGS},future_unshipped_flag=on"
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_staging_external_agent_relay_fails(self) -> None:
        """The incident mutant: run 31775660872 staged exactly this name.

        It crash-looped the pre-009 image the automatic rollback restored. The
        *current* rollback target parses the name, so compatibility no longer
        objects — and that is the point: rollback-safe is not authorized to
        ship. Spec 007's rollout is separately governed, so staging it must
        still fail here, in CI, and not at the reachability gate.
        """

        mutated = self._staged_flag_mutant(
            f"{_MODULE.AUTHORIZED_STAGED_FEATURE_FLAGS},external_agent_relay=internal"
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()
        self.assertIn("external_agent_relay", _MODULE.ROLLBACK_KNOWN_FEATURE_FLAGS)

    def test_dropping_or_downgrading_the_delivery_canary_rollout_fails(self) -> None:
        """The staged line is the authoritative rollout, so silently reverting
        or restaging it at another state must not pass validation.

        ADR-0019 (2026-08-15) retires `voice_brain_dump`/`admin_portal` from
        this string entirely, so `delivery_canary` is the only remaining
        entry left to guard here."""

        for staged in (
            "",
            "delivery_canary=off",
            "delivery_canary=on",
        ):
            with self.subTest(staged=staged):
                mutated = self._staged_flag_mutant(staged)
                try:
                    self.assertEqual(validate_deploy_workflow(mutated), 1)
                finally:
                    mutated.unlink()

    def test_repo_deploy_workflow_stages_only_rollback_parseable_flags(self) -> None:
        """The shipped workflow itself, not just a mutant, holds the contract."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        staged = text.split('BRAIN_BUDDY_FEATURE_FLAGS="', 1)[1].split('"', 1)[0]
        names = {
            entry.split("=", 1)[0].strip()
            for entry in staged.split(",")
            if entry.strip()
        }
        self.assertEqual(names - _MODULE.ROLLBACK_KNOWN_FEATURE_FLAGS, set())
        self.assertEqual(
            _MODULE.ROLLBACK_KNOWN_FEATURE_FLAGS,
            frozenset(
                {
                    "delivery_canary",
                    "mobile_task_classification",
                    "voice_brain_dump",
                    "external_agent_relay",
                }
            ),
        )
        self.assertEqual(staged, _MODULE.AUTHORIZED_STAGED_FEATURE_FLAGS)
        self.assertEqual(
            _MODULE.AUTHORIZED_STAGED_FEATURE_FLAGS,
            "delivery_canary=internal",
        )
        self.assertNotIn("external_agent_relay", staged)
        self.assertNotIn("admin_portal", staged)
        self.assertNotIn("voice_brain_dump", staged)

    def test_a_comment_may_still_name_a_flag_it_does_not_stage(self) -> None:
        """Documentation of the ungranted relay rollout must not trip the
        checker, which reads the staged value and not the prose."""

        self.assertIn("external_agent_relay", DEPLOY_WORKFLOW.read_text(encoding="utf-8"))
        self.assertEqual(validate_deploy_workflow(DEPLOY_WORKFLOW), 0)

    def test_first_transition_seed_allow_listing_admin_portal_is_rejected(self) -> None:
        """admin_portal is retired (ADR-0019 DD-14); the new image cannot
        parse it, so the seed's allow-list must never include it again."""

        mutated = self._rollback_contract_mutant(
            '          KNOWN = {\n',
            '          KNOWN = {\n              "admin_portal",\n',
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_first_transition_seed_silently_dropping_unknown_flag_is_rejected(
        self,
    ) -> None:
        """Regression guard for the bug this change fixes: any name outside

        the known managed set used to be silently dropped, same as a
        legitimately retired one. Reverting to that behavior (while leaving
        state validation intact) must fail validation — only the explicitly
        retired admin_portal may be dropped without an error.
        """

        mutated = self._rollback_contract_mutant(
            "              if name not in KNOWN:\n"
            '                  print("error: the captured previous rollout '
            'has an unrecognized flag name", file=sys.stderr)\n'
            "                  sys.exit(1)\n"
            "              if state not in VALID_STATES:\n"
            '                  print("error: the captured previous rollout '
            'has an invalid flag state", file=sys.stderr)\n'
            "                  sys.exit(1)\n"
            '              entries.append(f"{name}={state}")\n',
            "              if state not in VALID_STATES:\n"
            '                  print("error: the captured previous rollout '
            'has an invalid flag state", file=sys.stderr)\n'
            "                  sys.exit(1)\n"
            "              if name in KNOWN:\n"
            '                  entries.append(f"{name}={state}")\n',
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_first_transition_seed_accepting_invalid_state_is_rejected(self) -> None:
        """Regression guard: a captured state outside the legacy

        off/internal/on vocabulary used to be staged verbatim, unchecked.
        Reverting to that (while leaving the unknown-name error intact) must
        fail validation.
        """

        mutated = self._rollback_contract_mutant(
            "              if name not in KNOWN:\n"
            '                  print("error: the captured previous rollout '
            'has an unrecognized flag name", file=sys.stderr)\n'
            "                  sys.exit(1)\n"
            "              if state not in VALID_STATES:\n"
            '                  print("error: the captured previous rollout '
            'has an invalid flag state", file=sys.stderr)\n'
            "                  sys.exit(1)\n"
            '              entries.append(f"{name}={state}")\n',
            "              if name not in KNOWN:\n"
            '                  print("error: the captured previous rollout '
            'has an unrecognized flag name", file=sys.stderr)\n'
            "                  sys.exit(1)\n"
            '              entries.append(f"{name}={state}")\n',
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_first_transition_seed_missing_mask_is_rejected(self) -> None:
        mutated = self._rollback_contract_mutant(
            '          echo "::add-mask::${staged}"\n', ""
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_first_transition_seed_hardcoded_literal_is_rejected(self) -> None:
        """The seed must be staged from the computed variable, never a
        second literal — a second literal would make the next deploy's
        capture of ``BRAIN_BUDDY_FEATURE_FLAGS`` ambiguous."""

        mutated = self._rollback_contract_mutant(
            'BRAIN_BUDDY_FEATURE_FLAGS="${staged}"',
            'BRAIN_BUDDY_FEATURE_FLAGS="delivery_canary=internal"',
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_first_transition_cleanup_second_image_deploy_is_rejected(self) -> None:
        """The cleanup restage must never itself trigger a second image
        deploy; it only stages the rollout for the next release."""

        mutated = self._rollback_contract_mutant(
            f"      - name: {_MODULE.CLEANUP_FIRST_TRANSITION_STEP}\n",
            f"      - name: {_MODULE.CLEANUP_FIRST_TRANSITION_STEP}\n"
            "        run: flyctl deploy --config fly.backend.toml\n",
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_first_transition_seed_after_backend_deploy_is_rejected(self) -> None:
        """Staging the seed after the backend has already booted would leave
        it running the delivery-only baseline — too late for migration."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        seed_marker = f"      - name: {_MODULE.STAGE_FIRST_TRANSITION_SEED_STEP}\n"
        seed_start = text.index(seed_marker)
        seed_end = text.index("\n      - name: ", seed_start + len(seed_marker)) + 1
        seed_block = text[seed_start:seed_end]
        backend_deploy_marker = "      - name: Deploy backend\n"
        backend_start = text.index(backend_deploy_marker)
        backend_end = text.index("\n      - name: ", backend_start + len(backend_deploy_marker)) + 1
        backend_block = text[backend_start:backend_end]
        mutated = _temp_workflow(
            text[:seed_start]
            + backend_block
            + text[seed_end:backend_start]
            + seed_block
            + text[backend_end:]
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_first_transition_cleanup_before_smoke_is_rejected(self) -> None:
        """The delivery-only restage must run only after smoke has passed,
        never before — running it earlier could restage over a seed that
        migration has not yet consumed."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        cleanup_marker = f"      - name: {_MODULE.CLEANUP_FIRST_TRANSITION_STEP}\n"
        cleanup_start = text.index(cleanup_marker)
        cleanup_end = text.index("\n      - name: ", cleanup_start + len(cleanup_marker)) + 1
        cleanup_block = text[cleanup_start:cleanup_end]
        remaining = text[:cleanup_start] + text[cleanup_end:]
        reachability_marker = "      - name: Reachability smoke test\n"
        insert_at = remaining.index(reachability_marker)
        mutated = _temp_workflow(
            remaining[:insert_at] + cleanup_block + remaining[insert_at:]
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def _rollback_contract_mutant(self, needle: str, replacement: str, count: int = 1) -> Path:
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(needle, text)
        return _temp_workflow(text.replace(needle, replacement, count))

    def test_prior_revision_authority_live_scrape_is_rejected(self) -> None:
        """Reading the prior rollout back from the live app would report
        whatever the failing release just staged, not the previous one."""

        mutated = self._rollback_contract_mutant(
            _MODULE.PRIOR_REVISION_READ,
            'flyctl secrets list --app "${BACKEND_APP}"',
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_prior_revision_authority_hardcode_is_rejected(self) -> None:
        """A remembered default rots silently, so the capture step must read
        the previous revision, never fall back to a literal string."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = "python3 scripts/extract_staged_feature_flags.py)"
        self.assertIn(needle, text)
        mutated = _temp_workflow(
            text.replace(_MODULE.PRIOR_REVISION_READ, "", 1).replace(
                needle,
                needle + ' || echo "delivery_canary=internal"',
                1,
            )
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_capture_after_first_fly_mutation_is_rejected(self) -> None:
        """An unreadable prior rollout must abort the run before any Fly
        mutation, not after — so a capture step reordered behind one must
        fail validation."""

        marker = f"      - name: {_MODULE.CAPTURE_PREVIOUS_ROLLOUT_STEP}\n"
        mutated = self._rollback_contract_mutant(
            marker,
            "      - name: Sneak an early mutation\n"
            "        shell: bash\n"
            '        run: flyctl secrets set --stage --app "${BACKEND_APP}" FOO=bar\n'
            "\n" + marker,
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_missing_add_mask_on_captured_rollout_is_rejected(self) -> None:
        mutated = self._rollback_contract_mutant(
            'echo "::add-mask::${previous_flags}"\n', ""
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_missing_github_env_export_of_captured_rollout_is_rejected(self) -> None:
        mutated = self._rollback_contract_mutant(
            'echo "PREVIOUS_FEATURE_FLAGS=${previous_flags}" >> "${GITHUB_ENV}"\n',
            'echo "PREVIOUS_FEATURE_FLAGS=${previous_flags}"\n',
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_rollback_restore_not_using_captured_variable_is_rejected(self) -> None:
        """The rollback must restage the captured ``${PREVIOUS_FEATURE_FLAGS}``
        value, never a literal rollout guessed at rollback time."""

        mutated = self._rollback_contract_mutant(
            _MODULE.PREVIOUS_ROLLOUT_RESTORE,
            'BRAIN_BUDDY_FEATURE_FLAGS="delivery_canary=internal"',
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_restore_after_backend_image_deploy_is_rejected(self) -> None:
        """The restage must precede the backend image redeploy, because that
        deploy is the release which applies the pending secret; restaging
        after it leaves the restored image running the failed release's
        flags until some later release."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        rollback_start = text.index(f"      - name: {_MODULE.ROLLBACK_STEP}\n")
        restore_block_start = text.index("          status=0\n", rollback_start)
        images_block_start = text.index(
            '          flyctl deploy --config fly.frontend.toml --app'
            ' "${FRONTEND_APP}" \\\n',
            restore_block_start,
        )
        images_block_end = text.index(
            '            --image "${PREVIOUS_BACKEND_IMAGE}"\n', images_block_start
        ) + len('            --image "${PREVIOUS_BACKEND_IMAGE}"\n')

        restore_block = text[restore_block_start:images_block_start]
        images_block = text[images_block_start:images_block_end]
        mutated = _temp_workflow(
            text[:restore_block_start]
            + images_block
            + restore_block
            + text[images_block_end:]
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_missing_land_job_fails(self) -> None:
        mutated = _mutated_copy(DEPLOY_WORKFLOW, "\n  land:")
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_secrets_in_land_job_are_rejected(self) -> None:
        """The land job may reference only the TRUNK_LANDING_SSH_KEY landing
        secret: production credentials belong exclusively to the deploy job
        (behind the landing proof)."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = "\n  land:\n"
        self.assertIn(needle, text)
        mutated = _temp_workflow(
            text.replace(
                needle,
                "\n  land:\n    env:\n      LEAKED: ${{ secrets.FLY_API_TOKEN }}\n",
                1,
            )
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_landing_key_outside_land_job_is_rejected(self) -> None:
        """The landing deploy key is scoped to the land job; the deploy job
        must never read it."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = "    env:\n      FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}\n"
        self.assertIn(needle, text)
        mutated = _temp_workflow(
            text.replace(
                needle,
                needle + "      LEAKED: ${{ secrets.TRUNK_LANDING_SSH_KEY }}\n",
                1,
            )
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_repo_deploy_workflow_holds_no_write_token_scope(self) -> None:
        """The landing push uses the dedicated SSH deploy key; no job may
        hold GITHUB_TOKEN contents: write anymore."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("contents: write", text)

    def test_reintroduced_write_token_scope_is_rejected(self) -> None:
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(text + "\n      contents: write\n")
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_write_token_scope_on_land_job_is_rejected(self) -> None:
        """Swapping the land job's read-only token back to contents: write
        must fail: the default token must stay unable to push main."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = "    permissions:\n      contents: read\n"
        self.assertIn(needle, text)
        mutated = _temp_workflow(
            text.replace(needle, "    permissions:\n      contents: write\n", 1)
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_production_environment_on_land_job_is_rejected(self) -> None:
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = "\n  land:\n"
        mutated = _temp_workflow(
            text.replace(needle, "\n  land:\n    environment: production\n", 1)
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_masked_rollback_is_rejected(self) -> None:
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(text + "\n# sneaky\n#    flyctl deploy || true\n")
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_candidate_only_main_head_verification_is_rejected(self) -> None:
        """Re-gating the exact-main verification to candidate runs only must
        fail: it would let a stale main CI run redeploy an older SHA."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = "- name: Verify the tested revision is the exact current main head\n"
        self.assertIn(needle, text)
        mutated = _temp_workflow(
            text.replace(
                needle,
                needle
                + "        if: startsWith(github.event.workflow_run.head_branch,"
                " 'trunk-candidate/')\n",
                1,
            )
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_candidate_only_landing_proof_is_rejected(self) -> None:
        """The landing proof must also run for main CI runs; gating it to
        candidates would let a stale main run through to the deploy job."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = "- name: Prove origin/main equals the tested revision\n"
        self.assertIn(needle, text)
        mutated = _temp_workflow(
            text.replace(
                needle,
                needle
                + "        if: startsWith(github.event.workflow_run.head_branch,"
                " 'trunk-candidate/')\n",
                1,
            )
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_force_push_is_rejected(self) -> None:
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(
            text.replace("git push origin", "git push --force origin", 1)
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_operator_email_aliased_to_admin_identity_is_rejected(self) -> None:
        """The exact incident this contract exists to prevent: the operator
        allow-list re-aliased to the smoke admin identity instead of staged
        from its own dedicated secret. Every deploy would silently overwrite
        the real operator with the rotating smoke identity."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        needle = 'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS}"'
        self.assertIn(needle, text)
        mutated = _temp_workflow(
            text.replace(
                needle,
                'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_EMAIL}"',
                1,
            )
        )
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_manual_dispatch_is_rejected(self) -> None:
        """A workflow_dispatch trigger on the release workflow must fail."""

        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        mutated = _temp_workflow(text.replace("on:\n", "on:\n  workflow_dispatch:\n", 1))
        try:
            self.assertEqual(validate_deploy_workflow(mutated), 1)
        finally:
            mutated.unlink()

    def test_deploy_only_triggers_from_completed_push_ci_runs(self) -> None:
        text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("github.event.workflow_run.conclusion == 'success'", text)
        self.assertIn("github.event.workflow_run.event == 'push'", text)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", text)
        self.assertIn(
            "startsWith(github.event.workflow_run.head_branch, 'trunk-candidate/')",
            text,
        )
        self.assertNotIn("workflow_dispatch", text)


if __name__ == "__main__":
    unittest.main()
