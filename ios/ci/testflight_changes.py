#!/usr/bin/env python3
"""Decide whether a commit range changes the iOS app, and write its TestFlight notes.

Used by .github/workflows/ios.yml. `decide` answers whether `main` should
upload a build: only when the range touches files that end up in the app
(app and widget sources, the shared kit's sources, the project and package
manifests), not when it only touches tests, docs, CI scripts or the macOS
app. `notes` writes the build's "What to Test": branch and commit, the pull
request title, and one line per commit in the range that changed the app.

Standard library and git only. It runs before any signing material exists,
but keeping it dependency-free keeps the upload workflow's surface small.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# Paths whose changes reach the binary uploaded to TestFlight. Prefixes end
# with "/"; the rest are exact files.
APP_PATHS: tuple[str, ...] = (
    "ios/BrainBuddy/",
    "ios/BrainBuddyWidgets/",
    "ios/Shared/",
    "ios/BrainBuddyKit/Sources/",
    "ios/BrainBuddyKit/Package.swift",
    "ios/BrainBuddyKit/Package.resolved",
    "ios/project.yml",
)
# Documentation inside those folders doesn't change the build.
IGNORED_SUFFIXES: tuple[str, ...] = (".md",)

# Apple caps whatsNew at 4000 characters; leave room for the truncation line.
MAX_NOTES = 4000
_MERGE_PR = re.compile(r"^Merge pull request #(\d+) from \S+$")


def is_app_path(path: str) -> bool:
    if path.endswith(IGNORED_SUFFIXES):
        return False
    return any(path.startswith(p) if p.endswith("/") else path == p for p in APP_PATHS)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def changed_paths(base: str, head: str) -> list[str]:
    return [line for line in git("diff", "--name-only", base, head).splitlines() if line]


def changes_app(base: str, head: str) -> bool:
    return any(is_app_path(path) for path in changed_paths(base, head))


def headline(head: str) -> str:
    """The pull request title for a merge commit, else the commit subject."""
    subject, _, body = git("log", "-1", "--format=%s%n%b", head).partition("\n")
    match = _MERGE_PR.match(subject.strip())
    title = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if match and title:
        return f"{title} (#{match.group(1)})"
    return subject.strip()


def app_commits(base: str, head: str) -> list[str]:
    """`<short sha> <subject>` for each non-merge commit in base..head that changed the app."""
    log = git("log", "--no-merges", "--name-only", "--format=%x00%h %s", f"{base}..{head}", "--", "ios/")
    commits = []
    for entry in log.split("\x00"):
        lines = [line for line in entry.splitlines() if line.strip()]
        if lines and any(is_app_path(path) for path in lines[1:]):
            commits.append(lines[0])
    return commits


def notes(base: str, head: str, branch: str) -> str:
    sha = git("rev-parse", "--short=7", head).strip()
    lines = [f"{branch} @ {sha}", headline(head), ""]
    commits = app_commits(base, head)
    if commits:
        lines.append("Changes in the app:")
    else:
        lines.append("No app changes in this range.")
    text = "\n".join(lines)
    for index, commit in enumerate(commits):
        line = f"\n- {commit}"
        remaining = len(commits) - index
        more = f"\n…and {remaining} more"
        if len(text) + len(line) + len(more) > MAX_NOTES:
            return text + more
        text += line
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    decide = commands.add_parser("decide", help="print true when base..head changes the app")
    decide.add_argument("--base", required=True)
    decide.add_argument("--head", required=True)
    write = commands.add_parser("notes", help="print the What to Test text for base..head")
    write.add_argument("--base", required=True)
    write.add_argument("--head", required=True)
    write.add_argument("--branch", required=True)
    args = parser.parse_args(argv)

    if args.command == "decide":
        print("true" if changes_app(args.base, args.head) else "false")
    else:
        print(notes(args.base, args.head, args.branch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
