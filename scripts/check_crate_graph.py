#!/usr/bin/env python3
"""Crate edges (``cargo metadata``) and module-ownership ``use`` rules (027-FR-008)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RUST = Path(__file__).resolve().parents[1] / "rust"

# Allowed normal/build edges between workspace crates, per crate.
_DP = "bb-domain bb-protocol"
ALLOWED_EDGES = {k: set(v.split()) for k, v in {
    "bb-domain": "bb-protocol", "bb-protocol": "", "bb-store": _DP,
    "bb-providers": _DP, "bb-app": f"bb-store bb-providers {_DP}",
    "bb-api": f"bb-app {_DP}",
    "bb-server": f"bb-api bb-app bb-store bb-providers {_DP}",
}.items()}  # fmt: skip
API_FORBIDDEN = {"bb-store", "bb-providers", "bb-server"}  # any kind, dev too
PURE_CRATES = {"bb-domain", "bb-protocol"}  # no I/O or web crates
IO_CRATES = set(
    "axum sqlx tokio tokio-postgres postgres reqwest hyper tower tower-http lettre "
    "rmcp object_store aws-sdk-s3 aws-config rust-s3 mio async-std ureq".split()
)
# Application modules sharing one store module (data-model: Tasks owner group).
OWNER_GROUP = dict.fromkeys("tasks review sync jobs navigator ai".split(), "tasks")
CONTROL_EXCEPTION = ("control", "mark_applied")
# Non-module support files inside bb-store that any module may use.
STORE_SHARED = {"error", "pool", "migrations", "tx", "db", "lib", "prelude"}

Path_ = tuple[str, ...]

def edge_violations(metadata: dict) -> list[str]:
    names = {p["name"] for p in metadata["packages"]}
    out: list[str] = []
    for pkg in metadata["packages"]:
        name = pkg["name"]
        for dep in pkg["dependencies"]:
            dname, kind = dep["name"], dep.get("kind")
            if name == "bb-api" and dname in API_FORBIDDEN:
                out.append(f"{name} -> {dname} ({kind or 'normal'}) is forbidden")
            if kind == "dev":
                continue
            if name in PURE_CRATES and dname in IO_CRATES:
                out.append(f"{name} must stay I/O-free but depends on {dname}")
            allowed = ALLOWED_EDGES.get(name)
            if dname in names and allowed is not None and dname not in allowed:
                out.append(f"{name} -> {dname} is not an allowed crate edge")
    return out


_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_IDENT = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*|\*)")
_SEP = re.compile(r"\s*::")
_ROOT = re.compile(r"\b(bb_store|crate)\s*::")


def _skip_ws(text: str, pos: int) -> int:
    while text[pos : pos + 1].isspace():
        pos += 1
    return pos


def _tree(text: str, pos: int, prefix: Path_) -> tuple[list[Path_], int]:
    """Expand a use-tree at ``pos`` into leaf paths; returns (leaves, new pos)."""
    pos = _skip_ws(text, pos)
    if text[pos : pos + 1] == "{":
        leaves: list[Path_] = []
        pos += 1
        while True:
            sub, pos = _tree(text, pos, prefix)
            leaves += sub
            pos = _skip_ws(text, pos)
            if text[pos : pos + 1] != ",":
                break
            pos += 1
        if text[pos : pos + 1] == "}":
            pos += 1
        return leaves, pos
    m = _IDENT.match(text, pos)
    if not m:
        return ([prefix] if prefix else []), pos
    prefix, pos = (*prefix, m.group(1)), m.end()
    sep = _SEP.match(text, pos)
    if sep:
        return _tree(text, sep.end(), prefix)
    return [prefix], pos


def references(source: str, roots: tuple[str, ...]) -> list[Path_]:
    """Paths (minus the root) that start with one of ``roots`` in ``source``."""
    text = _STRING.sub('""', _COMMENT.sub("", source))
    found: list[Path_] = []
    for m in _ROOT.finditer(text):
        if m.group(1) in roots:
            found += _tree(text, m.end(), ())[0]
    return found


def app_violations(src: Path) -> list[str]:
    """bb_app::<module> may import only bb_store::<its owner module>."""
    out: list[str] = []
    for f in sorted(src.rglob("*.rs")):
        parts = f.relative_to(src).parts
        module = parts[0].removesuffix(".rs")
        if module == "lib":
            continue
        if module == "ports":  # ports/<x>.rs is the port onto store module <x>
            if len(parts) < 2 or parts[1].removesuffix(".rs") == "mod":
                continue
            module = parts[1].removesuffix(".rs")
        owner = OWNER_GROUP.get(module, module)
        for ref in references(f.read_text(), ("bb_store",)):
            if ref[:1] != (owner,):
                out.append(
                    f"{f}: bb_app::{module} imports bb_store::{'::'.join(ref)}"
                    f" (only bb_store::{owner} allowed)"
                )
    return out


def store_violations(src: Path) -> list[str]:
    """bb_store::<module> may not reach another module, except mark_applied."""
    out: list[str] = []
    for f in sorted(src.rglob("*.rs")):
        module = f.relative_to(src).parts[0].removesuffix(".rs")
        if module in STORE_SHARED:
            continue
        for ref in references(f.read_text(), ("bb_store", "crate")):
            target = ref[0] if ref else ""
            if target in ("", module, "self", "super", *STORE_SHARED):
                continue
            if ref == CONTROL_EXCEPTION:
                continue
            out.append(
                f"{f}: bb_store::{module} reaches {'::'.join(ref)}"
                f" (only control::mark_applied is allowed)"
            )
    return out


def load_metadata(rust: Path) -> dict:
    res = subprocess.run(
        [
            "cargo",
            "metadata",
            "--no-deps",
            "--format-version",
            "1",
            "--manifest-path",
            str(rust / "Cargo.toml"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode:
        raise SystemExit(f"cargo metadata failed:\n{res.stderr}")
    return json.loads(res.stdout)


def check(metadata: dict, rust: Path) -> list[str]:
    out = edge_violations(metadata)
    crates = rust / "crates"
    if (crates / "bb-app/src").is_dir():
        out += app_violations(crates / "bb-app/src")
    if (crates / "bb-store/src").is_dir():
        out += store_violations(crates / "bb-store/src")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rust-dir", type=Path, default=RUST)
    ap.add_argument("--metadata", type=Path, help="cargo metadata JSON (skips cargo)")
    args = ap.parse_args(argv)
    meta = (
        json.loads(args.metadata.read_text())
        if args.metadata
        else load_metadata(args.rust_dir)
    )
    problems = check(meta, args.rust_dir)
    for p in problems:
        print(f"crate-graph: {p}", file=sys.stderr)
    if not problems:
        print("crate graph OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
