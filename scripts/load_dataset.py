#!/usr/bin/env python3
"""Utility script to load seed datasets into the Brain Buddy data directory.

The dataset format is a JSON document with a top-level `trees` array. Each entry
must contain a `TreeDocument` payload compatible with `backend/app/schemas/domain.py`.

Usage:
    python scripts/load_dataset.py docs/pilot_dataset.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

TREE_FILENAME = "tree.json"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load seed trees into the Brain Buddy data directory.")
    parser.add_argument(
        "dataset",
        type=Path,
        help="Path to the dataset JSON file (see docs/pilot_dataset.json for an example).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("backend/data"),
        help="Target data directory. Defaults to backend/data relative to the repo root.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the dataset and show the changes without writing to disk.",
    )
    return parser.parse_args(argv)


def load_dataset(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict) or "trees" not in payload:
        raise ValueError("Dataset must be an object with a top-level `trees` array.")
    trees = payload["trees"]
    if not isinstance(trees, list):
        raise ValueError("`trees` must be a list.")
    validated: list[dict[str, Any]] = []
    for entry in trees:
        if not isinstance(entry, dict):
            raise ValueError("Each tree entry must be an object.")
        for required in ("id", "title", "updated_at", "nodes", "relations", "version_refs"):
            if required not in entry:
                raise ValueError(f"Tree `{entry.get('id','<unknown>')}` missing required field `{required}`.")
        validated.append(entry)
    return validated


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_index(index_path: Path) -> list[dict[str, Any]]:
    if not index_path.exists():
        return []
    with index_path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, list):
        raise ValueError("Existing index.json is malformed (expected a list).")
    return data


def iso_or_raise(value: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Timestamp `{value}` is not ISO-8601 compliant.") from exc
    return value


def write_tree(tree: dict[str, Any], data_dir: Path, dry_run: bool) -> Path:
    tree_dir = data_dir / tree["id"]
    tree_path = tree_dir / TREE_FILENAME
    if dry_run:
        return tree_path
    ensure_directory(tree_dir)
    with tree_path.open("w", encoding="utf-8") as fp:
        json.dump(tree, fp, indent=2, ensure_ascii=False)
        fp.write("\n")
    return tree_path


def update_index(trees: list[dict[str, Any]], index_path: Path, dry_run: bool) -> None:
    entries = load_index(index_path)
    existing = {entry.get("id"): entry for entry in entries if isinstance(entry, dict) and "id" in entry}
    for tree in trees:
        iso_updated = iso_or_raise(tree["updated_at"])
        existing[tree["id"]] = {
            "id": tree["id"],
            "title": tree.get("title"),
            "description": tree.get("description"),
            "updated_at": iso_updated,
        }
    new_entries = sorted(existing.values(), key=lambda item: item["updated_at"], reverse=True)
    if dry_run:
        return
    ensure_directory(index_path.parent)
    with index_path.open("w", encoding="utf-8") as fp:
        json.dump(new_entries, fp, indent=2, ensure_ascii=False)
        fp.write("\n")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    dataset = load_dataset(args.dataset)
    data_dir = args.data_dir
    index_path = data_dir / "index.json"

    print(f"[dataset] Loading {len(dataset)} tree(s) from {args.dataset}")
    print(f"[dataset] Target data directory: {data_dir}")
    if args.dry_run:
        print("[dataset] Dry run enabled — no files will be written.")

    for tree in dataset:
        tree_path = write_tree(tree, data_dir, args.dry_run)
        print(f"[dataset] {'Would write' if args.dry_run else 'Wrote'} {tree_path}")

    update_index(dataset, index_path, args.dry_run)
    print(f"[dataset] {'Would update' if args.dry_run else 'Updated'} index at {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
