"""Tests for scripts/check_crate_graph.py (027-FR-008, 027-SC-006)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_crate_graph as cg  # noqa: E402


def meta(**deps: list[str]) -> dict:
    pk = []
    for name, ds in deps.items():
        entries = []
        for d in ds:
            n, _, kind = d.partition(":")
            entries.append({"name": n, "kind": kind or None})
        pk.append({"name": name.replace("_", "-"), "dependencies": entries})
    return {"packages": pk}


def tree(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return root


class CrateEdges(unittest.TestCase):
    def test_027_fr_008_allowed_graph_passes(self) -> None:
        m = meta(
            bb_api=["bb-app"],
            bb_app=["bb-store", "bb-providers", "bb-domain", "bb-protocol"],
            bb_store=["bb-domain"],
            bb_domain=["bb-protocol"],
            bb_protocol=["serde"],
            bb_providers=[],
            bb_server=["bb-api", "bb-store"],
        )
        self.assertEqual(cg.edge_violations(m), [])

    def test_027_fr_008_api_to_store_fails_even_as_dev_dep(self) -> None:
        for suffix in ("", ":dev"):
            m = meta(bb_api=["bb-app", "bb-store" + suffix], bb_app=[], bb_store=[])
            self.assertTrue(cg.edge_violations(m), suffix)

    def test_027_fr_008_store_to_app_and_domain_io_fail(self) -> None:
        self.assertTrue(cg.edge_violations(meta(bb_store=["bb-app"], bb_app=[])))
        self.assertTrue(cg.edge_violations(meta(bb_domain=["sqlx"])))
        self.assertTrue(cg.edge_violations(meta(bb_protocol=["axum"])))
        self.assertEqual(cg.edge_violations(meta(bb_domain=["tokio:dev"])), [])


class UsePaths(unittest.TestCase):
    def test_027_fr_008_grouped_and_inline_paths_expand(self) -> None:
        src = (
            "use bb_store::{tasks::Repo, identity::{User, self}}; // bb_store::crt\n"
            "fn f() { bb_store::voice::x(); }"
        )
        got = cg.references(src, ("bb_store",))
        self.assertIn(("tasks", "Repo"), got)
        self.assertIn(("identity", "User"), got)
        self.assertIn(("voice", "x"), got)
        self.assertNotIn(("crt",), got)


class ModuleOwnership(unittest.TestCase):
    def test_027_fr_008_app_module_imports(self) -> None:
        src = tree(
            {
                "lib.rs": "",
                "identity/mod.rs": "use bb_store::identity::Users;",
                "tasks/mod.rs": "use bb_store::tasks::Repo;",
                "review.rs": "use bb_store::tasks::Review;",
                "sync/feed.rs": "use bb_store::{tasks::Tx};",
                "jobs.rs": "use bb_store::tasks::Jobs;",
                "navigator.rs": "use bb_store::tasks::Nav;",
                "ai.rs": "use bb_store::tasks::X;",
                "ports/control.rs": "use bb_store::control::Ledger;",
            }
        )
        self.assertEqual(cg.app_violations(src), [])

    def test_027_fr_008_cross_module_store_import_fails(self) -> None:
        src = tree({"identity/mod.rs": "use bb_store::tasks::Repo;"})
        self.assertEqual(len(cg.app_violations(src)), 1)
        src = tree({"crt.rs": "use bb_store::{crt::A, voice::B};"})
        self.assertEqual(len(cg.app_violations(src)), 1)
        # Control is reachable only through bb_app::ports::control.
        src = tree({"tasks/mod.rs": "fn f() { bb_store::control::mark_applied(); }"})
        self.assertEqual(len(cg.app_violations(src)), 1)

    def test_027_fr_008_store_control_exception_is_only_mark_applied(self) -> None:
        ok = tree(
            {
                "crt.rs": "use crate::control::mark_applied;\nuse crate::crt::X;",
                "tasks.rs": "use bb_store::control::{mark_applied};",
                "error.rs": "use crate::tasks::T;",
            }
        )
        self.assertEqual(cg.store_violations(ok), [])
        for bad in (
            "use crate::tasks::Repo;",
            "use crate::control::Ledger;",
            "use crate::control::{mark_applied, Ledger};",
            "use crate::control;",
        ):
            self.assertTrue(cg.store_violations(tree({"crt.rs": bad})), bad)


if __name__ == "__main__":
    unittest.main()
