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
