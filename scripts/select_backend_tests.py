#!/usr/bin/env python3
"""Pick the backend tests a pull request can affect, from measured coverage.

Two commands:

``build-map``
    Reads a ``.coverage`` file recorded with ``--cov-context=test`` (a full run
    on the landing path) and writes a JSON map: for every measured ``app/``
    file, the test files whose tests executed at least one of its lines, plus
    the functions whose bodies also ran at import time.

``select``
    Reads that map and the diff between the map's commit and the candidate,
    and prints either ``ALL`` or the test files to run, one per line.

Static imports cannot answer this question here: most suites go through the
FastAPI app and the container, which import nearly all of ``app/``. Measured
coverage can, as long as every way it could be wrong falls back to ``ALL``.
The selection is narrowed for edits confined to function bodies of
``app/*.py`` files that the map has measured, because that is the one kind of
change a test's recorded line hits can vouch for:

* module-level code (constants, class attributes, ``__init__`` re-exports)
  runs at import, outside any test context, so no test is recorded against it
  (a function's own decorators and signature, and plain imports, are the
  exceptions; see ``_function_bodies`` and ``select``);
* a function body that also ran at import time has the same problem;
* a memoized function (``lru_cache``, ``cache``, ``cached_property``) or
  one that fills a ``global`` runs its body for the first caller only, so
  later tests that depend on its result are not recorded against it;
* a file the map never measured has no tests on record at all;
* anything outside ``app/`` and ``tests/test_*.py`` (fixtures, conftest,
  configuration, packaging) can change every test.

A change under ``rust/`` is narrowed the same way through the one door the
backend has into it: the tests on record for the app files that import the
``bb_core`` extension, plus the test files that import it directly.

Test files the map has never seen are always selected, so a stale map can only
ever run more, not less.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

MAP_VERSION = 2
ALL = "ALL"
APP_PREFIX = "backend/app/"
TESTS_PREFIX = "backend/tests/"
# The PyO3 extension the backend wheel builds from rust/bindings/python.
BRIDGE_MODULE = "bb_core"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


def _relative_to_backend(path: str, backend_root: Path) -> str | None:
    try:
        return Path(path).resolve().relative_to(backend_root.resolve()).as_posix()
    except ValueError:
        return None


def build_map(coverage_file: Path, backend_root: Path, source_sha: str) -> dict:
    from coverage import CoverageData  # Installed with pytest-cov.

    data = CoverageData(basename=str(coverage_file))
    data.read()
    if data.measured_contexts() <= {""}:
        raise ValueError(
            f"{coverage_file} holds no test contexts; run with --cov-context=test"
        )

    files: dict[str, list[str]] = {}
    import_executed: dict[str, list[str]] = {}
    tests: set[str] = set()
    for measured in sorted(data.measured_files()):
        relative = _relative_to_backend(measured, backend_root)
        if relative is None or not relative.startswith("app/"):
            continue
        by_line = data.contexts_by_lineno(measured)
        owners: set[str] = set()
        import_lines: set[int] = set()
        for line, contexts in by_line.items():
            for context in contexts:
                if not context:
                    import_lines.add(line)
                    continue
                test_file = context.split("::", 1)[0]
                owners.add(test_file)
        tests |= owners
        files[relative] = sorted(owners)
        source = backend_root / relative
        if import_lines and source.is_file():
            owners = _function_bodies(source.read_text(encoding="utf-8"))
            functions = {owners[line] for line in import_lines if line in owners}
            if functions:
                import_executed[relative] = sorted(functions)

    return {
        "version": MAP_VERSION,
        "source_sha": source_sha,
        "files": files,
        "import_executed": import_executed,
        # Every test file present, not only those that reached app/: one that
        # touched no app code at this commit can only start to by changing.
        "tests": sorted(
            tests
            | {
                path.relative_to(backend_root).as_posix()
                for path in (backend_root / "tests").rglob("test_*.py")
            }
        ),
    }


def _function_bodies(source: str, headers: bool = False) -> dict[int, str]:
    """Each line inside a function body, mapped to its innermost function's
    dotted name (``Class.method``, ``outer.inner``).

    With ``headers``, a function's decorators and signature belong to it too.
    They run at import, but every test they can affect calls the function and
    so ran its body when the map was recorded; that is what makes them safe to
    select on. Without it the lines are the body alone, which is what the map
    needs to tell a body that ran at import from a ``def`` that merely did.
    """

    owners: dict[int, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                if child.body:
                    start = child.body[0].lineno
                    if headers:
                        start = min(
                            [child.lineno, *(d.lineno for d in child.decorator_list)]
                        )
                    end = child.body[-1].end_lineno or child.body[-1].lineno
                    for line in range(start, end + 1):
                        owners[line] = name  # Inner functions overwrite below.
                visit(child, f"{name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(ast.parse(source), "")
    return owners


def _function_body_lines(source: str) -> set[int]:
    return set(_function_bodies(source))


def _import_lines(tree: ast.Module) -> set[int]:
    lines: set[int] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


MEMOIZERS = frozenset({"lru_cache", "cache", "cached_property"})


def _memoizes(tree: ast.AST) -> bool:
    """Whether a module memoizes anything a single test would be recorded for."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                target = (
                    decorator.func if isinstance(decorator, ast.Call) else decorator
                )
                name = (
                    target.attr
                    if isinstance(target, ast.Attribute)
                    else getattr(target, "id", "")
                )
                if name in MEMOIZERS:
                    return True
    return False


