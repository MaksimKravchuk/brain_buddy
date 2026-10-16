#!/usr/bin/env python3
"""Which releases a change reaches: the component -> release graph.

One table for every artifact main publishes, so "what does this commit
release?" has one answer:

  ios-testflight  the iOS app uploaded by .github/workflows/ios.yml
  fly-backend     the backend image deployed by deploy-fly-production.yml
  fly-frontend    the frontend image deployed by the same workflow

Each release lists the paths its artifact is built from. The shared Rust core
is not listed by hand: a release names the Rust crate it links (`bb-swift`
for the iOS app, `bb-python` for the backend wheel) and the crates that crate
depends on are read from the Cargo manifests, so a new dependency edge in
rust/ moves the release boundary with it. Crate tests, benches, examples and
markdown never reach an artifact and are left out.

The two consumers have different safety directions, kept from before this
graph existed:

* TestFlight is an allow-list. Only paths in its closure upload a build;
  anything else (backend, macOS, docs, an unknown file) does not.
* Fly is fail-open. A path no rule knows deploys BOTH apps, as does an empty
  listing; only paths known to be inert for production stay quiet.

Standard library only, and no git or network access: callers pass the changed
paths (NUL-separated on stdin for `fly`, the same contract the deploy
workflow had with scripts/classify_deploy_paths.sh), so tests exercise the
exact production behaviour.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUST_DIR = "rust"
# Workspace-wide inputs: every crate is built with this lock and toolchain.
RUST_SHARED = ("rust/Cargo.toml", "rust/Cargo.lock", "rust/rust-toolchain.toml")
# Inside a crate, these never end up in a library another crate links.
CRATE_IGNORED_DIRS = ("tests/", "benches/", "examples/")
IGNORED_SUFFIXES = (".md",)


@dataclass(frozen=True)
class Release:
    name: str
    # Prefixes end with "/"; anything else is an exact path or an fnmatch glob.
    paths: tuple[str, ...]
    # The crate the artifact links; its whole dependency closure is included.
    rust_root: str | None = None


RELEASES: tuple[Release, ...] = (
    Release(
        "ios-testflight",
        (
            "ios/BrainBuddy/",
            "ios/BrainBuddyWidgets/",
            "ios/Shared/",
            "ios/BrainBuddyKit/Sources/",
            "ios/BrainBuddyKit/Package.swift",
            "ios/BrainBuddyKit/Package.resolved",
            "ios/project.yml",
            # Builds the XCFramework the app links (spec 026).
            "ios/scripts/build-rust-bridge.sh",
        ),
        rust_root="bb-swift",
    ),
    Release(
        "fly-backend",
        ("backend/", "fly.backend.toml"),
        # backend/pyproject.toml builds the wheel from rust/bindings/python.
        rust_root="bb-python",
    ),
    Release(
        "fly-frontend",
        ("frontend/", "fly.frontend.toml", "deploy/nginx/"),
    ),
)

FLY_RELEASES = ("fly-backend", "fly-frontend")
# Shared by both Fly images or by Fly itself: deploy both.
FLY_SHARED = (".dockerignore", ".env", "Dockerfile*", "docker-compose*", "compose.y*ml", "fly.*")
# Never reach a Fly image. ios/, macos/ and cli/ ship through their own
# channels; contracts/ is outside both Docker build contexts (backend/Dockerfile
# copies backend/ and rust/, frontend/Dockerfile copies frontend/ and
# deploy/nginx/); a rust/ path outside the backend's closure is matched
# separately, from the Cargo graph.
FLY_INERT = (
    ".github/*",
    ".specify/*",
    ".claude/*",
    ".design-sync/*",
    "docs/*",
    "specs/*",
    "ios/*",
    "macos/*",
    "cli/*",
    "contracts/*",
    "scripts/*",
    "*.md",
    "Makefile",
    ".gitignore",
    "LICENSE",
    ".env.example",
)


def _manifest(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _dependency_tables(manifest: dict) -> Iterable[dict]:
    for key in ("dependencies", "build-dependencies"):
        yield manifest.get(key, {})
    for target in manifest.get("target", {}).values():
        for key in ("dependencies", "build-dependencies"):
            yield target.get(key, {})


def rust_crates(root: Path = REPO_ROOT) -> dict[str, tuple[str, set[str]]]:
    """Every workspace crate: name -> (repo-relative dir, local dependency names)."""
    workspace = _manifest(root / RUST_DIR / "Cargo.toml")
    shared = workspace.get("workspace", {}).get("dependencies", {})
    crates: dict[str, tuple[str, set[str]]] = {}
    for member in workspace["workspace"]["members"]:
        crate_dir = root / RUST_DIR / member
        manifest = _manifest(crate_dir / "Cargo.toml")
        local: set[str] = set()
        for table in _dependency_tables(manifest):
            for dep, spec in table.items():
                if not isinstance(spec, dict):
                    continue
                if "path" in spec or (spec.get("workspace") and "path" in shared.get(dep, {})):
                    local.add(spec.get("package", dep))
        crates[manifest["package"]["name"]] = (f"{RUST_DIR}/{member}/", local)
    return crates


def rust_closure(crate: str, crates: dict[str, tuple[str, set[str]]]) -> list[str]:
    """Directories of `crate` and every workspace crate it depends on."""
    seen: set[str] = set()
    pending = [crate]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        if name not in crates:
            raise KeyError(f"unknown Rust crate {name!r}")
        seen.add(name)
        pending.extend(crates[name][1])
    return sorted(crates[name][0] for name in seen)


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern or fnmatch.fnmatchcase(path, pattern)


def _in_crate(path: str, crate_dirs: Iterable[str]) -> bool:
    for crate_dir in crate_dirs:
        if path.startswith(crate_dir):
            inner = path[len(crate_dir) :]
            return not inner.startswith(CRATE_IGNORED_DIRS)
    return False


class Graph:
    def __init__(self, root: Path = REPO_ROOT) -> None:
        crates = rust_crates(root)
        self.releases = {release.name: release for release in RELEASES}
        self.crate_dirs = {
            release.name: rust_closure(release.rust_root, crates) if release.rust_root else []
            for release in RELEASES
        }

    def reaches(self, release: str, path: str) -> bool:
        if path.endswith(IGNORED_SUFFIXES):
            return False
        spec = self.releases[release]
        if any(_matches(path, pattern) for pattern in spec.paths):
            return True
        return bool(spec.rust_root) and (path in RUST_SHARED or _in_crate(path, self.crate_dirs[release]))

    def fly(self, paths: Iterable[str]) -> tuple[dict[str, bool], list[str]]:
        """Which Fly apps to deploy, fail-open; plus one reason line per decision."""
        needed = dict.fromkeys(FLY_RELEASES, False)
        reasons: list[str] = []
        seen = False
        for path in paths:
            seen = True
            hit = [name for name in FLY_RELEASES if self.reaches(name, path)]
            if hit:
                reasons.append(f"{'+'.join(hit)}: {path}")
            elif any(_matches(path, pattern) for pattern in FLY_SHARED):
                hit = list(FLY_RELEASES)
                reasons.append(f"both apps (shared deploy input): {path}")
            elif path.startswith(f"{RUST_DIR}/") or any(_matches(path, pattern) for pattern in FLY_INERT):
                continue
            else:
                hit = list(FLY_RELEASES)
                reasons.append(f"both apps (unclassified, deploying to stay safe): {path}")
            for name in hit:
                needed[name] = True
        if not seen:
            reasons.append("Empty change listing; deploying both apps (fail-open).")
            needed = dict.fromkeys(FLY_RELEASES, True)
        return needed, reasons


def _read_nul_paths(stream) -> list[str]:
    data = stream.buffer.read() if hasattr(stream, "buffer") else stream.read()
    return [part.decode("utf-8", "surrogateescape") for part in data.split(b"\0") if part]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "fly",
        help="read NUL-separated changed paths on stdin; print backend=, frontend= and needed= lines",
    )
    reaches = commands.add_parser("reaches", help="print true when any PATH reaches RELEASE")
    reaches.add_argument("release", choices=[release.name for release in RELEASES])
    reaches.add_argument("paths", nargs="*")
    commands.add_parser("show", help="print every release with the paths and crates it is built from")
    args = parser.parse_args(argv)

    graph = Graph()
    if args.command == "fly":
        needed, reasons = graph.fly(_read_nul_paths(sys.stdin))
        for reason in reasons:
            print(reason, file=sys.stderr)
        if not any(needed.values()):
            print("Every changed path is deploy-inert; skipping the production release.", file=sys.stderr)
        print(f"backend={str(needed['fly-backend']).lower()}")
        print(f"frontend={str(needed['fly-frontend']).lower()}")
        print(f"needed={str(any(needed.values())).lower()}")
    elif args.command == "reaches":
        print("true" if any(graph.reaches(args.release, path) for path in args.paths) else "false")
    else:
        for release in RELEASES:
            print(release.name)
            for pattern in release.paths:
                print(f"  {pattern}")
            if release.rust_root:
                print(f"  rust crate {release.rust_root} and its dependencies:")
                for crate_dir in graph.crate_dirs[release.name]:
                    print(f"    {crate_dir}")
                for shared in RUST_SHARED:
                    print(f"    {shared}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
