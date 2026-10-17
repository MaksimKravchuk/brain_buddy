"""Standard-library helpers for Spec 036 required-CI sharding.

The pytest hooks deliberately do not import pytest at module import time, so
the validators can exercise the contracts with the standard library alone.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import sqlite3
import sys
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

SHARD_COUNT = 2
MUTATION_COUNTERS = (
    "killed",
    "survived",
    "total",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid or missing JSON evidence: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    private_roots = [
        os.environ.get(name, "")
        for name in ("GITHUB_WORKSPACE", "HOME", "RUNNER_TEMP")
    ]

    def strings(item: Any) -> Iterable[str]:
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for key, nested in item.items():
                yield str(key)
                yield from strings(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                yield from strings(nested)

    text_values = list(strings(value))
    for root in filter(None, private_roots):
        if len(root) > 3 and any(root in text for text in text_values):
            raise ValueError("manifest contains a workspace, home, or temporary path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _check_shard(index: int, count: int) -> None:
    if count != SHARD_COUNT or index not in range(SHARD_COUNT):
        raise ValueError("Spec 036 requires exactly two shard indexes: 0 and 1")


def _unique(values: Iterable[str], description: str) -> list[str]:
    result = list(values)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate {description}")
    return result


def partition_nodeids(
    nodeids: list[str], groups: dict[str, str | list[str]], *, count: int
) -> list[list[str]]:
    """Split IDs deterministically while keeping each xdist group connected."""
    if count != SHARD_COUNT:
        raise ValueError("backend collection must use exactly two shards")
    ids = _unique(nodeids, "pytest node id")
    if not ids:
        raise ValueError("whole pytest collection is empty")
    parent = {nodeid: nodeid for nodeid in ids}

    def find(nodeid: str) -> str:
        while parent[nodeid] != nodeid:
            parent[nodeid] = parent[parent[nodeid]]
            nodeid = parent[nodeid]
        return nodeid

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    by_group: dict[str, list[str]] = defaultdict(list)
    for nodeid in ids:
        raw_groups = groups.get(nodeid, [])
        labels = [raw_groups] if isinstance(raw_groups, str) else raw_groups
        if not isinstance(labels, list) or any(not isinstance(label, str) or not label for label in labels):
            raise ValueError("xdist group labels are corrupt")
        for label in labels:
            by_group[label].append(nodeid)
    for members in by_group.values():
        for nodeid in members[1:]:
            union(members[0], nodeid)

    components: dict[str, list[str]] = defaultdict(list)
    for nodeid in ids:
        components[find(nodeid)].append(nodeid)
    parts: list[list[str]] = [[], []]
    # Hash the component's stable contents, not discovery order.
    for members in sorted(components.values(), key=lambda items: min(items)):
        key = "\n".join(sorted(members)).encode("utf-8")
        bucket = int(hashlib.sha256(key).hexdigest(), 16) % count
        parts[bucket].extend(members)
    return [sorted(part) for part in parts]


def pytest_collection_finish(session: Any) -> None:
    """Pytest plugin hook: persist whole collection and this runner's assignment."""
    if not session.config.option.collectonly:
        return
    raw_dir = os.environ.get("CI_SHARD_DIR")
    raw_sha = os.environ.get("CI_SHARD_SHA")
    raw_index = os.environ.get("CI_SHARD_INDEX")
    raw_count = os.environ.get("CI_SHARD_COUNT")
    mode = os.environ.get("CI_SHARD_MODE")
    if not all((raw_dir, raw_sha, raw_index, raw_count, mode)):
        raise ValueError("CI_SHARD_* collection environment is incomplete")
    index, count = int(raw_index), int(raw_count)
    _check_shard(index, count)
    if mode not in {"full", "selected"}:
        raise ValueError("CI_SHARD_MODE must be full or selected")
    nodeids = [item.nodeid for item in session.items]
    groups: dict[str, list[str]] = {}
    for item in session.items:
        labels = []
        for marker in item.iter_markers("xdist_group"):
            if marker.args:
                labels.append(str(marker.args[0]))
            elif marker.kwargs.get("name"):
                labels.append(str(marker.kwargs["name"]))
        if labels:
            groups[item.nodeid] = sorted(set(labels))
    parts = partition_nodeids(nodeids, groups, count=count)
    output = Path(raw_dir)
    output.mkdir(parents=True, exist_ok=True)
    collection = sorted(nodeids)
    assignment = {
        "sha": raw_sha,
        "index": index,
        "count": count,
        "mode": mode,
        "collection": collection,
        "groups": groups,
        "assigned": parts[index],
    }
    _write_json(output / "collection.json", {"sha": raw_sha, "mode": mode, "nodeids": collection})
    _write_json(output / "assignment.json", assignment)
    (output / "pytest-args.txt").write_text(
        "\n".join(parts[index]) + ("\n" if parts[index] else ""),
        encoding="utf-8",
    )