def _changed_lines(diff: str) -> set[int]:
    lines: set[int] = set()
    for row in diff.splitlines():
        match = HUNK.match(row)
        if not match:
            continue
        start = int(match.group("start"))
        count = int(match.group("count") or "1")
        if count == 0:
            # A pure deletion: mark the line it was removed in front of.
            lines.add(max(start, 1))
        else:
            lines.update(range(start, start + count))
    return lines


def select(
    test_map: dict,
    changes: list[tuple[str, str]],
    diff_for: Callable[[str], str],
    head_source_for: Callable[[str], str],
    head_tests: set[str],
    bridge_importers: set[str] = frozenset(),
) -> tuple[list[str] | None, list[str]]:
    """Return (tests or None for ALL, reasons)."""

    reasons: list[str] = []
    selected: set[str] = set()
    files = test_map["files"]
    import_executed = {
        path: set(functions) for path, functions in test_map["import_executed"].items()
    }
    bridge_users: set[str] = set()

    for status, path in changes:
        if not path.startswith(("backend/", "rust/")):
            continue
        if path.startswith("rust/"):
            # The backend reaches the Rust core only through the extension
            # module, so a Rust change matters to the files that import it.
            bridge_users.add(path)
            continue
        if status not in {"M", "A"}:
            return None, [f"{path}: status {status} (deleted, renamed or copied)"]

        if path.startswith(TESTS_PREFIX):
            name = Path(path).name
            if name.startswith("test_") and name.endswith(".py"):
                selected.add(path.removeprefix("backend/"))
                reasons.append(f"{path}: changed test file")
                continue
            return None, [f"{path}: shared test support can change every test"]

        if not path.startswith(APP_PREFIX) or not path.endswith(".py"):
            return None, [f"{path}: outside app/*.py and tests/test_*.py"]

        relative = path.removeprefix("backend/")
        if status == "A" or relative not in files:
            return None, [f"{path}: no measured tests on record"]
        source = head_source_for(path)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None, [f"{path}: does not parse"]
        if _memoizes(tree):
            return None, [
                f"{path}: memoizes results, so only the first caller is recorded"
            ]
        owners = _function_bodies(source, headers=True)
        changed = _changed_lines(diff_for(path))
        # Import statements bind names this module's own code reads, and its
        # code is either recorded (function bodies) or runs in every selected
        # test's import (module level). A package __init__ is the exception:
        # it imports in order to re-export to other modules.
        if Path(path).name != "__init__.py":
            changed -= _import_lines(tree)
        outside = sorted(changed - set(owners))
        if outside:
            return None, [f"{path}: module-level lines changed ({outside[:5]})"]
        at_import = {owners[line] for line in changed} & import_executed.get(
            relative, set()
        )
        if at_import:
            return None, [f"{path}: {min(at_import)} also runs at import time"]
        if not files[relative]:
            return None, [f"{path}: no test executed it"]
        selected.update(files[relative])
        reasons.append(f"{path}: {len(files[relative])} test file(s) on record")

    if bridge_users:
        importers = sorted(path for path in bridge_importers if path.startswith("app/"))
        if not importers:
            return None, [f"{min(bridge_users)}: no app file imports the Rust bridge"]
        for importer in importers:
            source = head_source_for(f"backend/{importer}")
            # Import-time calls through the bridge do not disqualify it: they
            # run in every process, the selected tests' included, and a test
            # that consumes the bridge afterwards calls back into this file.
            if importer not in files or _memoizes(ast.parse(source)):
                return None, [
                    f"{min(bridge_users)}: {importer} cannot vouch for its callers"
                ]
            selected.update(files[importer])
        selected.update(path for path in bridge_importers if path.startswith("tests/"))
        reasons.append(
            f"{len(bridge_users)} Rust file(s): tests on record for {', '.join(importers)}"
        )

    unknown = sorted(head_tests - set(test_map["tests"]))
    if unknown:
        selected.update(unknown)
        reasons.append(f"{len(unknown)} test file(s) the map has not measured")
    # Only test files that still exist can be run.
    selected &= head_tests
    if not selected:
        return None, reasons + ["nothing selected; running everything"]
    return sorted(selected), reasons


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _cmd_build_map(args: argparse.Namespace) -> int:
    result = build_map(args.coverage, args.backend_root, args.source_sha)
    args.output.write_text(
        json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"mapped {len(result['files'])} app files to {len(result['tests'])} test files "
        f"({len(result['import_executed'])} run at import) at {args.source_sha}"
    )
    return 0


