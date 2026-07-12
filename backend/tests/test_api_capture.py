"""API integration tests for the vNext capture workflow.

Tests the full HTTP API: session creation, decisions, routing, and
cross-owner isolation. Uses the authenticated TestClient fixture.
"""

from __future__ import annotations


def _signup(client, invite_code: str, email: str, password: str) -> dict:
    """Helper to sign up and return auth response."""
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "invite_code": invite_code},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCaptureSessionAPI:
    def test_text_capture_full_flow(self, api_client) -> None:
        """Submit text, get session, approve capture, route to external tracker."""
        # Submit text capture.
        resp = api_client.post(
            "/api/capture-sessions",
            json={
                "text": "Need to buy groceries. What is the meaning of life?",
                "consent": {"external_processing_allowed": False},
            },
        )
        assert resp.status_code == 202
        session = resp.json()
        assert session["status"] == "ready"
        assert len(session["atomic_capture_ids"]) == 2
        session_id = session["id"]

        # Get session detail.
        detail_resp = api_client.get(f"/api/capture-sessions/{session_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert len(detail["atomic_captures"]) == 2
        assert len(detail["items"]) == 2
        assert detail["items"][0]["review_state"] in ("proposed", "needs_clarification")

    def test_empty_text_capture_fails(self, api_client) -> None:
        resp = api_client.post(
            "/api/capture-sessions",
            json={"text": "", "consent": {"external_processing_allowed": False}},
        )
        assert resp.status_code == 202
        session = resp.json()
        assert session["status"] == "failed"
        assert session["last_error"]["code"] == "EMPTY_TRANSCRIPT"

    def test_retry_failed_session(self, api_client) -> None:
        # Create a failed session.
        resp = api_client.post(
            "/api/capture-sessions",
            json={"text": "", "consent": {"external_processing_allowed": False}},
        )
        session_id = resp.json()["id"]

        # Retry with valid text.
        retry_resp = api_client.post(
            f"/api/capture-sessions/{session_id}/retry",
            json={"text": "Now I have something to say."},
        )
        assert retry_resp.status_code == 202
        retried = retry_resp.json()
        assert retried["status"] == "ready"
        assert len(retried["atomic_capture_ids"]) > 0

    def test_list_captures(self, api_client) -> None:
        # Create a capture.
        api_client.post(
            "/api/capture-sessions",
            json={"text": "Test capture.", "consent": {"external_processing_allowed": False}},
        )

        # List captures.
        resp = api_client.get("/api/captures")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        assert items[0]["review_state"] in ("proposed", "needs_clarification")


class TestCaptureDecisionsAPI:
    def test_approve_and_route_flow(self, api_client) -> None:
        """Full flow: capture -> approve -> route to external tracker."""
        # Capture.
        resp = api_client.post(
            "/api/capture-sessions",
            json={
                "text": "Need to call mom.",
                "consent": {"external_processing_allowed": False},
            },
        )
        session = resp.json()
        capture_id = session["atomic_capture_ids"][0]

        # Get the item to find its revision.
        detail = api_client.get(f"/api/capture-sessions/{session['id']}").json()
        item_revision = detail["items"][0]["revision"]

        # Approve.
        approve_resp = api_client.post(
            f"/api/captures/{capture_id}/decisions",
            json={
                "action": "approve",
                "expected_revision": item_revision,
            },
        )
        assert approve_resp.status_code == 200
        approved = approve_resp.json()
        assert approved["item"]["review_state"] == "approved"

        # Route.
        route_resp = api_client.post(
            f"/api/captures/{capture_id}/routes",
            json={"destination": "external_task_tracker"},
        )
        assert route_resp.status_code == 202
        route_detail = route_resp.json()
        assert route_detail["route"]["status"] == "succeeded"
        assert route_detail["route"]["external_ref"] is not None
        assert route_detail["item"]["review_state"] == "completed"

    def test_edit_capture(self, api_client) -> None:
        resp = api_client.post(
            "/api/capture-sessions",
            json={
                "text": "Original text here.",
                "consent": {"external_processing_allowed": False},
            },
        )
        capture_id = resp.json()["atomic_capture_ids"][0]

        detail = api_client.get(f"/api/capture-sessions/{resp.json()['id']}").json()
        item_revision = detail["items"][0]["revision"]

        edit_resp = api_client.post(
            f"/api/captures/{capture_id}/decisions",
            json={
                "action": "edit",
                "expected_revision": item_revision,
                "new_text": "Edited text",
            },
        )
        assert edit_resp.status_code == 200
        assert edit_resp.json()["item"]["current_text"] == "Edited text"

    def test_delete_capture(self, api_client) -> None:
        resp = api_client.post(
            "/api/capture-sessions",
            json={
                "text": "To be deleted.",
                "consent": {"external_processing_allowed": False},
            },
        )
        capture_id = resp.json()["atomic_capture_ids"][0]

        detail = api_client.get(f"/api/capture-sessions/{resp.json()['id']}").json()
        item_revision = detail["items"][0]["revision"]

        del_resp = api_client.post(
            f"/api/captures/{capture_id}/decisions",
            json={
                "action": "delete",
                "expected_revision": item_revision,
                "reason": "Not needed",
                "avoidance_reason": "duplicate",
            },
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["item"]["review_state"] == "deleted"

    def test_route_before_approval_rejected(self, api_client) -> None:
        resp = api_client.post(
            "/api/capture-sessions",
            json={
                "text": "Unapproved task.",
                "consent": {"external_processing_allowed": False},
            },
        )
        capture_id = resp.json()["atomic_capture_ids"][0]

        route_resp = api_client.post(
            f"/api/captures/{capture_id}/routes",
            json={"destination": "external_task_tracker"},
        )
        assert route_resp.status_code == 400

    def test_stale_revision_returns_409(self, api_client) -> None:
        resp = api_client.post(
            "/api/capture-sessions",
            json={
                "text": "Revision test.",
                "consent": {"external_processing_allowed": False},
            },
        )
        capture_id = resp.json()["atomic_capture_ids"][0]

        # Use wrong revision.
        approve_resp = api_client.post(
            f"/api/captures/{capture_id}/decisions",
            json={
                "action": "approve",
                "expected_revision": 99,
            },
        )
        assert approve_resp.status_code == 409


class TestCrossOwnerIsolation:
    def test_cross_owner_session_404(self, second_api_client) -> None:
        client_a, client_b = second_api_client

        # Client A creates a capture.
        resp_a = client_a.post(
            "/api/capture-sessions",
            json={
                "text": "Owner A's private capture.",
                "consent": {"external_processing_allowed": False},
            },
        )
        session_id = resp_a.json()["id"]

        # Client B tries to access it.
        resp_b = client_b.get(f"/api/capture-sessions/{session_id}")
        assert resp_b.status_code == 404

    def test_cross_owner_capture_404(self, second_api_client) -> None:
        client_a, client_b = second_api_client

        # Client A creates a capture.
        resp_a = client_a.post(
            "/api/capture-sessions",
            json={
                "text": "Owner A capture.",
                "consent": {"external_processing_allowed": False},
            },
        )
        capture_id = resp_a.json()["atomic_capture_ids"][0]

        # Client B tries to approve it.
        resp_b = client_b.post(
            f"/api/captures/{capture_id}/decisions",
            json={"action": "approve", "expected_revision": 1},
        )
        assert resp_b.status_code == 404

    def test_cross_owner_list_empty(self, second_api_client) -> None:
        client_a, client_b = second_api_client

        # Client A creates captures.
        client_a.post(
            "/api/capture-sessions",
            json={
                "text": "Owner A capture.",
                "consent": {"external_processing_allowed": False},
            },
        )

        # Client B lists captures.
        resp_b = client_b.get("/api/captures")
        assert resp_b.status_code == 200
        assert resp_b.json() == []


class TestCaptureResultsAPI:
    def test_get_empty_results(self, api_client) -> None:
        resp = api_client.post(
            "/api/capture-sessions",
            json={
                "text": "Result test.",
                "consent": {"external_processing_allowed": False},
            },
        )
        capture_id = resp.json()["atomic_capture_ids"][0]

        results_resp = api_client.get(f"/api/captures/{capture_id}/results")
        assert results_resp.status_code == 200
        assert results_resp.json() == []


class TestAuthGate:
    def test_unauthenticated_capture_rejected(self, anonymous_api_client) -> None:
        resp = anonymous_api_client.post(
            "/api/capture-sessions",
            json={"text": "Should fail.", "consent": {"external_processing_allowed": False}},
        )
        assert resp.status_code == 401
