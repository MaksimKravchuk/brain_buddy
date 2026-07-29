"""Deterministic Allure taxonomy for the backend pytest suite.

Every backend test must emit a non-empty epic/feature/story, a human-readable
title, and at least one named step (enforced by
``scripts/validate_allure_taxonomy.py``). Rather than repeat ``@allure.*``
decorators across hundreds of tests, this module maps each test's module to a
meaningful (epic, feature, story) triple and derives a human title/step from the
test's own docstring or name. The mapping is applied centrally by an autouse
fixture in ``conftest.py``.

Tests may still override any dimension with the usual ``@allure.epic`` /
``@allure.feature`` / ``@allure.story`` / ``@allure.title`` decorators — the
fixture only fills dimensions a test has not set for itself.
"""

from __future__ import annotations

from dataclasses import dataclass

# Product-area epics grouping the backend by capability, not by test mechanics.
EPIC_REALITY_TREE = "Reality Tree"
EPIC_TASKS = "Task Management"
EPIC_AUTH = "Authentication & Access"
EPIC_AI = "AI Validation"
EPIC_QUALITY = "Platform Quality"

# Module stem -> (epic, feature, story). Keyed by the test file name without the
# leading ``test_`` and ``.py``. Keep these meaningful: feature is the subsystem
# under test, story is the behaviour grouping shown in the Allure tree.
_MODULE_TAXONOMY: dict[str, tuple[str, str, str]] = {
    # Reality Tree — services & repositories
    "tree_service": (EPIC_REALITY_TREE, "Tree service", "Tree lifecycle operations"),
    "node_service": (EPIC_REALITY_TREE, "Node service", "Node mutations"),
    "relation_service": (EPIC_REALITY_TREE, "Relation service", "Relation linking"),
    "version_service": (EPIC_REALITY_TREE, "Version service", "Version snapshots"),
    "version_repository": (
        EPIC_REALITY_TREE,
        "Version repository",
        "Version persistence",
    ),
    "index_repository": (EPIC_REALITY_TREE, "Index repository", "Tree index persistence"),
    "repository_and_cli_edges": (
        EPIC_REALITY_TREE,
        "Repositories & CLI",
        "Storage and CLI edge cases",
    ),
    "service_edge_cases": (EPIC_REALITY_TREE, "Domain services", "Service edge cases"),
    # Reality Tree — HTTP API
    "api_trees": (EPIC_REALITY_TREE, "Tree API", "Tree HTTP endpoints"),
    "api_versions": (EPIC_REALITY_TREE, "Version API", "Version HTTP endpoints"),
    "api_mutation_and_errors": (
        EPIC_REALITY_TREE,
        "Tree API",
        "Mutation and error handling",
    ),
    "tree_ai_feedback": (EPIC_REALITY_TREE, "Tree API", "AI feedback endpoint"),
    "tree_import_export": (EPIC_REALITY_TREE, "Tree API", "Import and export"),
    # Task management
    "task_api": (EPIC_TASKS, "Task API", "Task HTTP endpoints"),
    "task_smart_add_api": (EPIC_TASKS, "Task API", "Smart Add classification"),
    "task_branch_coverage": (EPIC_TASKS, "Task API", "Task API branch coverage"),
    "task_tag_project_mvp_api": (
        EPIC_TASKS,
        "Projects & tags API",
        "Task projects and tags",
    ),
    "brain_dump_operations_api": (
        EPIC_TASKS,
        "Brain dump API",
        "Voice brain dump operation lifecycle",
    ),
    "voice_brain_dump_reconciliation": (
        EPIC_TASKS,
        "Voice brain dump reconciliation",
        "Schema v2 dual-STT contracts",
    ),
    # Authentication & access
    "auth_service": (EPIC_AUTH, "Auth service", "Credential and session logic"),
    "auth_routes": (EPIC_AUTH, "Auth API", "Auth HTTP endpoints"),
    "ownership": (EPIC_AUTH, "Ownership", "Per-user data isolation"),
    # AI validation
    "validation_service": (EPIC_AI, "Validation service", "AI feedback orchestration"),
    "api_validation": (EPIC_AI, "Validation API", "AI validation endpoint"),
    "prompt_and_provider_adapters": (
        EPIC_AI,
        "Provider adapters",
        "Prompt and provider adapters",
    ),
    # Platform quality
    "api_contract": (EPIC_QUALITY, "API contract", "Error envelope contract"),
    "schemathesis_contract": (EPIC_QUALITY, "API contract", "Schemathesis fuzzing"),
    "property_invariants": (EPIC_QUALITY, "Property invariants", "Tree invariants"),
    "branch_invariants": (EPIC_QUALITY, "Branch invariants", "Tree branch invariants"),
    "mutation_survivor_exact": (
        EPIC_QUALITY,
        "Mutation resistance",
        "Surviving-mutant kills",
    ),
    "config": (EPIC_QUALITY, "Configuration", "App configuration"),
    "feature_flags": (EPIC_QUALITY, "Feature flags", "Server-owned rollout flags"),
    "health": (EPIC_QUALITY, "Health", "Health endpoint"),
    "utils_file_ops": (EPIC_QUALITY, "File utilities", "Atomic file operations"),
    "utils_time": (EPIC_QUALITY, "Time utilities", "Time helpers"),
}


@dataclass(frozen=True)
class TestTaxonomy:
    epic: str
    feature: str
    story: str
    title: str
    step: str


def _humanize(identifier: str) -> str:
    """Turn a ``test_snake_case`` identifier into a readable sentence."""

    stem = identifier
    if stem.startswith("test_"):
        stem = stem[len("test_") :]
    words = [word for word in stem.split("_") if word]
    if not words:
        return identifier
    phrase = " ".join(words)
    return phrase[0].upper() + phrase[1:]


def _module_stem(module_name: str) -> str:
    """``tests.api.test_tree_import_export`` -> ``tree_import_export``."""

    leaf = module_name.rsplit(".", 1)[-1]
    if leaf.startswith("test_"):
        leaf = leaf[len("test_") :]
    return leaf


def resolve(
    module_name: str,
    function_name: str,
    docstring: str | None,
    param_id: str | None = None,
) -> TestTaxonomy:
    """Compute the taxonomy for a single test.

    epic/feature/story come from the deterministic module map (with a readable
    fallback for unmapped modules); the title and step are derived from the
    test's own docstring or name so they stay meaningful and test-specific.
    """

    stem = _module_stem(module_name)
    epic, feature, story = _MODULE_TAXONOMY.get(
        stem, (EPIC_QUALITY, _humanize(stem), f"{_humanize(stem)} behaviour")
    )

    summary = ""
    if docstring:
        summary = docstring.strip().splitlines()[0].strip().rstrip(".")
    title = summary or _humanize(function_name)
    if param_id:
        title = f"{title} [{param_id}]"

    step = summary or f"Exercise {_humanize(function_name).lower()}"
    return TestTaxonomy(epic=epic, feature=feature, story=story, title=title, step=step)
