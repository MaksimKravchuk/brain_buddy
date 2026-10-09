"""Spec 026 (tasks.md T002): the frozen parity oracle holds against the repository.

``specs/026-rust-core-sync/contracts/reference-store.json`` freezes the existing
normative files by path and sha256, so an oracle can only change through an
explicit, reviewed edit of its hash (recompute with ``sha256sum``). It also
carries the bounded synthetic dataset, which is loaded here into the real
``TaskRepository`` and read back, and ``web-presentation-vectors.json``, whose
``Smart Add`` payloads are checked against the server's own request model.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import allure
import pytest
from pydantic import BaseModel, ValidationError

from app.modules.tasks.domain import (
    ProjectDocument,
    TagDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.modules.tasks.repository import (
    TaskRepository,
    display_tag_name,
    normalize_task_name,
)
from app.schemas.tasks import SmartAddTaskCreateRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "specs" / "026-rust-core-sync" / "contracts"
STORE: dict[str, Any] = json.loads(
    (CONTRACTS / "reference-store.json").read_text(encoding="utf-8")
)
WEB: dict[str, Any] = json.loads(
    (CONTRACTS / "web-presentation-vectors.json").read_text(encoding="utf-8")
)
DATASET: dict[str, Any] = STORE["dataset"]
RECORDS: dict[str, list[dict[str, Any]]] = DATASET["records"]


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [row["id"] for row in rows]


# --------------------------------------------------------------------- manifest
@pytest.mark.parametrize(
    "source", STORE["oracle_sources"], ids=_ids(STORE["oracle_sources"])
)
def test_026_FR_002_oracle_source_is_frozen(source: dict[str, Any]) -> None:
    """Each oracle file matches its recorded hash, schema, sections and copies."""

    path = REPO_ROOT / source["path"]
    with allure.step("Hash the file"):
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"], (
            f"{source['path']} changed: update its sha256 in reference-store.json "
            "together with every consumer"
        )
        assert len(raw) == source["bytes"]
    with allure.step("Compare schema and section counts"):
        document = json.loads(raw)
        assert document.get("schema") == source["schema"]
        sections = {k: len(v) for k, v in document.items() if isinstance(v, list)}
        assert sections == source["sections"]
        assert any(sections.values()), "an oracle must carry at least one case"
    with allure.step("Check copies are byte-identical and consumers exist"):
        for copy in source["copies"]:
            assert (REPO_ROOT / copy).read_bytes() == raw, f"{copy} drifted"
        for consumer in source["consumers"]:
            assert (REPO_ROOT / consumer).is_file(), f"missing consumer {consumer}"


def test_026_FR_002_manifest_lists_every_task_oracle_and_resolves_in_source_ones() -> (
    None
):
    """The three files T002 names are listed, and in-source oracles exist."""

    with allure.step("List the files T002 names"):
        listed = {source["path"] for source in STORE["oracle_sources"]}
        for name in (
            "review_formulation_vectors.json",
            "review_flow_vectors.json",
            "project_archive_traces.json",
        ):
            assert f"backend/tests/fixtures/{name}" in listed
        assert len(listed) == len(STORE["oracle_sources"])
    with allure.step("Resolve in-source oracles"):
        for entry in STORE["in_source_oracles"]:
            assert (REPO_ROOT / entry["path"]).is_file(), entry["path"]
            if entry["folded_into"]:
                assert (REPO_ROOT / entry["folded_into"].split("#")[0]).is_file()
    with allure.step("Every contradiction names evidence and a status"):
        ids = _ids(STORE["contradictions"])
        assert len(ids) == len(set(ids)) > 0
        for item in STORE["contradictions"]:
            assert item["evidence"] and item["proposed_resolution"]
            assert item["status"] in {"proposed", "decision-needed"}


# ---------------------------------------------------------------------- dataset
def test_026_SC_005_dataset_records_are_valid_stored_documents() -> None:
    """Every record validates against the server's own storage models."""

    models: dict[str, type[BaseModel]] = {
        "projects": ProjectDocument,
        "tags": TagDocument,
        "tasks": TaskDocument,
        "subtasks": TaskSubtaskDocument,
        "comments": TaskCommentDocument,
    }
    with allure.step("Validate and round-trip each record"):
        for kind, model in models.items():
            assert RECORDS[kind], kind
            for record in RECORDS[kind]:
                assert model.model_validate(record).model_dump(mode="json") == record


