"""Privacy headers on the account surface (027-FR-022, 027-FR-009)."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("path", ["/api/account", "/api/account/", "/api/auth/methods"])
def test_027_FR_022_account_and_auth_responses_are_not_cacheable(
    path, anonymous_api_client
):
    response = anonymous_api_client.get(path)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_027_FR_009_prefix_lookalike_gets_no_privacy_headers(anonymous_api_client):
    response = anonymous_api_client.get("/api/accountant")
    assert "Referrer-Policy" not in response.headers
