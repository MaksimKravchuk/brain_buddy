"""The component -> release graph reads the Rust crate closure from Cargo manifests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_graph


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class RustClosureTests(unittest.TestCase):
    def test_closure_follows_workspace_path_and_target_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root,
                {
                    "rust/Cargo.toml": (
                        "[workspace]\nmembers = [\"app\", \"core\", \"leaf\", \"other\"]\n"
                        "[workspace.dependencies]\n"
                        "core = { path = \"core\" }\nleaf = { path = \"leaf\" }\n"
                        "serde = \"1\"\n"
                    ),
                    "rust/app/Cargo.toml": (
                        "[package]\nname = \"app\"\n[dependencies]\ncore.workspace = true\n"
                        "serde.workspace = true\n"
                        "[dev-dependencies]\nother = { path = \"../other\" }\n"
                    ),
                    "rust/core/Cargo.toml": (
                        "[package]\nname = \"core\"\n"
                        "[target.'cfg(unix)'.dependencies]\nleaf = { workspace = true }\n"
                    ),
                    "rust/leaf/Cargo.toml": "[package]\nname = \"leaf\"\n",
                    "rust/other/Cargo.toml": "[package]\nname = \"other\"\n",
                },
            )
            crates = release_graph.rust_crates(root)
            self.assertEqual(
                release_graph.rust_closure("app", crates),
                ["rust/app/", "rust/core/", "rust/leaf/"],
                "dev-dependencies never reach the shipped library",
            )
            with self.assertRaises(KeyError):
                release_graph.rust_closure("missing", crates)

    def test_repo_graph_links_the_ios_app_and_backend_to_their_bindings(self) -> None:
        graph = release_graph.Graph()
        self.assertIn("rust/bindings/swift/", graph.crate_dirs["ios-testflight"])
        self.assertIn("rust/bindings/python/", graph.crate_dirs["fly-backend"])
        self.assertNotIn("rust/crates/bb-server/", graph.crate_dirs["ios-testflight"])
        self.assertNotIn("rust/crates/bb-server/", graph.crate_dirs["fly-backend"])
        self.assertEqual(graph.crate_dirs["fly-frontend"], [])
        self.assertFalse(graph.reaches("fly-frontend", "rust/crates/bb-domain/src/lib.rs"))


if __name__ == "__main__":
    unittest.main()