def _cmd_select(args: argparse.Namespace) -> int:
    def everything(reason: str) -> int:
        print(f"running everything: {reason}", file=sys.stderr)
        print(ALL)
        return 0

    try:
        test_map = json.loads(args.map.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return everything(f"no readable map ({error})")
    if test_map.get("version") != MAP_VERSION:
        return everything(f"map version {test_map.get('version')!r}")

    repo = args.repo
    base = test_map["source_sha"]
    try:
        raw = _git("diff", "--no-renames", "--name-status", base, "HEAD", cwd=repo)
    except subprocess.CalledProcessError as error:
        return everything(f"cannot diff {base}..HEAD ({error.stderr.strip()})")
    changes = []
    for row in raw.splitlines():
        status, _, path = row.partition("\t")
        changes.append((status[:1], path))

    head_tests = {
        path.relative_to(repo / "backend").as_posix()
        for path in (repo / "backend" / "tests").rglob("test_*.py")
    }
    try:
        grep = _git(
            "grep",
            "-lE",
            rf"^[[:space:]]*(import|from)[[:space:]]+{BRIDGE_MODULE}([^[:alnum:]_]|$)",
            "HEAD",
            "--",
            "backend",
            cwd=repo,
        )
    except subprocess.CalledProcessError:
        grep = ""  # No match.
    bridge_importers = {
        line.split(":", 1)[1].removeprefix("backend/")
        for line in grep.splitlines()
        if ":" in line
    }
    tests, reasons = select(
        test_map,
        changes,
        bridge_importers=bridge_importers,
        diff_for=lambda path: _git("diff", "-U0", base, "HEAD", "--", path, cwd=repo),
        head_source_for=lambda path: (repo / path).read_text(encoding="utf-8"),
        head_tests=head_tests,
    )
    for reason in reasons:
        print(reason, file=sys.stderr)
    if tests is None:
        print(ALL)
        return 0
    print(f"selected {len(tests)} of {len(head_tests)} test files", file=sys.stderr)
    print("\n".join(tests))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser(
        "build-map", help="build the map from a context-recorded .coverage"
    )
    build.add_argument("--coverage", type=Path, required=True)
    build.add_argument("--backend-root", type=Path, required=True)
    build.add_argument("--source-sha", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(func=_cmd_build_map)

    pick = sub.add_parser("select", help="print ALL or the test files to run")
    pick.add_argument("--map", type=Path, required=True)
    pick.add_argument("--repo", type=Path, default=Path("."))
    pick.set_defaults(func=_cmd_select)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
