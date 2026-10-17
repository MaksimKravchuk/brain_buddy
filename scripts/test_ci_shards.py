"""Spec 036 contracts for the CI shard helper."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import ci_shards


class BackendPartitionTests(unittest.TestCase):
    def test_036_FR_001_partitions_exactly_and_keeps_xdist_groups_together(self) -> None:
        """SC-001: grouped tests stay together in the deterministic partition."""
        ids = ["test_a.py::test_1", "test_b.py::test_2", "test_c.py::test_3"]
        assigned = ci_shards.partition_nodeids(
            ids, {ids[0]: "serial", ids[1]: "serial"}, count=2
        )
        self.assertEqual(sorted(sum(assigned, [])), sorted(ids))
        self.assertTrue(set(assigned[0]).isdisjoint(assigned[1]))
        self.assertEqual(
            next(i for i, shard in enumerate(assigned) if ids[0] in shard),
            next(i for i, shard in enumerate(assigned) if ids[1] in shard),
        )

    def test_036_FR_001_overlapping_xdist_labels_form_one_connected_group(self) -> None:
        """SC-001: overlapping marker labels coalesce transitively."""
        ids = ["a::one", "b::two", "c::three"]
        parts = ci_shards.partition_nodeids(
            ids,
            {ids[0]: ["alpha"], ids[1]: ["alpha", "beta"], ids[2]: ["beta"]},
            count=2,
        )
        self.assertTrue(any(set(ids).issubset(set(part)) for part in parts))

    def test_036_FR_001_empty_plugin_assignment_writes_zero_byte_argument_file(self) -> None:
        """SC-001: an empty runner cannot accidentally expand to the full suite."""
        class Item:
            nodeid = "single::case"

            @staticmethod
            def iter_markers(_name: str):
                return []

        class Session:
            items = [Item()]
            config = type("Config", (), {"option": type("Options", (), {"collectonly": True})()})()

        empty_index = next(
            index
            for index, part in enumerate(ci_shards.partition_nodeids(["single::case"], {}, count=2))
            if not part
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "CI_SHARD_DIR": directory,
                    "CI_SHARD_SHA": "a" * 40,
                    "CI_SHARD_INDEX": str(empty_index),
                    "CI_SHARD_COUNT": "2",
                    "CI_SHARD_MODE": "full",
                },
            ):
                ci_shards.pytest_collection_finish(Session())
            self.assertEqual((Path(directory) / "pytest-args.txt").read_bytes(), b"")

    def test_036_FR_001_rejects_empty_collection_but_allows_empty_assignment(self) -> None:
        """036-SC-001: the complete selection is nonempty; an assigned part may be empty."""
        with self.assertRaises(ValueError):
            ci_shards.partition_nodeids([], {}, count=2)
        parts = ci_shards.partition_nodeids(["only::test"], {}, count=2)
        self.assertEqual(sum(map(len, parts)), 1)
        self.assertIn([], parts)

    def test_036_FR_005_rejects_leaked_and_unsafe_manifest_paths(self) -> None:
        for value in ("/Users/max/work/app.py", "../app.py", "app/../../secret"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ci_shards.validate_repo_path(value)


class BackendEvidenceTests(unittest.TestCase):
    def _manifest(self, index: int, ids: list[str], **extra: object) -> dict[str, object]:
        assigned = ids
        return {
            "sha": "a" * 40,
            "index": index,
            "count": 2,
            "mode": "full",
            "collection": ["a::test", "b::test"],
            "assigned": assigned,
            "junit": {"tests": len(assigned), "failures": 0, "errors": 0, "skipped": 0},
            "coverage_version": "7.6.0",
            "coverage_paths": ["app/example.py"] if assigned else [],
            "coverage_file": ".coverage" if assigned else None,
            "status": "success",
            **extra,
        }

    def test_036_FR_001_validates_exact_backend_assignment_union(self) -> None:
        collection = ["a::test", "b::test"]
        parts = ci_shards.partition_nodeids(collection, {}, count=2)
        manifests = [
            self._manifest(0, parts[0]),
            self._manifest(1, parts[1]),
        ]
        ci_shards.validate_backend_manifests(manifests, sha="a" * 40)

    def test_036_FR_005_rejects_missing_duplicate_wrong_sha_and_interrupted_parts(self) -> None:
        m0, m1 = self._manifest(0, ["a::test"]), self._manifest(1, ["b::test"])
        cases = [
            ([m0], "missing"),
            ([m0, {**m1, "index": 0}], "duplicate"),
            ([m0, {**m1, "sha": "b" * 40}], "sha"),
            ([m0, {**m1, "status": "failed"}], "failed"),
        ]
        for manifests, _ in cases:
            with self.subTest(manifests=manifests), self.assertRaises(ValueError):
                ci_shards.validate_backend_manifests(manifests, sha="a" * 40)

    def test_036_FR_001_rejects_junit_count_or_result_mismatch(self) -> None:
        m0, m1 = self._manifest(0, ["a::test"]), self._manifest(1, ["b::test"])
        for change in (
            {"junit": {"tests": 2, "failures": 0, "errors": 0, "skipped": 0}},
            {"junit": {"tests": 1, "failures": 1, "errors": 0, "skipped": 0}},
            {"junit": {"tests": 1, "failures": 0, "errors": 1, "skipped": 0}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ci_shards.validate_backend_manifests([m0, {**m1, **change}], sha="a" * 40)

    def test_036_FR_001_accepts_intentionally_empty_shard(self) -> None:
        collection = ["a::test"]
        parts = ci_shards.partition_nodeids(collection, {}, count=2)
        manifests = [
            self._manifest(0, parts[0], collection=collection),
            self._manifest(1, parts[1], collection=collection),
        ]
        ci_shards.validate_backend_manifests(manifests, sha="a" * 40)

    def test_036_FR_005_backend_version_copies_allure_before_corrupt_manifest_fails(self) -> None:
        """SC-002: failed shard evidence still leaves its Allure diagnostics."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shard = root / "backend-shard-0"
            (shard / "allure-results").mkdir(parents=True)
            (shard / "allure-results" / "result.json").write_text("{}", encoding="utf-8")
            (shard / "manifest.json").write_text("{broken", encoding="utf-8")
            output = root / "output"
            with self.assertRaises(ValueError):
                ci_shards.backend_version(root, output, "a" * 40)
            self.assertEqual((output / "allure-results" / "result.json").read_text(), "{}")

    def test_036_FR_005_json_manifests_reject_known_temporary_roots(self) -> None:
        """SC-002: CI evidence cannot serialize runner-local filesystem roots."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manifest.json"
            with patch.dict(os.environ, {"RUNNER_TEMP": "/private/tmp/runner-secret"}):
                with self.assertRaisesRegex(ValueError, "temporary path"):
                    ci_shards._write_json(output, {"path": "/private/tmp/runner-secret/file"})


class MutationMergeTests(unittest.TestCase):
    def _part(self, index: int, files: list[str], ids: list[str], **extra: object) -> dict[str, object]:
        file_ids = {path: [] for path in files}
        for identity in ids:
            for path in files:
                prefix = path.removesuffix(".py").replace("/", ".") + "."
                if identity.startswith(prefix):
                    file_ids[path].append(identity)
                    break
        return {
            "sha": "a" * 40,
            "index": index,
            "count": 2,
            "requested_scope": ["app/services/tree_service.py", "app/services/task.py"],
            "assigned": files,
            "status": "success",
            "identities": ids,
            "file_identities": file_ids,
            "identity_counters": {"killed": len(ids), "survived": 0, "total": len(ids), "no_tests": 0, "skipped": 0, "suspicious": 0, "timeout": 0, "check_was_interrupted_by_user": 0, "segfault": 0},
            "stats": {"killed": len(ids), "survived": 0, "total": len(ids), "no_tests": 0, "skipped": 0, "suspicious": 0, "timeout": 0, "check_was_interrupted_by_user": 0, "segfault": 0},
            **extra,
        }

    def test_036_FR_003_merges_disjoint_scope_and_sums_raw_counters(self) -> None:
        """036-SC-002: preserve every mutant and judge the combined raw counts."""
        """SC-002: aggregate raw counters produce a weighted checked total."""
        parts = [
            self._part(0, ["app/services/tree_service.py"], ["app.services.tree_service.x1"]),
            self._part(1, ["app/services/task.py"], ["app.services.task.x1", "app.services.task.x2"]),
        ]
        result = ci_shards.merge_mutation_manifests(parts, sha="a" * 40)
        self.assertEqual(result["stats"]["killed"], 3)
        self.assertEqual(result["stats"]["total"], 3)

    def test_036_FR_003_requires_metadata_for_zero_mutant_assigned_file(self) -> None:
        """SC-002: a zero-mutant file still needs a per-file metadata entry."""
        parts = [
            self._part(0, ["app/services/tree_service.py"], []),
            self._part(1, ["app/services/task.py"], ["app.services.task.x1"]),
        ]
        parts[0]["file_identities"] = {}
        with self.assertRaisesRegex(ValueError, "per-file mutation metadata"):
            ci_shards.merge_mutation_manifests(parts, sha="a" * 40)

    def test_036_FR_003_accepts_explicit_empty_part(self) -> None:
        parts = [
            self._part(0, [], [], requested_scope=["app/services/task.py"]),
            self._part(1, ["app/services/task.py"], ["app.services.task.x1"], requested_scope=["app/services/task.py"]),
        ]
        result = ci_shards.merge_mutation_manifests(parts, sha="a" * 40)
        self.assertEqual(result["stats"]["killed"], 1)

    def test_036_FR_003_rejects_missing_scope_duplicate_identity_bad_stats_and_interruption(self) -> None:
        p0 = self._part(0, ["app/services/tree_service.py"], ["m1"])
        p1 = self._part(1, ["app/services/task.py"], ["m2"])
        cases = [
            [p0],
            [p0, {**p1, "assigned": ["app/services/tree_service.py"]}],
            [p0, {**p1, "identities": ["m1"]}],
            [p0, {**p1, "stats": {**p1["stats"], "killed": -1}}],
            [p0, {**p1, "stats": {**p1["stats"], "check_was_interrupted_by_user": 1}}],
            [p0, {**p1, "sha": "b" * 40}],
            [p0, {**p1, "status": None}],
        ]
        for parts in cases:
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                ci_shards.merge_mutation_manifests(parts, sha="a" * 40)



class WorkflowEmptyMutationTests(unittest.TestCase):
    def test_036_FR_003_workflow_empty_assignment_records_complete_zero_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/ci.yml").read_text()
        emitters = re.findall(r"python3 -c '([^']+)' \\\n            ([^\n]+/assignment.json) > /tmp/assigned-scope.txt", workflow)
        zeros = re.findall(r"python3 -c '([^']+)' ([^\n]+/mutation-stats.json)", workflow)
        self.assertEqual(len(emitters), 2)
        self.assertEqual(len(zeros), 2)
        for emitter, zero in zip(emitters, zeros):
            with self.subTest(), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                assignment = folder / "assignment.json"
                ci_shards._write_json(assignment, {
                    "sha": "a" * 40, "index": 0, "count": 2,
                    "requested_scope": ["app/services/version_service.py"], "assigned": [],
                })
                emitted = subprocess.check_output([sys.executable, "-c", emitter[0], str(assignment)])
                self.assertEqual(emitted, b"")
                stats = folder / "mutation-stats.json"
                subprocess.run([sys.executable, "-c", zero[0], str(stats)], cwd=root, check=True)
                self.assertEqual(ci_shards.main([
                    "mutation-record", "--assignment", str(assignment),
                    "--meta", str(folder / "absent"), "--stats", str(stats),
                    "--output", str(folder / "manifest.json"),
                ]), 0)
                manifest = json.loads((folder / "manifest.json").read_text())
                self.assertEqual(manifest["identities"], [])
                self.assertEqual(manifest["stats"]["total"], 0)

if __name__ == "__main__":
    unittest.main()
