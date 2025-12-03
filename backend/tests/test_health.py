"""Basic smoke tests for the Brain Buddy API."""

from fastapi.testclient import TestClient

from app.core import get_config
from app.main import app


def test_health_check() -> None:
    client = TestClient(app)
    response = client.get("/health")

    config = get_config()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["environment"] == config.environment.value
    assert payload["schema_version"] == config.data.schema_version
