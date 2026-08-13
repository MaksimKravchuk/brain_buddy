"""Contract tests for the Spec Kit preserved-override guard."""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_speckit_manifests.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_speckit_manifests", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreservedOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_repository_overrides_are_all_intact(self) -> None:
        self.assertEqual(self.module.check(ROOT), [])

    def test_the_implement_policy_is_protected(self) -> None:
        """One tree now. The Codex twin was removed with `.agents/`.

        The override still matters for the same reason it always did: it is
        the implement-directly policy, and `specify integration upgrade
        claude --force` would silently restore upstream's refuse-and-route.
        """
        protected = set(self.module.PRESERVED_OVERRIDES)
        self.assertIn(".claude/skills/speckit-implement/SKILL.md", protected)
        self.assertNotIn(".agents/skills/speckit-implement/SKILL.md", protected)

    def test_all_four_customized_templates_are_protected(self) -> None:
        protected = set(self.module.PRESERVED_OVERRIDES)
        for name in ("spec", "plan", "tasks", "checklist"):
            self.assertIn(f".specify/templates/{name}-template.md", protected)

    def test_reverted_file_is_reported(self) -> None:
        """A file overwritten with upstream content loses its marker."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            (fake_root / ".specify").mkdir()
            for relative in self.module.PRESERVED_OVERRIDES:
                path = fake_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("upstream content with no override\n", encoding="utf-8")

            failures = self.module.check(fake_root)
            self.assertEqual(len(failures), len(self.module.PRESERVED_OVERRIDES))
            self.assertTrue(all("override marker" in item for item in failures))

    def test_missing_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            (fake_root / ".specify").mkdir()
            failures = self.module.check(fake_root)
            self.assertTrue(all("MISSING" in item for item in failures))

    def test_every_hooked_command_resolves_to_an_installed_skill(self) -> None:
        """A hook naming a skill that does not exist stops the pipeline.

        This was a two-tree parity check while `.agents/` existed. Removing
        that tree narrows the check but does not retire it: the failure mode
        was never specific to Codex. A mandatory hook whose SKILL.md is absent
        makes the running agent emit EXECUTE_COMMAND for a command it cannot
        invoke, and the stage dies there.

        Note for anyone reading this while considering a new hook: this guard
        now says nothing about `assess`. It ships Claude skills, so hooking it
        would pass here. The reason it stays unhooked is in the extensions.yml
        comment and is about stage 0 being optional, not about tree parity.
        """
        extensions = ROOT / ".specify" / "extensions.yml"
        self.assertTrue(extensions.is_file(), "extensions.yml is missing")

        commands = re.findall(
            r"^\s*command:\s*([\w.]+)\s*$",
            extensions.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        self.assertTrue(commands, "extensions.yml registers no hook commands")

        missing = [
            f".claude/skills/{command.replace('.', '-')}/SKILL.md (hook `{command}`)"
            for command in commands
            if not (
                ROOT / ".claude/skills" / command.replace(".", "-") / "SKILL.md"
            ).is_file()
        ]

        self.assertEqual(missing, [], f"hooked skills with no SKILL.md: {missing}")

    def test_the_codex_tree_is_gone_and_nothing_resolves_into_it(self) -> None:
        """No *functional* reference to `.agents/` survives.

        Deliberately not a blanket text ban. The first version of this test
        was one, and it failed on the extensions.yml comment explaining why
        the tree was removed and what that costs — prose the removal was
        required to add. A guard that forbids documenting a change is worse
        than no guard: the cheapest way to satisfy it is to delete the
        explanation.
        """
        self.assertFalse((ROOT / ".agents").exists(), "`.agents/` is back")
        self.assertFalse(
            any(key.startswith(".agents/") for key in self.module.PRESERVED_OVERRIDES),
            "a preserved override still points into the removed tree",
        )
        integration = json.loads(
            (ROOT / ".specify" / "integration.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("codex", integration["installed_integrations"])
        self.assertNotIn("codex", integration["integration_settings"])
        self.assertFalse(
            (ROOT / ".specify" / "integrations" / "codex.manifest.json").exists()
        )

    def test_the_workflow_registry_describes_the_workflow_it_registers(self) -> None:
        """The registry drifted three versions behind the file it points at.

        `workflow-registry.json` is what `specify workflow list` prints, so it
        is the first and often only description a reader sees. It still
        advertised "Spec Kit Planning Cycle" v1.0.0 — "runs specify -> clarify
        -> plan -> checklist -> tasks, then stops for Hermes Kanban handoff" —
        while `workflow.yml` had become the v3.0.0 portable spec review gate of
        ADR-0011. Two of the three claims were not merely dated but inverted:
        the workflow does not author anything, and ADR-0010 made the Kanban
        handoff opt-in rather than the terminus.

        Identity and version are asserted exactly. The description is only
        checked for the superseded claim, because pinning prose exactly would
        make every wording change a two-file edit for no safety.

        `installed_at` and `updated_at` are deliberately left at the values the
        `specify` CLI wrote. Only name/version/description were corrected by
        hand, and stamping a fresh `updated_at` would assert a CLI write that
        never happened. This test is what keeps them honest instead.
        """
        registry = json.loads(
            (ROOT / ".specify/workflows/workflow-registry.json").read_text(
                encoding="utf-8"
            )
        )
        workflow_yml = (ROOT / ".specify/workflows/speckit/workflow.yml").read_text(
            encoding="utf-8"
        )

        def field(name: str) -> str:
            """Regex, not PyYAML: it is not a dependency of this repository.

            `WorkflowContractTests` in test_spec_kit_planning_review.py reads
            the same file the same way, so this follows the existing
            convention rather than adding an install to run `make check-specs`.
            Tolerates any indent and optional single/double quotes so a
            reformat of workflow.yml does not read as a drift failure.
            """
            match = re.search(
                rf"""^\s*{name}:\s*(?:"([^"]*)"|'([^']*)'|(\S.*?))\s*$""",
                workflow_yml,
                re.MULTILINE,
            )
            self.assertIsNotNone(match, f"workflow.yml has no {name}")
            assert match is not None
            value = next(group for group in match.groups() if group is not None)
            return value

        entry = registry["workflows"]["speckit"]
        self.assertEqual(entry["name"], field("name"))
        self.assertEqual(entry["version"], field("version"))
        self.assertNotIn("Kanban", entry["description"])
        self.assertNotIn("Hermes", entry["description"])

    def test_portable_core_templates_name_no_execution_runtime(self) -> None:
        """ADR-0010's own verification step, mechanized.

        The four core templates are copied into every feature's artifacts, so
        they are the portable surface ADR-0010 protects: "the main Spec Kit
        task template stays portable. Managed metadata is documented only in
        `.hermes.md` and `docs/spec-driven-kanban.md`." That ADR lists "verify
        portable instruction files contain no mandatory plugin calls or managed
        task grammar" as a manual check; nothing ran it, and
        `checklist-template.md` shipped a Hermes Kanban handoff to every
        feature generated from it.

        Scoped to `.specify/templates/` on purpose. A repository-wide ban on
        the word would forbid ADR-0010, the runbook and the skill wrappers from
        describing the opt-in overlay that genuinely exists — the same trap
        `test_the_codex_tree_is_gone_and_nothing_resolves_into_it` documents.
        Templates are different: they are emitted, not read, so they are the
        one place the overlay must never be mentioned by default.
        """
        offenders = [
            f"{name}-template.md: {term}"
            for name in ("spec", "plan", "tasks", "checklist")
            for term in ("Hermes", "Kanban")
            if term
            in (ROOT / ".specify/templates" / f"{name}-template.md").read_text(
                encoding="utf-8"
            )
        ]
        self.assertEqual(
            offenders, [], f"portable templates name an execution runtime: {offenders}"
        )

    def test_implement_skill_is_not_disabled(self) -> None:
        """Regression: the implement skill used to refuse to run at all.

        `CLAUDE.md`, the constitution and `docs/spec-kit-workflow.md` all say
        the artifacts may be implemented directly, so a disabled skill left an
        agent that reads skills first with no legal way to proceed.
        """
        relative = ".claude/skills/speckit-implement/SKILL.md"
        text = (ROOT / relative).read_text(encoding="utf-8")
        self.assertNotIn("user-invocable: false", text, relative)
        self.assertNotIn("disable-model-invocation: true", text, relative)
        self.assertNotIn("DISABLED in BrainBuddy", text, relative)


if __name__ == "__main__":
    unittest.main()
