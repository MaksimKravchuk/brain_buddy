from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta

import pytest

from app.repositories.feature_flag import FlagMode, RuntimeOverlay
from app.utils.time import utcnow


def _enable_crt(client) -> None:
    client.app.state.container.feature_flag_service.set_mode(
        "crt_canvas", "on", operator_id="test-operator"
    )


def _create_tree(client, *, name: str) -> dict:
    keys = {
        "First tree": "123e4567-e89b-12d3-a456-426614174099",
        "Second tree": "123e4567-e89b-12d3-a456-426614174098",
    }
    response = client.post(
        "/api/crt/trees",
        json={"name": name},
        headers={
            "Idempotency-Key": keys.get(name, "123e4567-e89b-12d3-a456-426614174097")
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_019_FR_001_effective_crt_exposure_probe_is_content_free(api_client) -> None:
    """An effective owner receives only a successful, bodyless exposure probe."""
    _enable_crt(api_client)

    response = api_client.get("/api/crt/exposure")

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers.get("X-Correlation-ID")
    assert "CRT" not in response.text


def test_019_FR_001_disabled_crt_facade_returns_content_free_reason(api_client) -> None:
    response = api_client.get("/api/crt/trees")

    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "crt_canvas_disabled"
    assert "nodes" not in response.text
    assert response.headers.get("X-Correlation-ID")


def test_019_FR_001_degraded_flag_store_returns_unavailable_reason(
    api_client, monkeypatch
) -> None:
    monkeypatch.setattr(
        api_client.app.state.container.feature_flag_repo,
        "read",
        lambda: RuntimeOverlay(degraded=True, flags={}),
    )

    response = api_client.get("/api/crt/exposure")

    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "feature_flag_unavailable"
    assert "nodes" not in response.text
    assert response.headers.get("X-Correlation-ID")


def test_019_FR_001_crt_facade_rejects_malformed_correlation_id(api_client) -> None:
    _enable_crt(api_client)

    response = api_client.get(
        "/api/crt/exposure", headers={"X-Correlation-ID": "not-a-uuid"}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["reason"] == "invalid_correlation_id"
    assert response.headers.get("X-Correlation-ID") == "not-a-uuid"


def test_019_FR_001_crt_facade_retains_valid_correlation_id(api_client) -> None:
    _enable_crt(api_client)
    correlation_id = "123e4567-e89b-12d3-a456-426614174000"

    response = api_client.get(
        "/api/crt/exposure", headers={"X-Correlation-ID": correlation_id}
    )

    assert response.status_code == 204
    assert response.headers.get("X-Correlation-ID") == correlation_id


def test_019_FR_001_crt_facade_generates_canonical_correlation_id(api_client) -> None:
    _enable_crt(api_client)

    response = api_client.get("/api/crt/exposure")

    correlation_id = response.headers["X-Correlation-ID"]
    assert str(uuid.UUID(correlation_id)) == correlation_id


def test_019_FR_002_crt_reads_are_owner_scoped_and_read_only(second_api_client) -> None:
    client_a, client_b = second_api_client
    _enable_crt(client_a)
    tree_response = client_a.post("/api/trees", json={"name": "Owner A private tree"})
    assert tree_response.status_code == 201
    tree_id = tree_response.json()["id"]

    listed_a = client_a.get("/api/crt/trees")
    assert listed_a.status_code == 200
    assert [item["id"] for item in listed_a.json()] == [tree_id]

    loaded_a = client_a.get(f"/api/crt/trees/{tree_id}")
    assert loaded_a.status_code == 200
    assert loaded_a.json()["name"] == "Owner A private tree"

    wrong_owner = client_b.get(f"/api/crt/trees/{tree_id}")
    assert wrong_owner.status_code == 404
    assert "Owner A private tree" not in wrong_owner.text
    assert wrong_owner.json()["detail"]["resource"] == "Tree"


def test_019_FR_002_selected_crt_routes_gate_before_tree_reads(
    second_api_client, monkeypatch
) -> None:
    """Selected users can read CRT while denied users get content-free 404s."""
    client_a, client_b = second_api_client
    container = client_a.app.state.container
    owner_a = client_a.get("/api/account").json()["id"]
    container.feature_flag_service.set_mode(
        "crt_canvas", FlagMode.SELECTED_USERS, operator_id="test-operator"
    )
    container.feature_flag_service.add_selected_user(
        "crt_canvas", operator_id="test-operator", account_id=owner_a
    )
    created = client_a.post("/api/trees", json={"name": "Selected CRT tree"})
    assert created.status_code == 201
    tree_id = created.json()["id"]

    assert client_a.get("/api/crt/exposure").status_code == 204
    assert client_a.get("/api/crt/trees").status_code == 200
    selected_detail = client_a.get(f"/api/crt/trees/{tree_id}")
    assert selected_detail.status_code == 200
    assert selected_detail.json()["name"] == "Selected CRT tree"

    def unexpected_list_read(*, owner_id: str):
        raise AssertionError(f"denied CRT list read for {owner_id}")

    def unexpected_tree_read(tree_id: str, *, owner_id: str):
        raise AssertionError(f"denied CRT detail read for {tree_id}/{owner_id}")

    monkeypatch.setattr(container.tree_service, "list_trees", unexpected_list_read)
    monkeypatch.setattr(
        container.tree_service, "get_tree_for_owner", unexpected_tree_read
    )
    denied_exposure = client_b.get("/api/crt/exposure")
    denied_list = client_b.get("/api/crt/trees")
    denied_detail = client_b.get(f"/api/crt/trees/{tree_id}")

    for response in (denied_exposure, denied_list, denied_detail):
        assert response.status_code == 404
        assert response.json()["detail"]["reason"] == "crt_canvas_disabled"
        assert "Selected CRT tree" not in response.text


def test_019_FR_020_crt_facade_requires_authentication(anonymous_api_client) -> None:
    response = anonymous_api_client.get("/api/crt/exposure")

    assert response.status_code == 401
    assert response.headers.get("X-Correlation-ID")


def test_019_FR_019_create_replays_the_exact_committed_response(api_client) -> None:
    _enable_crt(api_client)
    key = "123e4567-e89b-12d3-a456-426614174001"

    first = api_client.post(
        "/api/crt/trees", json={"name": "Replay me"}, headers={"Idempotency-Key": key}
    )
    replay = api_client.post(
        "/api/crt/trees", json={"name": "Replay me"}, headers={"Idempotency-Key": key}
    )

    assert first.status_code == 201
    assert replay.status_code == first.status_code
    assert replay.json() == first.json()
    assert api_client.get("/api/crt/trees").json() == [
        {
            "id": first.json()["id"],
            "name": "Replay me",
            "updated_at": first.json()["metadata"]["updated_at"],
            "owner_id": first.json()["owner_id"],
        }
    ]


def test_019_FR_019_reusing_create_key_with_different_fingerprint_conflicts(
    api_client,
) -> None:
    _enable_crt(api_client)
    key = "123e4567-e89b-12d3-a456-426614174002"

    first = api_client.post(
        "/api/crt/trees", json={"name": "Original"}, headers={"Idempotency-Key": key}
    )
    conflict = api_client.post(
        "/api/crt/trees", json={"name": "Changed"}, headers={"Idempotency-Key": key}
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "idempotency_conflict"
    assert [item["name"] for item in api_client.get("/api/crt/trees").json()] == [
        "Original"
    ]


def test_019_FR_019_pending_create_retries_forward_after_crash_before_tree_write(
    api_client, monkeypatch
) -> None:
    _enable_crt(api_client)
    service = api_client.app.state.container.crt_command_service
    original_create = service.tree_service.persist_prepared_create_tree
    calls: list[str] = []

    def crash_before_tree_write(*args, **kwargs):
        calls.append("create")
        if len(calls) == 1:
            raise RuntimeError("simulated crash before CRT tree write")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_create_tree", crash_before_tree_write
    )
    key = "123e4567-e89b-12d3-a456-426614174014"
    payload = {"name": "Recover create"}

    with pytest.raises(RuntimeError, match="before CRT tree write"):
        api_client.post(
            "/api/crt/trees", json=payload, headers={"Idempotency-Key": key}
        )

    owner_id = api_client.get("/api/auth/me").json()["id"]
    key_digest = service._key_digest(key)
    pending = service.command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert pending is not None
    assert pending.state == "pending"

    conflict = api_client.post(
        "/api/crt/trees",
        json={"name": "Different create"},
        headers={"Idempotency-Key": key},
    )
    recovered = api_client.post(
        "/api/crt/trees", json=payload, headers={"Idempotency-Key": key}
    )
    replay = api_client.post(
        "/api/crt/trees", json=payload, headers={"Idempotency-Key": key}
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "idempotency_conflict"
    assert recovered.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == recovered.json()
    assert calls == ["create", "create"]
    assert [item["name"] for item in api_client.get("/api/crt/trees").json()] == [
        "Recover create"
    ]


def test_019_FR_019_pending_update_retries_forward_after_crash_before_tree_write(
    api_client, monkeypatch
) -> None:
    _enable_crt(api_client)
    created = api_client.post(
        "/api/crt/trees",
        json={"name": "Before update"},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174015"},
    )
    tree = created.json()
    payload = {
        "name": "Recover update",
        "schema_version": tree["schema_version"],
        "metadata": tree["metadata"],
        "nodes": tree["nodes"],
        "relations": tree["relations"],
        "owner_id": tree["owner_id"],
        "expected_revision": tree["revision"],
    }
    service = api_client.app.state.container.crt_command_service
    original_update = service.tree_service.persist_prepared_update_tree
    calls: list[str] = []

    def crash_before_tree_write(*args, **kwargs):
        calls.append("update")
        if len(calls) == 1:
            raise RuntimeError("simulated crash before CRT tree write")
        return original_update(*args, **kwargs)

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_update_tree", crash_before_tree_write
    )
    key = "123e4567-e89b-12d3-a456-426614174016"

    with pytest.raises(RuntimeError, match="before CRT tree write"):
        api_client.put(
            f"/api/crt/trees/{tree['id']}",
            json=payload,
            headers={"Idempotency-Key": key},
        )

    owner_id = api_client.get("/api/auth/me").json()["id"]
    pending = service.command_repo.get(
        owner_id=owner_id, key_digest=service._key_digest(key)
    )
    assert pending is not None
    assert pending.state == "pending"

    conflict = api_client.put(
        f"/api/crt/trees/{tree['id']}",
        json={**payload, "name": "Different update"},
        headers={"Idempotency-Key": key},
    )
    recovered = api_client.put(
        f"/api/crt/trees/{tree['id']}",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    replay = api_client.put(
        f"/api/crt/trees/{tree['id']}",
        json=payload,
        headers={"Idempotency-Key": key},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "idempotency_conflict"
    assert recovered.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == recovered.json()
    assert calls == ["update", "update"]
    assert api_client.get(f"/api/crt/trees/{tree['id']}").json()["name"] == (
        "Recover update"
    )


def test_019_FR_019_pending_update_with_unknown_marker_fails_closed(
    api_client, monkeypatch
) -> None:
    _enable_crt(api_client)
    created = api_client.post(
        "/api/crt/trees",
        json={"name": "Unknown marker base"},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174018"},
    )
    tree = created.json()
    service = api_client.app.state.container.crt_command_service
    stored = service.tree_service.get_tree_for_owner(
        tree["id"], owner_id=api_client.get("/api/auth/me").json()["id"]
    )
    service.tree_service.tree_repo.save(
        stored.model_copy(update={"last_command_id": "f" * 64}, deep=True)
    )
    payload = {
        "name": "Should not apply",
        "schema_version": tree["schema_version"],
        "metadata": tree["metadata"],
        "nodes": tree["nodes"],
        "relations": tree["relations"],
        "owner_id": tree["owner_id"],
        "expected_revision": tree["revision"],
    }
    original_update = service.tree_service.persist_prepared_update_tree

    def crash_before_tree_write(*args, **kwargs):
        raise RuntimeError("simulated crash before CRT tree write")

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_update_tree", crash_before_tree_write
    )
    key = "123e4567-e89b-12d3-a456-426614174019"

    with pytest.raises(RuntimeError, match="before CRT tree write"):
        api_client.put(
            f"/api/crt/trees/{tree['id']}",
            json=payload,
            headers={"Idempotency-Key": key},
        )

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_update_tree", original_update
    )
    retry = api_client.put(
        f"/api/crt/trees/{tree['id']}",
        json=payload,
        headers={"Idempotency-Key": key},
    )

    assert retry.status_code == 409


def test_019_FR_019_tree_write_before_commit_reconciles_exactly(
    api_client, monkeypatch
) -> None:
    _enable_crt(api_client)
    service = api_client.app.state.container.crt_command_service
    original_commit = service.command_repo.commit
    commit_calls: list[str] = []

    def crash_after_tree_write(*args, **kwargs):
        commit_calls.append("commit")
        if len(commit_calls) == 1:
            raise RuntimeError("simulated crash after CRT tree write")
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(service.command_repo, "commit", crash_after_tree_write)
    key = "123e4567-e89b-12d3-a456-426614174017"
    payload = {"name": "Reconcile committed tree"}

    with pytest.raises(RuntimeError, match="after CRT tree write"):
        api_client.post(
            "/api/crt/trees", json=payload, headers={"Idempotency-Key": key}
        )

    recovered = api_client.post(
        "/api/crt/trees", json=payload, headers={"Idempotency-Key": key}
    )
    replay = api_client.post(
        "/api/crt/trees", json=payload, headers={"Idempotency-Key": key}
    )

    assert recovered.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == recovered.json()
    assert commit_calls == ["commit", "commit"]


def test_019_FR_019_update_key_is_scoped_to_tree_resource(api_client) -> None:
    _enable_crt(api_client)
    first_tree = _create_tree(api_client, name="First tree")
    second_tree = _create_tree(api_client, name="Second tree")
    key = "123e4567-e89b-12d3-a456-426614174020"

    def payload(tree: dict, name: str, *, fingerprint_tree: dict) -> dict:
        return {
            "name": name,
            "schema_version": fingerprint_tree["schema_version"],
            "metadata": fingerprint_tree["metadata"],
            "nodes": fingerprint_tree["nodes"],
            "relations": fingerprint_tree["relations"],
            "owner_id": fingerprint_tree["owner_id"],
            "expected_revision": tree["revision"],
        }

    first = api_client.put(
        f"/api/crt/trees/{first_tree['id']}",
        json=payload(first_tree, "First updated", fingerprint_tree=first_tree),
        headers={"Idempotency-Key": key},
    )
    second = api_client.put(
        f"/api/crt/trees/{second_tree['id']}",
        json=payload(second_tree, "First updated", fingerprint_tree=first_tree),
        headers={"Idempotency-Key": key},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 409
    assert second.json()["detail"]["reason"] == "idempotency_conflict"
    assert api_client.get(f"/api/crt/trees/{second_tree['id']}").json()["name"] == (
        "Second tree"
    )


def test_019_FR_019_update_replay_precedes_live_revision_checks(api_client) -> None:
    _enable_crt(api_client)
    create = api_client.post(
        "/api/crt/trees",
        json={"name": "Before"},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174003"},
    )
    tree = create.json()
    tree_id = tree["id"]
    first_key = "123e4567-e89b-12d3-a456-426614174004"
    update_payload = {
        "name": "First",
        "schema_version": tree["schema_version"],
        "metadata": tree["metadata"],
        "nodes": tree["nodes"],
        "relations": tree["relations"],
        "owner_id": tree["owner_id"],
        "expected_revision": tree["revision"],
    }
    first_update = api_client.put(
        f"/api/crt/trees/{tree_id}",
        json=update_payload,
        headers={"Idempotency-Key": first_key},
    )
    second = first_update.json()
    later = api_client.put(
        f"/api/crt/trees/{tree_id}",
        json={
            **update_payload,
            "name": "Later",
            "expected_revision": second["revision"],
        },
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174005"},
    )
    replay = api_client.put(
        f"/api/crt/trees/{tree_id}",
        json=update_payload,
        headers={"Idempotency-Key": first_key},
    )

    assert first_update.status_code == 200
    assert later.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first_update.json()
    assert api_client.get(f"/api/crt/trees/{tree_id}").json()["name"] == "Later"


def test_019_FR_019_stale_revision_detail_matches_crt_contract(api_client) -> None:
    _enable_crt(api_client)
    create = api_client.post(
        "/api/crt/trees",
        json={"name": "Stale"},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174006"},
    )
    tree = create.json()
    tree_id = tree["id"]
    update = {
        "name": "Fresh",
        "schema_version": tree["schema_version"],
        "metadata": tree["metadata"],
        "nodes": tree["nodes"],
        "relations": tree["relations"],
        "owner_id": tree["owner_id"],
        "expected_revision": tree["revision"],
    }
    assert (
        api_client.put(
            f"/api/crt/trees/{tree_id}",
            json=update,
            headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174007"},
        ).status_code
        == 200
    )

    stale = api_client.put(
        f"/api/crt/trees/{tree_id}",
        json=update,
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174008"},
    )

    assert stale.status_code == 409
    assert (
        stale.json()["message"]
        == "This tree has newer changes; review the conflict before saving."
    )
    assert stale.json()["detail"]["reason"] == "stale_revision"
    assert stale.json()["detail"]["tree_id"] == tree_id


def test_019_FR_019_schema_versions_are_rejected_before_crt_create_mutation(
    api_client,
) -> None:
    _enable_crt(api_client)
    headers = {"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174009"}

    unsupported = api_client.post(
        "/api/crt/trees",
        json={
            "name": "Unsupported",
            "metadata": {
                "version": 2,
                "created_at": "2026-09-20T00:00:00Z",
                "updated_at": "2026-09-20T00:00:00Z",
            },
        },
        headers=headers,
    )
    mismatch = api_client.post(
        "/api/crt/trees",
        json={
            "name": "Mismatch",
            "schema_version": 1,
            "metadata": {
                "version": 2,
                "created_at": "2026-09-20T00:00:00Z",
                "updated_at": "2026-09-20T00:00:00Z",
            },
        },
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174010"},
    )

    assert unsupported.status_code == 400
    assert unsupported.json()["detail"]["reason"] == "unsupported_schema_version"
    assert mismatch.status_code == 400
    assert mismatch.json()["detail"]["reason"] == "schema_version_mismatch"
    assert api_client.get("/api/crt/trees").json() == []


def test_019_FR_019_schema_versions_are_rejected_before_crt_update_mutation(
    api_client,
) -> None:
    _enable_crt(api_client)
    create = api_client.post(
        "/api/crt/trees",
        json={"name": "Schema"},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174011"},
    )
    tree = create.json()
    tree_id = tree["id"]

    unsupported = api_client.put(
        f"/api/crt/trees/{tree_id}",
        json={
            "name": tree["name"],
            "expected_revision": tree["revision"],
            "schema_version": 2,
            "metadata": {**tree["metadata"], "version": 2},
            "nodes": tree["nodes"],
            "relations": tree["relations"],
            "owner_id": tree["owner_id"],
        },
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174012"},
    )
    mismatch = api_client.put(
        f"/api/crt/trees/{tree_id}",
        json={
            "name": tree["name"],
            "expected_revision": tree["revision"],
            "schema_version": 1,
            "metadata": {**tree["metadata"], "version": 2},
            "nodes": tree["nodes"],
            "relations": tree["relations"],
            "owner_id": tree["owner_id"],
        },
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174013"},
    )

    assert unsupported.status_code == 400
    assert unsupported.json()["detail"]["reason"] == "unsupported_schema_version"
    assert mismatch.status_code == 400
    assert mismatch.json()["detail"]["reason"] == "schema_version_mismatch"
    assert api_client.get(f"/api/crt/trees/{tree_id}").json() == tree


def test_crt_idempotency_fingerprint_ignores_untrusted_owner_fields(api_client) -> None:
    """Owner fields are server-owned and cannot alter a replay fingerprint."""
    _enable_crt(api_client)
    key = "123e4567-e89b-12d3-a456-426614174021"
    metadata = {
        "version": 1,
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
    }

    first = api_client.post(
        "/api/crt/trees",
        json={
            "name": "Owner-safe replay",
            "owner_id": "spoof-a",
            "metadata": {**metadata, "owner_id": "spoof-a"},
        },
        headers={"Idempotency-Key": key},
    )
    replay = api_client.post(
        "/api/crt/trees",
        json={
            "name": "Owner-safe replay",
            "owner_id": "spoof-b",
            "metadata": {**metadata, "owner_id": "spoof-b"},
        },
        headers={"Idempotency-Key": key},
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()


def test_pending_crt_command_blocks_a_different_key_for_same_tree(
    api_client, monkeypatch
) -> None:
    """A pending command cannot be bypassed by submitting another key."""
    _enable_crt(api_client)
    created = api_client.post(
        "/api/crt/trees",
        json={"name": "Pending guard"},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174022"},
    )
    tree = created.json()
    service = api_client.app.state.container.crt_command_service
    original_update = service.tree_service.persist_prepared_update_tree

    def crash_once(*args, **kwargs):
        monkeypatch.setattr(
            service.tree_service, "persist_prepared_update_tree", original_update
        )
        raise RuntimeError("pending command")

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_update_tree", crash_once
    )
    payload = {
        "name": "Pending update",
        "schema_version": tree["schema_version"],
        "metadata": tree["metadata"],
        "nodes": tree["nodes"],
        "relations": tree["relations"],
        "owner_id": tree["owner_id"],
        "expected_revision": tree["revision"],
    }
    with pytest.raises(RuntimeError, match="pending command"):
        api_client.put(
            f"/api/crt/trees/{tree['id']}",
            json=payload,
            headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174023"},
        )

    bypass = api_client.put(
        f"/api/crt/trees/{tree['id']}",
        json={**payload, "name": "Bypassed"},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174024"},
    )

    assert bypass.status_code == 409
    assert bypass.json()["detail"]["reason"] == "pending_command"
    assert api_client.get(f"/api/crt/trees/{tree['id']}").json()["name"] == tree["name"]


def test_expired_crt_receipt_requires_explicit_reconciliation(api_client) -> None:
    """A stale receipt is never replayed after its exact-replay window."""
    _enable_crt(api_client)
    key = "123e4567-e89b-12d3-a456-426614174025"
    first = api_client.post(
        "/api/crt/trees",
        json={"name": "Expired replay"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201
    service = api_client.app.state.container.crt_command_service
    expired_at = (utcnow() - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(service.command_repo.db_path) as connection:
        connection.execute(
            "UPDATE crt_command_receipts SET expires_at = ? WHERE owner_id = ? AND key_digest = ?",
            (
                expired_at,
                api_client.get("/api/auth/me").json()["id"],
                service._key_digest(key),
            ),
        )

    replay = api_client.post(
        "/api/crt/trees",
        json={"name": "Expired replay"},
        headers={"Idempotency-Key": key},
    )

    assert replay.status_code == 409
    assert replay.json()["detail"]["reason"] == "idempotency_receipt_expired"


def test_swept_crt_receipt_keeps_same_key_fail_closed(api_client) -> None:
    """Retention sweep redacts a receipt without reopening its command key."""
    _enable_crt(api_client)
    key = "123e4567-e89b-12d3-a456-426614174027"
    first = api_client.post(
        "/api/crt/trees",
        json={"name": "Swept replay"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201
    service = api_client.app.state.container.crt_command_service
    owner_id = api_client.get("/api/auth/me").json()["id"]
    expired_at = utcnow() - timedelta(seconds=1)
    with sqlite3.connect(service.command_repo.db_path) as connection:
        connection.execute(
            "UPDATE crt_command_receipts SET expires_at = ? WHERE owner_id = ? AND key_digest = ?",
            (expired_at.isoformat(), owner_id, service._key_digest(key)),
        )

    assert service.command_repo.purge_expired(now=utcnow()) == 1
    reused = api_client.post(
        "/api/crt/trees",
        json={"name": "Swept replay"},
        headers={"Idempotency-Key": key},
    )

    assert reused.status_code == 409
    assert reused.json()["detail"]["reason"] == "idempotency_receipt_expired"


def test_malformed_committed_crt_receipt_fails_closed(api_client) -> None:
    """Corrupt replay content does not become a successful mutation response."""
    _enable_crt(api_client)
    key = "123e4567-e89b-12d3-a456-426614174026"
    first = api_client.post(
        "/api/crt/trees",
        json={"name": "Corrupt replay"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201
    service = api_client.app.state.container.crt_command_service
    owner_id = api_client.get("/api/auth/me").json()["id"]
    with sqlite3.connect(service.command_repo.db_path) as connection:
        connection.execute(
            "UPDATE crt_command_receipts SET response_json = ? WHERE owner_id = ? AND key_digest = ?",
            ("not-json", owner_id, service._key_digest(key)),
        )

    replay = api_client.post(
        "/api/crt/trees",
        json={"name": "Corrupt replay"},
        headers={"Idempotency-Key": key},
    )

    assert replay.status_code == 409
    assert replay.json()["detail"]["reason"] == "idempotency_receipt_unavailable"