def validate_repo_path(value: str) -> str:
    """Validate an artifact path is a relative backend source path."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("artifact contains an unsafe path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("artifact contains an unsafe path")
    if path.parts[0] != "app" or not value.endswith(".py"):
        raise ValueError("artifact contains an unexpected source path")
    return value


def _validate_coverage_db(path: Path) -> list[str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("coverage database is missing or empty")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            rows = db.execute("SELECT path FROM file").fetchall()
    except sqlite3.Error as exc:
        raise ValueError("coverage database is corrupt") from exc
    paths = _unique([validate_repo_path(str(row[0])) for row in rows], "coverage path")
    if not paths:
        raise ValueError("coverage database measured no app files")
    return sorted(paths)


def junit_counts(path: Path) -> dict[str, int]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("JUnit report is missing or corrupt") from exc
    cases = list(root.iter("testcase"))
    failures = sum(1 for case in cases if case.find("failure") is not None)
    errors = sum(1 for case in cases if case.find("error") is not None)
    skipped = sum(1 for case in cases if case.find("skipped") is not None)
    return {"tests": len(cases), "failures": failures, "errors": errors, "skipped": skipped}


def validate_backend_manifests(
    manifests: list[dict[str, Any]], *, sha: str
) -> dict[str, Any]:
    if len(manifests) != SHARD_COUNT:
        raise ValueError("backend aggregation requires exactly two shard manifests")
    if any(not isinstance(manifest, dict) for manifest in manifests):
        raise ValueError("backend manifest is corrupt")
    by_index: dict[int, dict[str, Any]] = {}
    for manifest in manifests:
        index = manifest.get("index")
        if index not in (0, 1) or index in by_index:
            raise ValueError("backend manifest index is missing or duplicated")
        by_index[index] = manifest
    if set(by_index) != {0, 1}:
        raise ValueError("backend shard index is missing")
    first = by_index[0]
    if first.get("sha") != sha or first.get("count") != 2:
        raise ValueError("backend shard SHA or count does not match candidate")
    mode, collection = first.get("mode"), first.get("collection")
    if mode not in {"full", "selected"} or not isinstance(collection, list) or not collection:
        raise ValueError("backend whole collection or mode is invalid")
    _unique(collection, "collected node id")
    groups = first.get("groups", {})
    if not isinstance(groups, dict) or any(key not in collection for key in groups):
        raise ValueError("backend xdist group evidence is corrupt")
    expected_parts = partition_nodeids(collection, groups, count=2)
    assignments: list[str] = []
    for index in (0, 1):
        item = by_index[index]
        if item.get("sha") != sha or item.get("count") != 2:
            raise ValueError("backend shard SHA or count does not match candidate")
        if item.get("mode") != mode or item.get("collection") != collection or item.get("groups", {}) != groups:
            raise ValueError("backend collection or mode differs between shards")
        if item.get("status") != "success":
            raise ValueError("backend shard failed or was interrupted")
        assigned = item.get("assigned")
        junit = item.get("junit")
        if not isinstance(assigned, list) or not isinstance(junit, dict):
            raise ValueError("backend assignment or JUnit evidence is corrupt")
        _unique(assigned, "assigned pytest node id")
        if junit.get("tests") != len(assigned) or junit.get("failures") != 0 or junit.get("errors") != 0:
            raise ValueError("JUnit counts do not prove successful assigned execution")
        if not set(assigned).issubset(collection):
            raise ValueError("backend assignment contains an uncollected test")
        if sorted(assigned) != expected_parts[index]:
            raise ValueError("backend assignment differs from deterministic grouped partition")
        if not item.get("coverage_version") or not re.fullmatch(r"\d+(?:\.\d+){1,3}", str(item.get("coverage_version"))):
            raise ValueError("backend shard coverage version is missing or invalid")
        if assigned:
            if not item.get("coverage_paths"):
                raise ValueError("nonempty backend shard lacks coverage evidence")
        elif junit.get("tests") != 0 or item.get("coverage_paths"):
            raise ValueError("empty backend assignment has unexpected execution payload")
        assignments.extend(assigned)
    _unique(assignments, "backend assigned pytest node id")
    if sorted(assignments) != sorted(collection):
        raise ValueError("backend assignments do not equal the whole collection")
    versions = {by_index[i].get("coverage_version") for i in (0, 1)}
    if len(versions) > 1:
        raise ValueError("coverage tool versions differ between backend shards")
    return {"mode": mode, "collection": collection, "assignments": assignments, "coverage_version": next(iter(versions), None)}


def _read_artifact_manifests(root: Path, name: str) -> list[tuple[Path, dict[str, Any]]]:
    found = []
    names = {name, "manifest.json"}
    paths = sorted({path for candidate in names for path in root.glob(f"*/{candidate}")})
    for manifest_path in paths:
        try:
            manifest = _read_json(manifest_path)
        except ValueError:
            raise
        found.append((manifest_path.parent, manifest))
    return found


def _copy_allure_diagnostics(artifacts: Path, output_dir: Path) -> None:
    """Preserve diagnostic files without relying on valid shard manifests."""
    target = output_dir / "allure-results"
    for source in sorted(artifacts.glob("*/allure-results")):
        if not source.is_dir():
            continue
        target.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            dest = target / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)


def _context_map(coverage: Any) -> dict[str, dict[int, set[str]]]:
    data = coverage.get_data()
    result: dict[str, dict[int, set[str]]] = {}
    for filename in data.measured_files():
        normalized = filename.replace("\\", "/")
        validate_repo_path(normalized)
        result[normalized] = {
            int(line): set(contexts)
            for line, contexts in data.contexts_by_lineno(filename).items()
        }
    return result


def _merge_coverage(files: list[Path], output_dir: Path, version: str | None) -> None:
    if not files:
        return
    import coverage  # Imported only after aggregator installs the existing tool.

    if coverage.__version__ != version:
        raise ValueError("aggregator coverage version differs from shard version")
    expected: dict[str, dict[int, set[str]]] = {}
    for path in files:
        cov = coverage.Coverage(data_file=str(path))
        cov.load()
        for filename, line_map in _context_map(cov).items():
            dest = expected.setdefault(filename, {})
            for line, contexts in line_map.items():
                dest.setdefault(line, set()).update(contexts)
    output_dir = output_dir.resolve()
    files = [path.resolve() for path in files]
    target = output_dir / ".coverage"
    target.unlink(missing_ok=True)
    previous_cwd = Path.cwd()
    try:
        # Coverage must map relative database names in the reporting workspace.
        os.chdir(output_dir)
        combined = coverage.Coverage(data_file=str(target), source=["app"])
        combined.set_option("run:relative_files", True)
        combined.combine(data_paths=[str(path) for path in files], strict=True, keep=True)
        combined.load()
        actual = _context_map(combined)
        if actual != expected:
            raise ValueError("combined coverage contexts differ from shard union")
        combined.xml_report(outfile="coverage.xml")
    finally:
        os.chdir(previous_cwd)


def merge_backend(artifacts: Path, output_dir: Path, sha: str) -> dict[str, Any]:
    """Copy diagnostics first, then validate and aggregate backend evidence."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_allure_diagnostics(artifacts, output_dir)
    entries = _read_artifact_manifests(artifacts, "backend-execution.json")
    summary = validate_backend_manifests([entry[1] for entry in entries], sha=sha)
    (output_dir / "mode.txt").write_text(summary["mode"] + "\n", encoding="utf-8")
    coverage_files: list[Path] = []
    for folder, manifest in entries:
        if manifest["assigned"]:
            coverage_path = folder / ".coverage"
            _validate_coverage_db(coverage_path)
            coverage_files.append(coverage_path)
    _merge_coverage(coverage_files, output_dir, summary["coverage_version"])
    _write_json(output_dir / "backend-merge.json", summary)
    return summary


