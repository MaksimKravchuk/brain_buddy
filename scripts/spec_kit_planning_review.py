#!/usr/bin/env python3
"""Run bounded, read-only reviews for the Architect Spec Kit planning lane.

The workflow engine owns scheduling and persisted run state. This helper owns
sandbox enforcement, structured output validation, and deterministic fan-in.
It never edits product or planning artifacts; only the parent Architect may do
that after reading the generated review summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
PRODUCT_DECISION_CATEGORIES = {
    "scope",
    "ux",
    "priority",
    "privacy",
    "permissions",
    "pricing",
    "safety-compliance",
    "acceptance-behavior",
}
VERDICTS = {"pass", "changes-required", "product-decision-required"}
SEVERITIES = {"blocking", "important", "advisory"}
STANDARD_ROLES = (
    "requirements-consistency",
    "architecture-consistency",
    "testability-evidence",
)
ROLE_CONFIGS: dict[str, dict[str, str]] = {
    "requirements-consistency": {
        "integration": "codex",
        "model": "gpt-5.6-sol",
        "focus": (
            "Find contradictions, missing acceptance behavior, unsupported scope, "
            "and mismatches between spec.md and plan.md."
        ),
    },
    "architecture-consistency": {
        "integration": "codex",
        "model": "gpt-5.6-sol",
        "focus": (
            "Challenge boundaries, contracts, data ownership, failure handling, "
            "migration/rollback, ADR alignment, and repository factual claims."
        ),
    },
    "testability-evidence": {
        "integration": "codex",
        "model": "gpt-5.6-sol",
        "focus": (
            "Check that every acceptance outcome has proportionate automated or "
            "operational evidence and that tasks can be grouped into independent lanes."
        ),
    },
    "adversarial-high-risk": {
        "integration": "claude",
        "model": "fable",
        "focus": (
            "Perform an adversarial high-risk review of security, privacy, data loss, "
            "concurrency, public contracts, migrations, and irreversible decisions."
        ),
    },
}


class ReviewError(RuntimeError):
    """Raised when a reviewer cannot produce valid planning evidence."""


def project_root() -> Path:
    root = Path.cwd().resolve()
    if not (root / ".specify").is_dir() or not (root / "specs").is_dir():
        raise ReviewError("Run from an initialized BrainBuddy Spec Kit worktree")
    return root


def run_directory(root: Path, run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ReviewError(f"Unsafe workflow run id: {run_id!r}")
    runs_root = (root / ".specify" / "workflows" / "runs").resolve()
    candidate = runs_root / run_id
    candidate.mkdir(parents=True, exist_ok=True)
    resolved = candidate.resolve()
    if resolved.parent != runs_root:
        raise ReviewError("Workflow run directory escaped the project run root")
    return resolved


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: object, field: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ValueError(f"{field} must be a list with at least {minimum} item(s)")
    result = [_required_string(item, f"{field}[]") for item in value]
    return result


def validate_review(payload: object, *, expected_role: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("review output must be a JSON object")

    role = _required_string(payload.get("role"), "role")
    if role != expected_role:
        raise ValueError(f"role mismatch: expected {expected_role!r}, got {role!r}")

    verdict = _required_string(payload.get("verdict"), "verdict")
    if verdict not in VERDICTS:
        raise ValueError(f"unsupported verdict: {verdict!r}")

    summary = _required_string(payload.get("summary"), "summary")
    reviewed_files = _string_list(payload.get("reviewed_files"), "reviewed_files", minimum=1)

    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise ValueError("findings must be a list")
    findings: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_findings):
        if not isinstance(raw, dict):
            raise ValueError(f"findings[{index}] must be an object")
        severity = _required_string(raw.get("severity"), f"findings[{index}].severity")
        if severity not in SEVERITIES:
            raise ValueError(f"findings[{index}].severity is unsupported")
        findings.append(
            {
                "severity": severity,
                "category": _required_string(raw.get("category"), f"findings[{index}].category"),
                "description": _required_string(
                    raw.get("description"), f"findings[{index}].description"
                ),
                "evidence": _string_list(
                    raw.get("evidence"), f"findings[{index}].evidence", minimum=1
                ),
                "recommendation": _required_string(
                    raw.get("recommendation"), f"findings[{index}].recommendation"
                ),
            }
        )

    raw_decisions = payload.get("product_decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("product_decisions must be a list")
    decisions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_decisions):
        if not isinstance(raw, dict):
            raise ValueError(f"product_decisions[{index}] must be an object")
        category = _required_string(
            raw.get("category"), f"product_decisions[{index}].category"
        )
        if category not in PRODUCT_DECISION_CATEGORIES:
            raise ValueError(f"unsupported product decision category: {category!r}")
        decisions.append(
            {
                "category": category,
                "question": _required_string(
                    raw.get("question"), f"product_decisions[{index}].question"
                ),
                "why_needed": _required_string(
                    raw.get("why_needed"), f"product_decisions[{index}].why_needed"
                ),
                "options": _string_list(
                    raw.get("options"), f"product_decisions[{index}].options", minimum=2
                ),
                "affected_acceptance": _required_string(
                    raw.get("affected_acceptance"),
                    f"product_decisions[{index}].affected_acceptance",
                ),
            }
        )

    if verdict == "product-decision-required" and not decisions:
        raise ValueError("product_decisions is required for product-decision-required verdict")
    if decisions and verdict != "product-decision-required":
        raise ValueError("product_decisions require product-decision-required verdict")
    if verdict == "changes-required" and not findings:
        raise ValueError("changes-required verdict requires findings")

    return {
        "role": role,
        "verdict": verdict,
        "summary": summary,
        "reviewed_files": reviewed_files,
        "findings": findings,
        "product_decisions": decisions,
    }


def _decode_json_candidate(text: str) -> object:
    stripped = text.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        stripped = stripped[7:-3].strip()
    elif stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("reviewer output did not contain a JSON object") from None
        return json.loads(stripped[start : end + 1])


def parse_review_output(raw: str) -> dict[str, Any]:
    parsed = _decode_json_candidate(raw)
    if not isinstance(parsed, dict):
        raise ValueError("reviewer output must decode to an object")
    structured = parsed.get("structured_output")
    if isinstance(structured, dict):
        return structured
    result = parsed.get("result")
    if isinstance(result, str):
        nested = _decode_json_candidate(result)
        if isinstance(nested, dict):
            return nested
    return parsed


def build_review_command(
    *, role: str, prompt: str, schema_path: Path
) -> tuple[list[str], dict[str, str]]:
    try:
        config = ROLE_CONFIGS[role]
    except KeyError as exc:
        raise ReviewError(f"Unknown review role: {role}") from exc

    env = os.environ.copy()
    integration = config["integration"]
    if integration == "codex":
        return (
            [
                "codex",
                "exec",
                "--model",
                config["model"],
                "-c",
                "model_reasoning_effort=xhigh",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
                prompt,
            ],
            env,
        )

    env.pop("ANTHROPIC_API_KEY", None)
    schema = schema_path.read_text(encoding="utf-8")
    return (
        [
            "claude",
            "-p",
            "--model",
            config["model"],
            "--effort",
            "max",
            "--permission-mode",
            "plan",
            "--allowedTools",
            "Read,Grep,Glob",
            "--no-session-persistence",
            "--output-format",
            "json",
            "--json-schema",
            schema,
            prompt,
        ],
        env,
    )


def resolve_feature_dir(root: Path) -> Path:
    command = [
        "bash",
        ".specify/scripts/bash/check-prerequisites.sh",
        "--json",
        "--paths-only",
    ]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=60)
    if result.returncode != 0:
        raise ReviewError(result.stderr.strip() or "Spec Kit prerequisite check failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReviewError("Spec Kit prerequisite output was not JSON") from exc
    raw_dir = payload.get("FEATURE_DIR") or payload.get("feature_dir")
    if not isinstance(raw_dir, str) or not raw_dir:
        raise ReviewError("Spec Kit prerequisite output omitted FEATURE_DIR")
    feature_dir = Path(raw_dir)
    if not feature_dir.is_absolute():
        feature_dir = root / feature_dir
    feature_dir = feature_dir.resolve()
    specs_root = (root / "specs").resolve()
    if specs_root not in feature_dir.parents:
        raise ReviewError("Resolved feature directory is outside specs/")
    for name in ("spec.md", "plan.md"):
        if not (feature_dir / name).is_file():
            raise ReviewError(f"Planning review requires {feature_dir / name}")
    return feature_dir


def build_prompt(*, role: str, feature_dir: Path, root: Path) -> str:
    config = ROLE_CONFIGS[role]
    relative_feature = feature_dir.relative_to(root)
    allowed_categories = ", ".join(sorted(PRODUCT_DECISION_CATEGORIES))
    return f"""You are a read-only planning reviewer for BrainBuddy.

