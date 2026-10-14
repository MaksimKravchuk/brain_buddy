"""Markdown evidence writer for the automated rehearsal (spec 026, S1).

Rehearsal results are NOT reference-device evidence: they go to their own file and
never touch ``evidence/apple-pilot.md``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MACHINE = "MacBook Air M4 (not reference)"
STATUSES = ("PASS", "FAIL", "NOT_AUTOMATED")


def read_git_sha(start: Path) -> str:
    """HEAD sha from the .git files (the rehearsal never runs git)."""
    try:
        root = next(p for p in [start, *start.parents] if (p / ".git").exists())
        git = root / ".git"
        if git.is_file():
            git = Path(git.read_text().split("gitdir:", 1)[1].strip())
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(" ", 1)[1]
        common = git / "commondir"
        base = (git / common.read_text().strip()).resolve() if common.exists() else git
        for folder in (git, base):
            if (folder / ref).exists():
                return (folder / ref).read_text().strip()
        for line in (base / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except (OSError, StopIteration, IndexError):
        pass
    return "unknown"


def render(results: list[dict[str, Any]], identity: dict[str, Any]) -> str:
    """The "S1 API driver" markdown section."""
    lines = [
        f"# Automated rehearsal {identity['date']} (not reference-device evidence)",
        "",
        "Q-rows below are an API-level rehearsal. They do not fill any cell of "
        "`apple-pilot.md`, which stays `pending`.",
        "",
        "## S1 API driver",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for key in ("target", "git_sha", "machine", "timestamp", "run_id", "requests"):
        lines.append(f"| {key} | `{identity.get(key, '')}` |")
    lines += ["", "| Scenario | Status | Summary |", "| --- | --- | --- |"]
    for item in results:
        summary = str(item.get("summary", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {item['id']} {item['title']} | {item['status']} | {summary} |")
    for item in results:
        lines += ["", f"### {item['id']} {item['title']} - {item['status']}", ""]
        if item.get("reason"):
            lines += [f"Reason: {item['reason']}", ""]
        if item.get("correlation_ids"):
            lines += ["Correlation IDs: " + ", ".join(item["correlation_ids"]), ""]
        if item.get("observed") is not None:
            lines += ["```json", json.dumps(item["observed"], indent=2, default=str)]
            lines += ["```"]
    return "\n".join(lines) + "\n"


def write(
    results: list[dict[str, Any]], identity: dict[str, Any], out_dir: Path
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"rehearsal-{identity['date']}.md"
    path.write_text(render(results, identity), encoding="utf-8")
    return path


def stamp() -> tuple[str, str]:
    now = datetime.now(UTC)
    return now.astimezone().date().isoformat(), now.isoformat(timespec="seconds")