def backend_version(artifacts: Path, output_dir: Path, sha: str) -> str:
    """Copy diagnostics and validate the common coverage version pre-install."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_allure_diagnostics(artifacts, output_dir)
    entries = _read_artifact_manifests(artifacts, "backend-execution.json")
    summary = validate_backend_manifests([manifest for _, manifest in entries], sha=sha)
    version = summary["coverage_version"]
    if not isinstance(version, str) or not re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
        raise ValueError("coverage tool version is missing or invalid")
    (output_dir / "coverage-version.txt").write_text(version + "\n", encoding="utf-8")
    print(version)
    return version


def _scope_from_file(path: Path) -> list[str]:
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for value in values:
        validate_repo_path(value)
    _unique(values, "mutation scope path")
    return sorted(values)


def split_mutation_scope(scope: list[str]) -> list[list[str]]:
    _unique(scope, "mutation scope path")
    for path in scope:
        validate_repo_path(path)
    tree = "app/services/tree_service.py"
    return [[tree] if tree in scope else [], [path for path in sorted(scope) if path != tree]]


def _stats_valid(stats: dict[str, Any]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key in MUTATION_COUNTERS:
        value = stats.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"invalid mutation counter: {key}")
        normalized[key] = value
    if normalized["check_was_interrupted_by_user"] != 0:
        raise ValueError("mutation campaign was interrupted")
    statuses = sum(normalized[k] for k in MUTATION_COUNTERS if k not in {"total", "check_was_interrupted_by_user"})
    if normalized["total"] != statuses:
        raise ValueError("mutation counter totals do not agree")
    return normalized


def _expected_scope_parts(scope: list[str]) -> list[list[str]]:
    return split_mutation_scope(scope)


def merge_mutation_manifests(
    manifests: list[dict[str, Any]], *, sha: str, expected_scope: list[str] | None = None
) -> dict[str, Any]:
    if len(manifests) != 2:
        raise ValueError("mutation aggregation requires exactly two manifests")
    by_index: dict[int, dict[str, Any]] = {}
    for manifest in manifests:
        index = manifest.get("index")
        if index not in (0, 1) or index in by_index:
            raise ValueError("mutation manifest index is missing or duplicated")
        by_index[index] = manifest
    if set(by_index) != {0, 1}:
        raise ValueError("mutation shard index is missing")
    first = by_index[0]
    requested = first.get("requested_scope")
    if not isinstance(requested, list) or _unique(requested, "requested mutation path") is None:
        raise ValueError("mutation requested scope is corrupt")
    requested = sorted(requested)
    if expected_scope is not None and requested != sorted(expected_scope):
        raise ValueError("mutation requested scope differs from independently expected scope")
    expected_parts = _expected_scope_parts(requested)
    identities: list[str] = []
    assigned: list[str] = []
    totals = {key: 0 for key in MUTATION_COUNTERS}
    for index in (0, 1):
        part = by_index[index]
        if part.get("sha") != sha or part.get("count") != 2:
            raise ValueError("mutation source SHA or shard count does not match")
        if part.get("requested_scope") != first.get("requested_scope"):
            raise ValueError("mutation requested scopes differ")
        if part.get("status") != "success":
            raise ValueError("mutation campaign failed or was interrupted")
        files, ids = part.get("assigned"), part.get("identities")
        file_identities = part.get("file_identities")
        if files != expected_parts[index] or not isinstance(ids, list) or not isinstance(file_identities, dict):
            raise ValueError("mutation shard scope is missing or incorrectly assigned")
        if sorted(file_identities) != sorted(files) or any(not isinstance(value, list) for value in file_identities.values()):
            raise ValueError("per-file mutation metadata is missing or corrupt")
        flattened = [identity for values in file_identities.values() for identity in values]
        if sorted(flattened) != sorted(ids):
            raise ValueError("per-file mutant identities differ from aggregate identities")
        for file_path, file_ids in file_identities.items():
            module = file_path.removesuffix(".py").replace("/", ".") + "."
            if any(not isinstance(identity, str) or not identity.startswith(module) for identity in file_ids):
                raise ValueError("mutant identity does not belong to its assigned file")
        _unique(ids, "mutant identity")
        for mutant_id in ids:
            if not isinstance(mutant_id, str) or not mutant_id or "\n" in mutant_id:
                raise ValueError("mutation identity is corrupt")
            identities.append(mutant_id)
        assigned.extend(files)
        stats = part.get("stats")
        if not isinstance(stats, dict):
            raise ValueError("mutation stats are missing or corrupt")
        clean = _stats_valid(stats)
        if clean["total"] != len(ids):
            raise ValueError("mutation identities do not agree with exported counters")
        identity_counters = part.get("identity_counters")
        if not isinstance(identity_counters, dict):
            raise ValueError("mutation identity counters are missing or corrupt")
        for key in ("killed", "survived", "no_tests", "skipped", "suspicious", "timeout", "segfault"):
            if identity_counters.get(key) != clean[key]:
                raise ValueError("mutation identities disagree with exported counters")
        for key, value in clean.items():
            totals[key] += value
    _unique(assigned, "assigned mutation path")
    if sorted(assigned) != requested:
        raise ValueError("mutation shard scopes do not cover requested scope")
    _unique(identities, "mutant identity across shards")
    totals["total"] = sum(totals[k] for k in MUTATION_COUNTERS if k not in {"total", "check_was_interrupted_by_user"})
    return {"sha": sha, "requested_scope": requested, "assigned": sorted(assigned), "identities": sorted(identities), "stats": totals}


def _meta_identities(mutants_dir: Path, assigned: list[str]) -> tuple[list[str], dict[str, int], dict[str, list[str]]]:
    identities: list[str] = []
    statuses: Counter[str] = Counter()
    by_file: dict[str, list[str]] = {}
    for source in assigned:
        validate_repo_path(source)
        meta = mutants_dir / (source + ".meta")
        # mutmut stores paths relative to backend; when given mutants/ use its
        # mirrored app tree, while accepting a root containing the same paths.
        if not meta.is_file():
            meta = mutants_dir / source.removeprefix("app/") .replace("/", ".")
            meta = Path(str(meta) + ".meta")
        payload = _read_json(meta)
        exit_codes = payload.get("exit_code_by_key")
        if not isinstance(exit_codes, dict):
            raise ValueError("mutmut per-file metadata lacks exit_code_by_key")
        by_file[source] = []
        for identity, code in exit_codes.items():
            if not isinstance(identity, str) or isinstance(code, bool) or not isinstance(code, int):
                raise ValueError("mutmut per-file identity or exit code is corrupt")
            identities.append(identity)
            by_file[source].append(identity)
            # mutmut 3.8.0 stats.status_by_exit_code, restricted to its CI/CD
            # export categories. Unknown integer statuses are suspicious there.
            if code == 2:
                raise ValueError("mutation campaign was interrupted")
            if code == 37:
                # The existing CI export omits caught_by_type_check, while
                # including it in total. Type-check prefilters remain out of scope.
                raise ValueError("mutation type-check status is absent from exported counters")
            category = {
                1: "killed", 3: "killed", 0: "survived", 5: "no_tests", 33: "no_tests",
                34: "skipped", 35: "suspicious", 36: "timeout", -24: "timeout",
                24: "timeout", 152: "timeout", 255: "timeout", -11: "segfault", -9: "segfault",
            }.get(code, "suspicious")
            module = source.removesuffix(".py").replace("/", ".") + "."
            if not identity.startswith(module):
                raise ValueError("mutmut identity does not belong to its assigned source file")
            statuses[category] += 1
    _unique(identities, "mutant identity")
    return identities, dict(statuses), by_file


def _cmd_mutation_select(args: argparse.Namespace) -> None:
    _check_shard(args.index, args.count)
    scope = _scope_from_file(args.scope)
    parts = split_mutation_scope(scope)
    _write_json(args.output, {"sha": args.revision, "index": args.index, "count": args.count, "requested_scope": scope, "assigned": parts[args.index]})


def _cmd_mutation_record(args: argparse.Namespace) -> None:
    assignment = _read_json(args.assignment)
    assigned = assignment.get("assigned")
    requested = assignment.get("requested_scope")
    index, count, sha = assignment.get("index"), assignment.get("count"), assignment.get("sha")
    _check_shard(index, count)
    if not isinstance(assigned, list) or not isinstance(requested, list):
        raise ValueError("mutation assignment is corrupt")
    _unique(assigned, "assigned mutation path")
    stats = _read_json(args.stats)
    identities, identity_statuses, file_identities = _meta_identities(args.mutants_dir, assigned)
    clean = _stats_valid(stats)
    if clean["total"] != len(identities):
        raise ValueError("mutmut metadata identity count differs from exported stats")
    for key in ("killed", "survived", "no_tests", "skipped", "suspicious", "timeout", "segfault"):
        if clean[key] != identity_statuses.get(key, 0):
            raise ValueError("mutmut metadata identities disagree with exported counters")
    manifest = {
        **assignment,
        "status": "success",
        "identities": identities,
        "file_identities": file_identities,
        "identity_counters": {key: identity_statuses.get(key, 0) for key in ("killed", "survived", "no_tests", "skipped", "suspicious", "timeout", "segfault")},
        "stats": clean,
        "summary_file": args.summary.name if args.summary and args.summary.is_file() else None,
        "survivors_file": args.survivors.name if args.survivors and args.survivors.is_file() else None,
        "raw_state_file": args.raw_state.name if args.raw_state and args.raw_state.exists() else None,
    }
    _write_json(args.output, manifest)


def _cmd_mutation_merge(args: argparse.Namespace) -> None:
    expected_scope = _scope_from_file(args.expected_scope)
    entries = _read_artifact_manifests(args.artifacts, "mutation-manifest.json")
    result = merge_mutation_manifests([manifest for _, manifest in entries], sha=args.sha, expected_scope=expected_scope)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "mutation-stats.json", {key: result["stats"][key] for key in MUTATION_COUNTERS})
    _write_json(args.output_dir / "mutation-merge.json", result)
    for filename, dest_name in (("mutation-summary.txt", "mutation-summary.txt"), ("mutation-survivors.txt", "mutation-survivors.txt")):
        chunks = []
        for folder, manifest in sorted(entries, key=lambda entry: entry[1]["index"]):
            source = folder / filename
            if source.exists():
                chunks.append(source.read_text(encoding="utf-8"))
        (args.output_dir / dest_name).write_text("\n".join(chunks), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("backend-record", help="record one local pytest/JUnit/coverage result")
    for flag in ("assignment", "junit", "coverage", "output", "sha", "index", "count", "mode", "exit-code"):
        record.add_argument(f"--{flag}", required=True)
    record.add_argument("--allure", type=Path)
    record.set_defaults(func=_cmd_backend_record)
    merge = commands.add_parser("backend-merge", help="validate and combine two backend shard artifacts")
    merge.add_argument("--artifacts", type=Path, required=True)
    merge.add_argument("--output-dir", type=Path, required=True)
    merge.add_argument("--sha", required=True)
    merge.set_defaults(func=lambda args: merge_backend(args.artifacts, args.output_dir, args.sha))
    version = commands.add_parser("backend-version", help="copy diagnostics and validate coverage version")
    version.add_argument("--artifacts", type=Path, required=True)
    version.add_argument("--output-dir", type=Path, required=True)
    version.add_argument("--sha", required=True)
    version.set_defaults(func=lambda args: backend_version(args.artifacts, args.output_dir, args.sha))
    select = commands.add_parser("mutation-select", help="partition a newline-separated mutation scope")
    select.add_argument("--scope", type=Path, required=True)
    select.add_argument("--revision", required=True)
    select.add_argument("--index", type=int, required=True)
    select.add_argument("--count", type=int, default=2)
    select.add_argument("--output", type=Path, required=True)
    select.set_defaults(func=_cmd_mutation_select)
    record_mut = commands.add_parser("mutation-record", help="record one mutmut shard")
    record_mut.add_argument("--assignment", type=Path, required=True)
    record_mut.add_argument("--mutants-dir", "--meta", dest="mutants_dir", type=Path, required=True)
    record_mut.add_argument("--stats", type=Path, required=True)
    record_mut.add_argument("--summary", type=Path)
    record_mut.add_argument("--survivors", type=Path)
    record_mut.add_argument("--raw-state", type=Path)
    record_mut.add_argument("--output", type=Path, required=True)
    record_mut.set_defaults(func=_cmd_mutation_record)
    merge_mut = commands.add_parser("mutation-merge", help="validate both mutation shards and sum raw counters")
    merge_mut.add_argument("--artifacts", type=Path, required=True)
    merge_mut.add_argument("--expected-scope", type=Path, required=True)
    merge_mut.add_argument("--sha", required=True)
    merge_mut.add_argument("--output-dir", type=Path, required=True)
    merge_mut.set_defaults(func=_cmd_mutation_merge)
    return parser


def _cmd_backend_record(args: argparse.Namespace) -> None:
    _check_shard(int(args.index), int(args.count))
    assignment = _read_json(Path(args.assignment))
    if assignment.get("sha") != args.sha or assignment.get("index") != int(args.index) or assignment.get("count") != 2 or assignment.get("mode") != args.mode:
        raise ValueError("backend assignment does not match this candidate shard")
    assigned = assignment.get("assigned")
    collection = assignment.get("collection")
    if not isinstance(assigned, list) or not isinstance(collection, list):
        raise ValueError("backend assignment is corrupt")
    _unique(assigned, "assigned pytest node id")
    junit_path = Path(args.junit)
    if junit_path.exists():
        counts = junit_counts(junit_path)
    elif not assigned:
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    else:
        raise ValueError("JUnit report is missing for a nonempty backend assignment")
    if counts["tests"] != len(assigned):
        raise ValueError("JUnit case count does not match assigned execution")
    status = (
        "success"
        if int(args.exit_code) == 0
        and not counts["failures"]
        and not counts["errors"]
        and (not assigned or Path(args.coverage).exists())
        else "failed"
    )
    payload: dict[str, Any] = {
        "sha": args.sha,
        "index": int(args.index),
        "count": 2,
        "mode": args.mode,
        "collection": collection,
        "groups": assignment.get("groups", {}),
        "assigned": assigned,
        "junit": counts,
        "status": status,
        "coverage_version": None,
        "coverage_paths": [],
    }
    if assigned and Path(args.coverage).exists():
        paths = _validate_coverage_db(Path(args.coverage))
        payload["coverage_file"] = ".coverage"
        payload["coverage_paths"] = paths
        try:
            payload["coverage_version"] = importlib.metadata.version("coverage")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError("coverage tool version is unavailable") from exc
    elif not assigned and Path(args.coverage).exists():
        raise ValueError("empty backend assignment must not produce coverage data")
    else:
        try:
            payload["coverage_version"] = importlib.metadata.version("coverage")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError("coverage tool version is unavailable") from exc
    _write_json(Path(args.output), payload)
    if status != "success":
        raise ValueError("pytest or JUnit reports failed backend execution")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"ci_shards: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