Review role: {role}
Focus: {config['focus']}
Repository root: {root}
Feature artifacts: {relative_feature}/spec.md and {relative_feature}/plan.md
Also inspect relevant accepted/proposed ADRs and current code only where needed to verify factual claims.

Hard boundaries:
- Do not edit files, run implementation, commit, push, create cards, or propose a second scheduler.
- Spec Kit tasks are planning input; Hermes Kanban remains the sole execution runtime.
- Technical decisions belong to Architect. Do not escalate database, framework, API shape, module boundary, testing strategy, migration mechanics, or implementation choices to the product owner.
- Product decisions are allowed only for: {allowed_categories}.
- Cite concrete file paths/symbols/sections in every finding's evidence.
- Return only JSON matching the supplied schema, with role exactly {role!r}.
"""


def run_review(*, root: Path, run_id: str, role: str) -> Path:
    run_dir = run_directory(root, run_id)
    context_path = run_dir / "planning-context.json"
    if not context_path.is_file():
        raise ReviewError("Planning preflight was not completed for this run")
    context = json.loads(context_path.read_text(encoding="utf-8"))
    feature_dir = Path(context["feature_dir"]).resolve()
    if (root / "specs").resolve() not in feature_dir.parents:
        raise ReviewError("Persisted feature directory escaped specs/")

    schema_path = root / ".specify" / "workflows" / "speckit" / "review.schema.json"
    prompt = build_prompt(role=role, feature_dir=feature_dir, root=root)
    command, env = build_review_command(role=role, prompt=prompt, schema_path=schema_path)
    if shutil.which(command[0]) is None:
        raise ReviewError(f"Required reviewer CLI is not installed: {command[0]}")

    result = subprocess.run(
        command,
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise ReviewError(f"{role} reviewer failed: {detail[-2000:]}")
    review = validate_review(parse_review_output(result.stdout), expected_role=role)
    target = run_dir / "reviews" / f"{role}.json"
    write_json_atomic(target, review)
    return target


def aggregate_reviews(reviews: list[dict[str, Any]], *, risk: str) -> dict[str, Any]:
    technical_findings: list[dict[str, Any]] = []
    product_decisions: list[dict[str, Any]] = []
    reviewers: list[dict[str, str]] = []
    for review in reviews:
        role = str(review["role"])
        reviewers.append(
            {"role": role, "verdict": str(review["verdict"]), "summary": str(review["summary"])}
        )
        for finding in review.get("findings", []):
            technical_findings.append({"reviewer": role, **finding})
        for decision in review.get("product_decisions", []):
            product_decisions.append({"reviewer": role, **decision})

    if product_decisions:
        status = "product-decision-required"
        action = "Block only the Architect Kanban card with this decision packet."
    elif any(item.get("severity") == "blocking" for item in technical_findings):
        status = "technical-changes-required"
        action = "Architect resolves technical findings and reruns the review campaign once."
    else:
        status = "approved"
        action = "Architect may finalize tasks.md, analyze, and the compact Kanban handoff."

    return {
        "status": status,
        "risk": risk,
        "reviewers": reviewers,
        "technical_findings": technical_findings,
        "product_decisions": product_decisions,
        "architect_action": action,
    }


def preflight(*, root: Path, run_id: str) -> Path:
    feature_dir = resolve_feature_dir(root)
    target = run_directory(root, run_id) / "planning-context.json"
    write_json_atomic(target, {"feature_dir": str(feature_dir), "project_root": str(root)})
    return target


def parse_workflow_inputs(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ReviewError("Workflow inputs.json must contain an object")
    inputs = payload.get("inputs", payload)
    if not isinstance(inputs, dict):
        raise ReviewError("Workflow inputs envelope must contain an inputs object")
    return inputs


def summarize(*, root: Path, run_id: str) -> Path:
    run_dir = run_directory(root, run_id)
    inputs_path = run_dir / "inputs.json"
    if not inputs_path.is_file():
        raise ReviewError("Workflow inputs.json is missing")
    inputs = parse_workflow_inputs(json.loads(inputs_path.read_text(encoding="utf-8")))
    risk = inputs.get("risk", "standard")
    if risk not in {"standard", "high"}:
        raise ReviewError(f"Unsupported risk value: {risk!r}")

    roles: list[str] = list(STANDARD_ROLES)
    if risk == "high":
        roles.append("adversarial-high-risk")
    reviews: list[dict[str, Any]] = []
    for role in roles:
        path = run_dir / "reviews" / f"{role}.json"
        if not path.is_file():
            raise ReviewError(f"Required review output is missing: {path}")
        reviews.append(
            validate_review(json.loads(path.read_text(encoding="utf-8")), expected_role=role)
        )

    summary = aggregate_reviews(reviews, risk=risk)
    summary["run_id"] = run_id
    target = run_dir / "planning-review-summary.json"
    write_json_atomic(target, summary)
    print(target)
    return target


def validate_handoff(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("handoff must be a JSON object")
    if payload.get("schema_version") != "speckit-hermes-handoff/v1":
        raise ValueError("unsupported handoff schema_version")

    root_outcome = _required_string(payload.get("root_outcome"), "root_outcome")
    raw_artifacts = payload.get("artifacts")
    if not isinstance(raw_artifacts, dict):
        raise ValueError("artifacts must be an object")
    artifacts: dict[str, Any] = {
        name: _required_string(raw_artifacts.get(name), f"artifacts.{name}")
        for name in ("spec", "plan", "tasks", "checklist")
    }
    artifacts["adrs"] = _string_list(raw_artifacts.get("adrs", []), "artifacts.adrs")

    raw_review = payload.get("planning_review")
    if not isinstance(raw_review, dict):
        raise ValueError("planning_review must be an object")
    run_id = _required_string(raw_review.get("run_id"), "planning_review.run_id")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("planning_review.run_id is invalid")
    risk = _required_string(raw_review.get("risk"), "planning_review.risk")
    if risk not in {"standard", "high"}:
        raise ValueError("planning_review.risk is unsupported")
    if raw_review.get("status") != "approved":
        raise ValueError("planning_review.status must be approved")
    reviewers = _string_list(
        raw_review.get("reviewers"), "planning_review.reviewers", minimum=3
    )
    missing_standard = sorted(set(STANDARD_ROLES) - set(reviewers))
    if missing_standard:
        raise ValueError(f"planning_review.reviewers missing {missing_standard}")
    if risk == "high" and "adversarial-high-risk" not in reviewers:
        raise ValueError("high-risk handoff requires adversarial-high-risk reviewer")

    raw_decisions = payload.get("product_decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("product_decisions must be a list")
    product_decisions: list[dict[str, str]] = []
    for index, raw in enumerate(raw_decisions):
        if not isinstance(raw, dict):
            raise ValueError(f"product_decisions[{index}] must be an object")
        category = _required_string(
            raw.get("category"), f"product_decisions[{index}].category"
        )
        if category not in PRODUCT_DECISION_CATEGORIES:
            raise ValueError(f"unsupported product decision category: {category!r}")
        product_decisions.append(
            {
                "category": category,
                "question": _required_string(
                    raw.get("question"), f"product_decisions[{index}].question"
                ),
                "answer": _required_string(
                    raw.get("answer"), f"product_decisions[{index}].answer"
                ),
                "evidence_ref": _required_string(
                    raw.get("evidence_ref"), f"product_decisions[{index}].evidence_ref"
                ),
            }
        )

    raw_lanes = payload.get("lanes")
    if not isinstance(raw_lanes, list) or not 1 <= len(raw_lanes) <= 6:
        raise ValueError("lanes must contain between 1 and 6 coarse lanes")
    lanes: list[dict[str, Any]] = []
    lane_ids: set[str] = set()
    writer_scopes: set[str] = set()
    for index, raw in enumerate(raw_lanes):
        if not isinstance(raw, dict):
            raise ValueError(f"lanes[{index}] must be an object")
        lane_id = _required_string(raw.get("id"), f"lanes[{index}].id")
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", lane_id):
            raise ValueError(f"lanes[{index}].id is invalid")
        if lane_id in lane_ids:
            raise ValueError(f"duplicate lane id: {lane_id}")
        lane_ids.add(lane_id)
        scopes = _string_list(
            raw.get("exclusive_writer_scope"),
            f"lanes[{index}].exclusive_writer_scope",
            minimum=1,
        )
        overlap = writer_scopes.intersection(scopes)
        if overlap:
            raise ValueError(f"exclusive writer scope reused across lanes: {sorted(overlap)}")
        writer_scopes.update(scopes)
        lanes.append(
            {
                "id": lane_id,
                "outcome": _required_string(raw.get("outcome"), f"lanes[{index}].outcome"),
                "depends_on": _string_list(
                    raw.get("depends_on"), f"lanes[{index}].depends_on"
                ),
                "task_refs": _string_list(
                    raw.get("task_refs"), f"lanes[{index}].task_refs", minimum=1
                ),
                "scope_paths": _string_list(
                    raw.get("scope_paths"), f"lanes[{index}].scope_paths", minimum=1
                ),
                "exclusive_writer_scope": scopes,
                "acceptance_evidence": _string_list(
                    raw.get("acceptance_evidence"),
                    f"lanes[{index}].acceptance_evidence",
                    minimum=1,
                ),
            }
        )

    adjacency = {lane["id"]: lane["depends_on"] for lane in lanes}
    for lane_id, dependencies in adjacency.items():
        unknown = sorted(set(dependencies) - lane_ids)
        if unknown:
            raise ValueError(f"lane {lane_id} has unknown dependencies: {unknown}")
        if lane_id in dependencies:
            raise ValueError(f"lane {lane_id} depends on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(lane_id: str) -> None:
        if lane_id in visiting:
            raise ValueError("lane dependency cycle detected")
        if lane_id in visited:
            return
        visiting.add(lane_id)
        for dependency in adjacency[lane_id]:
            visit(dependency)
        visiting.remove(lane_id)
        visited.add(lane_id)

    for lane_id in adjacency:
        visit(lane_id)

    return {
        "schema_version": "speckit-hermes-handoff/v1",
        "root_outcome": root_outcome,
        "artifacts": artifacts,
        "planning_review": {
            "run_id": run_id,
            "risk": risk,
            "status": "approved",
            "reviewers": reviewers,
        },
        "product_decisions": product_decisions,
        "lanes": lanes,
        "risks": _string_list(payload.get("risks", []), "risks"),
        "non_goals": _string_list(payload.get("non_goals", []), "non_goals"),
    }


def validate_handoff_file(*, root: Path) -> Path:
    feature_dir = resolve_feature_dir(root)
    path = feature_dir / "hermes-handoff.json"
    if not path.is_file():
        raise ReviewError(f"Hermes handoff is missing: {path}")
    handoff = validate_handoff(json.loads(path.read_text(encoding="utf-8")))
    for key in ("spec", "plan", "tasks", "checklist"):
        candidate = (root / handoff["artifacts"][key]).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise ReviewError(f"Handoff artifact is missing or outside repository: {candidate}")
    print(path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "summarize"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--run-id", required=True)
    review = subparsers.add_parser("review")
    review.add_argument("--run-id", required=True)
    review.add_argument("--role", required=True, choices=sorted(ROLE_CONFIGS))
    subparsers.add_parser("validate-handoff")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = project_root()
        if args.command == "preflight":
            print(preflight(root=root, run_id=args.run_id))
        elif args.command == "review":
            print(run_review(root=root, run_id=args.run_id, role=args.role))
        elif args.command == "summarize":
            summarize(root=root, run_id=args.run_id)
        else:
            validate_handoff_file(root=root)
    except (ReviewError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"planning-review error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
