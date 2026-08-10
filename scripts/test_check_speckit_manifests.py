"""Contract tests for the Spec Kit preserved-override guard."""

from __future__ import annotations

import importlib.util
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

    def test_both_implement_copies_are_protected(self) -> None:
        protected = set(self.module.PRESERVED_OVERRIDES)
        self.assertIn(".claude/skills/speckit-implement/SKILL.md", protected)
        self.assertIn(".agents/skills/speckit-implement/SKILL.md", protected)

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

    def test_implement_skill_is_not_disabled(self) -> None:
        """Regression: the implement skill used to refuse to run at all.

        `CLAUDE.md`, the constitution and `docs/spec-kit-workflow.md` all say
        the artifacts may be implemented directly, so a disabled skill left an
        agent that reads skills first with no legal way to proceed.
        """
        for relative in (
            ".claude/skills/speckit-implement/SKILL.md",
            ".agents/skills/speckit-implement/SKILL.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("user-invocable: false", text, relative)
            self.assertNotIn("disable-model-invocation: true", text, relative)
            self.assertNotIn("DISABLED in BrainBuddy", text, relative)


if __name__ == "__main__":
    unittest.main()