def test_026_SC_005_dataset_counts_and_relationships_hold() -> None:
    """Counts match the frozen expectation and every reference stays in its owner."""

    owners = DATASET["owners"]
    with allure.step("Count records per owner and task state"):
        for owner in owners:
            expected = DATASET["expected_counts"][owner]
            for kind in ("projects", "tags", "tasks", "subtasks", "comments"):
                actual = sum(1 for r in RECORDS[kind] if r["owner_id"] == owner)
                assert actual == expected[kind], (owner, kind)
            states = Counter(
                t["state"] for t in RECORDS["tasks"] if t["owner_id"] == owner
            )
            assert dict(sorted(states.items())) == expected["tasks_by_state"]
        all_states = {t["state"] for t in RECORDS["tasks"]}
        assert all_states == {
            "inbox", "next", "waiting", "someday", "completed", "cancelled",
        }  # fmt: skip
    with allure.step("Resolve references within the same owner"):
        by_id = {
            kind: {r["id"]: r for r in RECORDS[kind]}
            for kind in ("projects", "tags", "tasks")
        }
        for task in RECORDS["tasks"]:
            if task["project_id"] is not None:
                assert by_id["projects"][task["project_id"]]["owner_id"] == (
                    task["owner_id"]
                )
            for tag_id in task["tag_ids"]:
                tag = by_id["tags"][tag_id]
                assert tag["owner_id"] == task["owner_id"]
                assert tag["state"] != "deleted"
        for child in RECORDS["subtasks"] + RECORDS["comments"]:
            assert by_id["tasks"][child["task_id"]]["owner_id"] == child["owner_id"]
    with allure.step("Archived projects keep their tasks (lossless archive)"):
        archived = {p["id"]: p for p in RECORDS["projects"] if p["state"] == "archived"}
        kept = [t for t in RECORDS["tasks"] if t["project_id"] in archived]
        assert kept, "the dataset must hold tasks inside archived projects"
        lossless = [p for p in archived.values() if p["archived_at"] is not None]
        legacy = [p for p in archived.values() if p["archived_before_lossless"]]
        assert lossless and legacy


def test_026_SC_005_dataset_name_keys_follow_the_server_rule() -> None:
    """``normalized_name`` is the server key, and owners may share names."""

    with allure.step("Recompute project and tag keys"):
        for project in RECORDS["projects"]:
            assert project["normalized_name"] == normalize_task_name(project["name"])
        for tag in RECORDS["tags"]:
            assert tag["normalized_name"] == normalize_task_name(
                tag["name"], strip_tag_prefix=True
            )
            assert display_tag_name(tag["name"]) == tag["name"]
    with allure.step("Same key under two owners is allowed"):
        keys = Counter(p["normalized_name"] for p in RECORDS["projects"])
        shared = [key for key, count in keys.items() if count > 1]
        assert shared, "owner B reuses an owner A name"
        owners_by_key = {
            key: {
                p["owner_id"]
                for p in RECORDS["projects"]
                if p["normalized_name"] == key
            }
            for key in shared
        }
        assert all(len(owners) > 1 for owners in owners_by_key.values())


def test_026_SC_005_dataset_restores_into_the_real_repository(tmp_path: Path) -> None:
    """Import then read back preserves every record and relationship."""

    repository = TaskRepository(tmp_path)
    with allure.step("Import the dataset"):
        for record in RECORDS["projects"]:
            repository.create_project(ProjectDocument.model_validate(record))
        for record in RECORDS["tags"]:
            repository.create_tag(TagDocument.model_validate(record))
        for record in RECORDS["tasks"]:
            repository.create(TaskDocument.model_validate(record))
        for record in RECORDS["subtasks"]:
            repository.create_subtask(TaskSubtaskDocument.model_validate(record))
        for record in RECORDS["comments"]:
            repository.create_comment(TaskCommentDocument.model_validate(record))
    with allure.step("Read every owner back"):
        for owner in DATASET["owners"]:
            expected = DATASET["expected_counts"][owner]
            projects = repository.list_projects_for_owner(owner_id=owner)
            tags = repository.list_tags_for_owner(owner_id=owner)
            tasks = repository.list_for_owner(owner_id=owner)
            assert (len(projects), len(tags), len(tasks)) == (
                expected["projects"],
                expected["tags"],
                expected["tasks"],
            )
            stored = {t.id: t.model_dump(mode="json") for t in tasks}
            for record in RECORDS["tasks"]:
                if record["owner_id"] == owner:
                    assert stored[record["id"]] == record
            subtasks = [
                s
                for t in tasks
                for s in repository.list_subtasks(owner_id=owner, task_id=t.id)
            ]
            comments = [
                c
                for t in tasks
                for c in repository.list_comments(owner_id=owner, task_id=t.id)
            ]
            assert len(subtasks) == expected["subtasks"]
            assert len(comments) == expected["comments"]


