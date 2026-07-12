"""API integration tests for vNext endpoints (ADR-0001).

Tests the full capture -> review -> promote flow through the HTTP API,
including owner scoping and state machine invariants.
"""

from __future__ import annotations


class TestCaptureSessionAPI:
    def test_create_text_capture_session(self, api_client):
        resp = api_client.post(
            "/api/capture-sessions",
            json={"text": "Fix the bug\nDeploy to staging\nWhy is API slow?"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["session"]["status"] == "ready"
        assert len(data["captures"]) == 3
        assert data["captures"][0]["review_state"] == "proposed"

    def test_get_capture_session(self, api_client):
        create = api_client.post(
            "/api/capture-sessions",
            json={"text": "A task"},
        )
        session_id = create.json()["session"]["id"]
        resp = api_client.get(f"/api/capture-sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["session"]["id"] == session_id

    def test_list_captures(self, api_client):
        api_client.post(
            "/api/capture-sessions",
            json={"text": "Task one\nTask two"},
        )
        resp = api_client.get("/api/captures")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_apply_decision(self, api_client):
        create = api_client.post(
            "/api/capture-sessions",
            json={"text": "A task"},
        )
        capture_id = create.json()["captures"][0]["id"]
        resp = api_client.post(
            f"/api/captures/{capture_id}/decisions",
            json={"action": "approve"},
        )
        assert resp.status_code == 200
        assert resp.json()["review_state"] == "approved"

    def test_edit_decision(self, api_client):
        create = api_client.post(
            "/api/capture-sessions",
            json={"text": "Original text"},
        )
        capture_id = create.json()["captures"][0]["id"]
        resp = api_client.post(
            f"/api/captures/{capture_id}/decisions",
            json={"action": "edit", "new_text": "Updated text"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["review_state"] == "approved"
        assert data["current_text"] == "Updated text"

    def test_delete_is_terminal(self, api_client):
        create = api_client.post(
            "/api/capture-sessions",
            json={"text": "To delete"},
        )
        capture_id = create.json()["captures"][0]["id"]
        api_client.post(
            f"/api/captures/{capture_id}/decisions",
            json={"action": "delete"},
        )
        # Second action should fail
        resp = api_client.post(
            f"/api/captures/{capture_id}/decisions",
            json={"action": "approve"},
        )
        assert resp.status_code == 400

    def test_auth_required(self, anonymous_api_client):
        resp = anonymous_api_client.post(
            "/api/capture-sessions",
            json={"text": "test"},
        )
        assert resp.status_code == 401

    def test_cross_owner_isolation(self, second_api_client):
        client_a, client_b = second_api_client
        create = client_a.post(
            "/api/capture-sessions",
            json={"text": "Owner A's task"},
        )
        capture_id = create.json()["captures"][0]["id"]
        # Owner B should get 404
        resp = client_b.post(
            f"/api/captures/{capture_id}/decisions",
            json={"action": "approve"},
        )
        assert resp.status_code == 404


class TestWeeklyReviewAPI:
    def test_start_and_complete_review(self, api_client):
        # Create captures
        create = api_client.post(
            "/api/capture-sessions",
            json={"text": "Task one\nTask two"},
        )
        captures = create.json()["captures"]

        # Start review
        resp = api_client.post("/api/weekly-reviews")
        assert resp.status_code == 200
        review = resp.json()
        assert review["review"]["status"] == "open"
        assert len(review["review"]["item_ids"]) == 2

        review_id = review["review"]["id"]

        # Record outcomes
        api_client.post(
            f"/api/weekly-reviews/{review_id}/items/{captures[0]['id']}/outcomes",
            json={"action": "keep"},
        )
        api_client.post(
            f"/api/weekly-reviews/{review_id}/items/{captures[1]['id']}/outcomes",
            json={"action": "defer"},
        )

        # Complete
        resp = api_client.post(f"/api/weekly-reviews/{review_id}/complete")
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["total_items"] == 2
        assert summary["kept"] == 1
        assert summary["deferred"] == 1

    def test_complete_with_uncovered_items_fails(self, api_client):
        create = api_client.post(
            "/api/capture-sessions",
            json={"text": "Task one\nTask two"},
        )
        captures = create.json()["captures"]

        resp = api_client.post("/api/weekly-reviews")
        review_id = resp.json()["review"]["id"]

        # Only one outcome
        api_client.post(
            f"/api/weekly-reviews/{review_id}/items/{captures[0]['id']}/outcomes",
            json={"action": "keep"},
        )

        resp = api_client.post(f"/api/weekly-reviews/{review_id}/complete")
        assert resp.status_code == 400

    def test_resume_open_review(self, api_client):
        api_client.post(
            "/api/capture-sessions",
            json={"text": "Task one"},
        )
        resp1 = api_client.post("/api/weekly-reviews")
        resp2 = api_client.post("/api/weekly-reviews")
        assert resp1.json()["review"]["id"] == resp2.json()["review"]["id"]

    def test_completion_is_idempotent(self, api_client):
        create = api_client.post(
            "/api/capture-sessions",
            json={"text": "Task one"},
        )
        capture_id = create.json()["captures"][0]["id"]

        resp = api_client.post("/api/weekly-reviews")
        review_id = resp.json()["review"]["id"]

        api_client.post(
            f"/api/weekly-reviews/{review_id}/items/{capture_id}/outcomes",
            json={"action": "defer"},
        )

        resp1 = api_client.post(f"/api/weekly-reviews/{review_id}/complete")
        resp2 = api_client.post(f"/api/weekly-reviews/{review_id}/complete")
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    def test_list_reviews(self, api_client):
        api_client.post(
            "/api/capture-sessions",
            json={"text": "Task one"},
        )
        api_client.post("/api/weekly-reviews")
        resp = api_client.get("/api/weekly-reviews")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_promote_to_crt_outcome(self, api_client):
        create = api_client.post(
            "/api/capture-sessions",
            json={"text": "Complex problem to solve"},
        )
        capture_id = create.json()["captures"][0]["id"]

        resp = api_client.post("/api/weekly-reviews")
        review_id = resp.json()["review"]["id"]

        resp = api_client.post(
            f"/api/weekly-reviews/{review_id}/items/{capture_id}/outcomes",
            json={"action": "promote_to_crt"},
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "promote_to_crt"


class TestCandidateAndPromotionAPI:
    def test_create_and_promote_candidate(self, api_client):
        create = api_client.post(
            "/api/problem-candidates",
            json={
                "title": "Recurring issue",
                "context": "Happens every week",
                "source_capture_ids": ["cap_1"],
            },
        )
        assert create.status_code == 201
        candidate_id = create.json()["id"]

        resp = api_client.post(
            f"/api/problem-candidates/{candidate_id}/promotions"
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "succeeded"
        assert data["tree_id"] is not None

    def test_list_candidates(self, api_client):
        api_client.post(
            "/api/problem-candidates",
            json={"title": "Problem A"},
        )
        api_client.post(
            "/api/problem-candidates",
            json={"title": "Problem B"},
        )
        resp = api_client.get("/api/problem-candidates")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestEvidenceResultAPI:
    def test_record_result(self, api_client):
        resp = api_client.post(
            "/api/results",
            json={
                "source": "manual",
                "kind": "evidence",
                "title": "Test evidence",
                "atomic_capture_ids": ["cap_1"],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Test evidence"

    def test_get_capture_results(self, api_client):
        api_client.post(
            "/api/results",
            json={
                "source": "manual",
                "kind": "evidence",
                "title": "Evidence for cap_1",
                "atomic_capture_ids": ["cap_1"],
            },
        )
        resp = api_client.get("/api/captures/cap_1/results")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
