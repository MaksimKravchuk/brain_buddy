#!/usr/bin/env python3
"""Name the stack lanes a change under scripts/ or to the Makefile can affect.

The `changes` job used to treat every file under scripts/ and the Makefile as a
shared surface that exercises every stack. Most of those files are delivery
and spec tooling that only the always-running jobs (workflow-lint, spec-kit,
e2e, the mutation gate, the Allure report) execute, so a pull request that
edited one queued macOS and Windows runners for a change none of them could
observe.

A stack lane can only be affected by a file it reads. This script finds the
readers of each changed file by searching, at the candidate revision, for the
places that name it:

* the lane's own jobs in the workflow (``scripts/validate_coverage_floor.py``
  in the backend job);
* the lane's source tree (the CLI tests load ``scripts/build_cli_release.py``,
  the Rust core runs ``scripts/validate_allure_taxonomy.py``);
* another file under scripts/ that names it, whose own readers are then found
  the same way.

A file is named by its path, its file name, its module name for Python, or a
``scripts/`` path to one of its directories (fixture directories are read as a
whole). Every search is textual and errs toward finding more readers, never
fewer. Anything the `changes` job itself executes decides the filter, so a
change to it exercises everything, as does any search that fails.

Usage: git diff --name-only BASE HEAD | classify_changed_scripts.py --workflow
.github/workflows/ci.yml. Prints ``all`` or the affected lanes, one per line.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

ALL = "all"

#: Workflow job -> the stack output that gates it.
JOB_LANES = {
    "backend": "backend",
    "backend-results": "backend",
    "frontend": "frontend",
    "ios-kit": "ios_kit",
    "ios-app": "ios",
    "ios-tests": "ios",
    "macos-app": "macos",
    "rust": "rust",
    "cli-native": "cli",
    "cli-artifacts": "cli",
}

#: Stack output -> the source trees its lane builds and tests.
LANE_TREES = {
    "backend": ("backend",),
    "frontend": ("frontend",),
    "ios": ("ios",),
    "ios_kit": ("ios/BrainBuddyKit", "ios/scripts"),
    "macos": ("macos", "ios/BrainBuddyKit", "ios/scripts"),
    "rust": ("rust",),
    "cli": ("cli",),
}

#: The job whose own inputs decide the filter: changing one exercises all.
DECIDER_JOB = "changes"

MAKEFILE = "Makefile"


class Unclassifiable(Exception):
    """A search could not be completed; the caller exercises everything."""


class Corpus(NamedTuple):
    """The candidate revision's text, gathered once."""

    #: Job id -> its block of the workflow.
    jobs: dict[str, str]
    #: Lane -> the concatenated text of every file in its source trees.
    lane_text: dict[str, str]
    #: scripts/ files and the Makefile -> their text.
    tooling: dict[str, str]


def workflow_jobs(text: str) -> dict[str, str]:
    """Each job's YAML block in the workflow, by job id."""

    jobs: dict[str, str] = {}
    body = re.split(r"^jobs:\n", text, maxsplit=1, flags=re.MULTILINE)
    if len(body) != 2:
        raise Unclassifiable("workflow has no jobs: block")
    starts = list(
        re.finditer(r"^  ([A-Za-z0-9_-]+):[ \t]*$", body[1], flags=re.MULTILINE)
    )
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(body[1])
        jobs[match.group(1)] = body[1][match.start() : end]
    if DECIDER_JOB not in jobs:
        raise Unclassifiable(f"workflow has no {DECIDER_JOB} job")
    return jobs


def search_terms(path: str) -> list[str]:
    """The strings that, found in a file, mean it may read ``path``."""

    if path == MAKEFILE:
        return [MAKEFILE]
    pure = PurePosixPath(path)
    terms = {path, pure.name}
    if pure.suffix == ".py":
        # The import name: a module beside the tooling's own entry points, or
        # dotted from a package below it (scripts/rehearsal/run.py is
        # rehearsal.run, never a bare "run").
        package = pure.parts[1:-1]
        terms.add(".".join((*package, pure.stem)))
    if pure.parts[0] == "scripts":
        # scripts/fixtures/x/case.json is read through "scripts/fixtures/x".
        for depth in range(2, len(pure.parts)):
            terms.add("/".join(pure.parts[:depth]))
    return sorted(term for term in terms if term)


#: A shell line that runs make: the only way a job reads the Makefile.
_RUNS_MAKE = re.compile(
    r"(?:^[ \t]*(?:-[ \t]+)?(?:run:[ \t]*)?|(?:&&|\|\||;)[ \t]*)make\b",
    re.MULTILINE,
)


def _mentions(text: str, terms: Iterable[str]) -> bool:
    terms = list(terms)
    if terms == [MAKEFILE]:
        return bool(_RUNS_MAKE.search(text))
    return any(term in text for term in terms)


def lanes_for(path: str, corpus: Corpus) -> set[str] | None:
    """Lanes that may read ``path``, directly or through tooling that names
    it; None means every lane."""

    lanes: set[str] = set()
    pending = [path]
    seen = {path}
    while pending:
        current = pending.pop()
        terms = search_terms(current)
        if _mentions(corpus.jobs[DECIDER_JOB], terms):
            return None
        lanes.update(
            lane
            for job, lane in JOB_LANES.items()
            if _mentions(corpus.jobs.get(job, ""), terms)
        )
        if current == MAKEFILE:
            # Lane source trees and tooling that merely name a Makefile (the
            # Mac app has its own) do not run this one.
            continue
        lanes.update(
            lane for lane, text in corpus.lane_text.items() if _mentions(text, terms)
        )
        for referrer, text in corpus.tooling.items():
            if referrer not in seen and _mentions(text, terms):
                seen.add(referrer)
                pending.append(referrer)
    return lanes


def classify(paths: Iterable[str], corpus: Corpus) -> set[str] | None:
    """Union of lanes over the changed scripts/ and Makefile paths."""

    lanes: set[str] = set()
    for path in paths:
        if not (path.startswith("scripts/") or path == MAKEFILE):
            continue
        found = lanes_for(path, corpus)
        if found is None:
            return None
        lanes |= found
    return lanes


def _read(repo: Path, path: str) -> str:
    try:
        return (repo / path).read_text(encoding="utf-8", errors="replace")
    # Separate clauses: the changes job runs the runner's own python3, which
    # predates unparenthesised multi-type except.
    except IsADirectoryError:
        return ""  # A submodule.
    except FileNotFoundError:
        return ""  # A path git lists but the tree lacks.


def load_corpus(repo: Path, workflow: Path) -> Corpus:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise Unclassifiable(result.stderr.decode(errors="replace").strip())
    files = [name for name in result.stdout.decode().split("\0") if name]
    lane_text = {
        lane: "\n".join(
            _read(repo, name)
            for name in files
            if any(name.startswith(f"{tree}/") for tree in trees)
        )
        for lane, trees in LANE_TREES.items()
    }
    tooling = {
        name: _read(repo, name)
        for name in files
        if name.startswith("scripts/") or name == MAKEFILE
    }
    return Corpus(
        workflow_jobs(workflow.read_text(encoding="utf-8")), lane_text, tooling
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    paths = [line.strip() for line in sys.stdin if line.strip()]
    try:
        lanes = classify(paths, load_corpus(args.repo, args.workflow))
    except (OSError, Unclassifiable) as error:
        print(
            f"cannot classify scripts/ changes ({error}); exercising every stack",
            file=sys.stderr,
        )
        lanes = None
    if lanes is None:
        print(ALL)
    else:
        print("\n".join(sorted(lanes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
