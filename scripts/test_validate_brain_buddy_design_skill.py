import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "brain-buddy-design"


class BrainBuddyDesignSkillContractTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (SKILL / relative_path).read_text(encoding="utf-8")

    def test_gtd_navigation_uses_four_primary_lists_tags_and_deferred_review(self) -> None:
        readme = self.read("README.md")
        skill = self.read("SKILL.md")
        nav = self.read("preview/components-gtd-nav.html")
        task_rows = self.read("preview/components-task-rows.html")
        ai_states = self.read("preview/components-ai-states.html")
        tokens = self.read("colors_and_type.css")

        self.assertIn(
            "`Inbox` → `Next actions` → `Waiting for` → `Someday / maybe`",
            readme,
        )
        self.assertIn("exactly four open GTD primary lists", readme)
        self.assertIn("Weekly Review remains visibly deferred", readme)
        self.assertIn("Projects and Tags", readme)
        self.assertIn("exactly four open GTD primary lists", skill)
        self.assertIn("Weekly Review remains visibly deferred", skill)
        self.assertIn("coming later", nav)
        self.assertIn(">Tags<", nav)
        self.assertNotRegex(
            "\n".join((readme, skill, nav, task_rows, tokens)),
            re.compile(r"Contexts?|@context|--bb-context", re.IGNORECASE),
        )
        self.assertNotRegex(task_rows, re.compile(r">@[a-z-]+<"))
        self.assertNotIn("due Sun", ai_states)

    def test_voice_copy_distinguishes_durable_capture_from_task_authority(self) -> None:
        readme = self.read("README.md")
        preview = self.read("preview/components-brain-dump.html")
        combined = "\n".join((readme, preview))

        self.assertIn("durable numbered chunks", combined)
        self.assertIn("Provisional", combined)
        self.assertIn("Stop & review", combined)
        self.assertIn("Confirm N additions", combined)
        self.assertIn("No canonical Task is created before explicit confirmation", combined)
        self.assertNotIn("Nothing is saved until you stop", combined)
        self.assertNotRegex(combined, re.compile(r"Stop & send .* inbox", re.IGNORECASE))

    def test_execution_material_is_non_shipped_and_separate_from_tasks(self) -> None:
        readme = self.read("README.md")
        agents = self.read("preview/components-agents.html")
        run_log = self.read("preview/components-agent-log.html")
        ai_states = self.read("preview/components-ai-states.html")
        task_rows = self.read("preview/components-task-rows.html")

        for content in (readme, agents, run_log, ai_states, task_rows):
            self.assertIn("Speculative, non-shipped", content)
            self.assertIn("accepted Execution contract", content)
            self.assertIn("separate from Task lifecycle", content)
        self.assertIn("A successful run never completes a Task", readme)
        self.assertNotIn("AI is a first-class executor", readme)
        self.assertNotIn("**Agents** are named executors", readme)

    def test_node_colors_and_logo_have_single_authoritative_sources(self) -> None:
        readme = self.read("README.md")
        nodes = self.read("preview/colors-nodes.html").lower()
        logo = self.read("preview/logo.html")

        self.assertIn("--bb-node-root-bg", nodes)
        self.assertIn("#facc15", nodes)
        self.assertIn("--bb-node-leaf-bg", nodes)
        self.assertIn("#ef4444", nodes)
        self.assertNotIn("--bb-warning", nodes)
        self.assertNotIn("--bb-danger", nodes)
        self.assertIn("assets/logo.svg", logo)
        self.assertIn("assets/logo-lockup.svg", logo)
        self.assertNotIn("<svg", logo)
        self.assertIn("authoritative logo sources", readme)
        self.assertIn("authoritative node-color tokens", readme)

    def test_adherence_and_generated_bundle_guidance_match_workspace_kit(self) -> None:
        adherence = json.loads(self.read("_adherence.oxlintrc.json"))
        kit_readme = self.read("ui_kits/workspace/README.md")
        root_readme = self.read("README.md")
        bundle = self.read("_ds_bundle.js")

        self.assertNotIn("no-restricted-imports", adherence["rules"])
        self.assertNotIn("index.js", json.dumps(adherence))
        self.assertIn("browser-global scripts", kit_readme)
        self.assertIn("generated artifact; do not edit", root_readme)
        self.assertIn("Regenerate `_ds_bundle.js`", root_readme)
        self.assertIn("12-character SHA-256", root_readme)

        header = re.match(r"/\* @ds-bundle: (\{.*?\}) \*/", bundle)
        if header is None:
            self.fail("_ds_bundle.js is missing its metadata header")
        source_hashes = json.loads(header.group(1))["sourceHashes"]
        for relative_path, expected_hash in source_hashes.items():
            actual_hash = hashlib.sha256(
                self.read(relative_path).encode("utf-8")
            ).hexdigest()[:12]
            self.assertEqual(expected_hash, actual_hash, relative_path)

    def test_manifest_matches_card_headers_and_skill_is_discoverable(self) -> None:
        manifest = json.loads(self.read("_ds_manifest.json"))
        card_paths = {
            path.relative_to(SKILL).as_posix()
            for path in SKILL.rglob("*.html")
            if "@dsCard" in path.read_text(encoding="utf-8")
        }
        self.assertEqual({card["path"] for card in manifest["cards"]}, card_paths)

        header_pattern = re.compile(
            r'@dsCard group="(?P<group>[^"]+)" name="(?P<name>[^"]+)" '
            r'subtitle="(?P<subtitle>[^"]+)" viewport="(?P<viewport>[^"]+)"'
        )
        for card in manifest["cards"]:
            match = header_pattern.search(self.read(card["path"]))
            if match is None:
                self.fail(f"Missing @dsCard header: {card['path']}")
            for field in ("group", "name", "subtitle", "viewport"):
                self.assertEqual(card[field], match.group(field), card["path"])

        skill = self.read("SKILL.md")
        self.assertTrue(skill.startswith("---\nname: brain-buddy-design\n"))
        self.assertIn("\nuser-invocable: true\n---\n", skill)


if __name__ == "__main__":
    unittest.main()