# ------------------------------------------------------------- web presentation
def test_026_FR_002_web_vector_file_is_versioned_and_source_linked() -> None:
    """Rule version, unique ids and an existing source test for every case."""

    with allure.step("Check the header"):
        assert WEB["schema"] == "brainbuddy-web-presentation-vectors/v1"
        assert WEB["rule_version"] == "smart-add-web/1"
    with allure.step("Check ids and sources"):
        cases = WEB["parse"] + WEB["suggestions"] + WEB["apply_suggestion"]
        ids = _ids(cases) + _ids(WEB["name_collision_probes"])
        assert len(ids) == len(set(ids))
        sources: dict[str, str] = {}
        for case in cases:
            path = REPO_ROOT / case["source"]["file"]
            sources.setdefault(case["source"]["file"], path.read_text(encoding="utf-8"))
            title = case["source"]["test"]
            # Titles with a printf placeholder or a "(...)" note cite a family.
            stem = title.split(" (")[0].replace("%s", "")
            assert stem.split("  ")[0] in sources[case["source"]["file"]] or (
                "research finding" in title or "contract" in title
            ), f"{case['id']}: {title!r} is not in {case['source']['file']}"


@pytest.mark.parametrize("case", WEB["parse"], ids=_ids(WEB["parse"]))
def test_026_FR_002_web_payload_is_accepted_by_the_server_exactly_when_valid(
    case: dict[str, Any],
) -> None:
    """``is_valid`` on the web equals the server request model, except as recorded."""

    expect = case["expect"]
    payload = {
        "title": expect["clean_title"],
        "project": expect["project"],
        "tags": expect["tags"],
    }
    with allure.step("Validate the web payload with the server request model"):
        try:
            SmartAddTaskCreateRequest.model_validate(payload)
            server_accepts = True
        except ValidationError:
            server_accepts = False
    divergence = case.get("divergence", {}).get("fields", {})
    with allure.step("Compare with the web verdict"):
        if "is_valid" in divergence:
            assert server_accepts is divergence["is_valid"]
            assert expect["is_valid"] is not server_accepts
        else:
            assert server_accepts is expect["is_valid"], case["id"]


def test_026_FR_002_recorded_divergences_are_real_on_the_server() -> None:
    """The sharp s and astral-length divergences are what the server does."""

    divergent = [case for case in WEB["parse"] if "divergence" in case]
    assert len(divergent) == 4
    with allure.step("Sharp s resolves to the stored 'ss' tag by the server key"):
        sharp = next(c for c in divergent if c["input"] == "Plan #ß")
        stored = WEB["fixtures"][sharp["fixture"]]["tags"][0]
        assert normalize_task_name(
            display_tag_name("ß"), strip_tag_prefix=True
        ) == normalize_task_name(stored["name"], strip_tag_prefix=True)
        assert sharp["expect"]["tags"] == [{"name": "ß"}]
        assert sharp["divergence"]["fields"]["tags"] == [{"id": stored["id"]}]
    with allure.step("300 emoji is within the scalar limit but over the UTF-16 one"):
        long_title = next(
            c for c in divergent if "is_valid" in c["divergence"]["fields"]
        )["input"]
        assert len(long_title) == 300
        assert len(long_title.encode("utf-16-le")) // 2 == 600
    with allure.step("Removing a token by scalar leaves the title the divergence says"):
        for case in (
            c for c in divergent if "clean_title" in c["divergence"]["fields"]
        ):
            # Delete the token (sigil + name) and collapse whitespace, in Python's
            # scalar-indexed strings, which is the shared rule.
            sigil_at = max(case["input"].rfind("#"), case["input"].rfind("@"))
            end = case["input"].find(" ", sigil_at)
            end = len(case["input"]) if end == -1 else end
            cleaned = " ".join((case["input"][:sigil_at] + case["input"][end:]).split())
            assert cleaned == case["divergence"]["fields"]["clean_title"]
            assert case["expect"]["clean_title"] != cleaned


@pytest.mark.parametrize(
    "probe", WEB["name_collision_probes"], ids=_ids(WEB["name_collision_probes"])
)
def test_026_FR_002_name_collision_probe_matches_the_server_key(
    probe: dict[str, Any],
) -> None:
    """A typed tag collides with a stored one exactly as the server keys say."""

    with allure.step("Compare the server keys"):
        server = normalize_task_name(
            probe["stored_tag"], strip_tag_prefix=True
        ) == normalize_task_name(
            display_tag_name(probe["typed_tag"]), strip_tag_prefix=True
        )
        assert server is probe["server_collides"]
        assert probe["agrees"] is (probe["web_collides"] is server)


def test_026_FR_002_web_server_disagreements_are_frozen_findings() -> None:
    """The probes include real disagreements, so the finding cannot vanish silently."""

    disagreements = [p["id"] for p in WEB["name_collision_probes"] if not p["agrees"]]
    assert disagreements == [
        "WP-K-001",
        "WP-K-003",
        "WP-K-008",
        "WP-K-009",
        "WP-K-010",
    ]
