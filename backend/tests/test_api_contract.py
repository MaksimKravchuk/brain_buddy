"""Executable OpenAPI contract checks for the public HTTP API."""

from __future__ import annotations

import allure
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers

ERROR_ENVELOPE = {"message", "detail", "reference_id"}


@allure.epic("Quality spine")
@allure.feature("API contract")
@allure.story("OpenAPI error responses")
def test_openapi_documents_precise_error_envelopes(api_client) -> None:
    """Public operations publish their intentional failure statuses explicitly."""

    response = api_client.get("/api/openapi.json")

    assert response.status_code == 200
    allure.attach(
        response.text,
        name="OpenAPI contract",
        attachment_type=allure.attachment_type.JSON,
    )
    schema = response.json()
    error_schema = schema["components"]["schemas"]["ErrorResponse"]
    assert error_schema["required"] == ["message"]

    expected_error_statuses = {
        ("/api/account", "get"): {"401"},
        ("/api/account/profile", "patch"): {"400", "401", "422"},
        ("/api/account/email", "post"): {"400", "401", "403", "422", "429"},
        ("/api/account/password", "post"): {"400", "401", "403", "422", "429"},
        ("/api/auth/login", "post"): {"401", "422", "429"},
        ("/api/auth/logout", "post"): set(),
        ("/api/auth/me", "get"): {"401"},
        ("/api/auth/signup", "post"): {"400", "409", "422"},
        ("/api/brain-dump-operations", "post"): {"400", "401", "409", "422"},
        ("/api/brain-dump-providers", "get"): {"401"},
        ("/api/brain-dump-operations/{operation_id}", "get"): {"401", "404", "422"},
        ("/api/brain-dump-operations/{operation_id}/audio/{chunk_number}", "put"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}", "patch"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/brain-dump-operations/{operation_id}/seal", "post"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/brain-dump-operations/{operation_id}/transcript", "post"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/brain-dump-operations/{operation_id}/{action}", "post"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/projects", "get"): {"401"},
        ("/api/projects", "post"): {"400", "401", "409", "422"},
        ("/api/projects/{project_id}", "get"): {"401", "404", "422"},
        ("/api/projects/{project_id}", "patch"): {"400", "401", "404", "409", "422"},
        ("/api/projects/{project_id}/archive", "post"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/tags", "get"): {"401"},
        ("/api/tags", "post"): {"400", "401", "409", "422"},
        ("/api/tags/{tag_id}", "delete"): {"400", "401", "404", "409", "422"},
        ("/api/tags/{tag_id}", "get"): {"401", "404", "422"},
        ("/api/tags/{tag_id}", "patch"): {"400", "401", "404", "409", "422"},
        ("/api/tasks", "get"): {"400", "401", "404", "422"},
        ("/api/tasks", "post"): {"400", "401", "404", "409", "422"},
        ("/api/tasks/smart-add", "post"): {"400", "401", "404", "409", "422"},
        ("/api/tasks/{task_id}", "get"): {"401", "404", "422"},
        ("/api/tasks/{task_id}", "patch"): {"400", "401", "404", "409", "422"},
        ("/api/tasks/{task_id}/comments", "post"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/tasks/{task_id}/subtasks", "post"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/tasks/{task_id}/subtasks/{subtask_id}", "patch"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/tasks/{task_id}/subtasks/{subtask_id}/transitions", "post"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/tasks/{task_id}/transitions", "post"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/tasks/{task_id}/comments/{comment_id}", "patch"): {
            "400",
            "401",
            "404",
            "409",
            "422",
        },
        ("/api/trees", "get"): {"401", "422"},
        ("/api/trees", "post"): {"400", "401", "422"},
        ("/api/trees/import", "post"): {"400", "401", "422"},
        ("/api/trees/{tree_id}", "delete"): {"401", "404", "422"},
        ("/api/trees/{tree_id}", "get"): {"401", "404", "422"},
        ("/api/trees/{tree_id}", "put"): {"400", "401", "404", "409", "422"},
        ("/api/trees/{tree_id}/ai-feedback", "post"): {
            "400",
            "401",
            "404",
            "422",
        },
        ("/api/trees/{tree_id}/export", "post"): {"401", "404", "422"},
        ("/api/trees/{tree_id}/nodes", "post"): {"401", "404", "422"},
        ("/api/trees/{tree_id}/nodes/{node_id}", "delete"): {
            "400",
            "401",
            "404",
            "422",
        },
        ("/api/trees/{tree_id}/nodes/{node_id}", "patch"): {
            "401",
            "404",
            "422",
        },
        (
            "/api/trees/{tree_id}/nodes/{node_id}/validation-history",
            "get",
        ): {"401", "404", "422"},
        ("/api/trees/{tree_id}/relations", "post"): {
            "400",
            "401",
            "404",
            "422",
        },
        ("/api/trees/{tree_id}/relations/{relation_id}", "delete"): {
            "401",
            "404",
            "422",
        },
        ("/api/trees/{tree_id}/relations/{relation_id}", "patch"): {
            "400",
            "401",
            "404",
            "422",
        },
        ("/api/trees/{tree_id}/validate/{node_id}", "post"): {
            "400",
            "401",
            "404",
            "422",
        },
        ("/api/trees/{tree_id}/versions", "get"): {"401", "404", "422"},
        ("/api/trees/{tree_id}/versions", "post"): {"401", "404", "422"},
        ("/api/trees/{tree_id}/versions/{version_id}", "delete"): {
            "401",
            "404",
            "422",
        },
        ("/api/trees/{tree_id}/versions/{version_id}/restore", "post"): {
            "401",
            "404",
            "422",
        },
    }
    discovered_operations = {
        (path, method)
        for path, path_item in schema["paths"].items()
        if path.startswith("/api/")
        for method in path_item
        if method in {"delete", "get", "patch", "post", "put"}
    }
    assert set(expected_error_statuses) == discovered_operations
    for (path, method), expected_statuses in expected_error_statuses.items():
        responses = schema["paths"][path][method]["responses"]
        documented_4xx_statuses = {
            status_code for status_code in responses if 400 <= int(status_code) < 500
        }
        assert documented_4xx_statuses == expected_statuses
        for status_code in expected_statuses:
            content = responses[status_code]["content"]
            assert content["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }


@allure.epic("Quality spine")
@allure.feature("API contract")
@allure.story("Error envelope and correlation ID")
def test_public_errors_use_the_documented_envelope_and_correlation_id(
    anonymous_api_client,
) -> None:
    """Authentication and request-validation failures are traceable API errors."""

    correlation_id = "contract-correlation-id"
    unauthorized = anonymous_api_client.get(
        "/api/trees", headers={"X-Correlation-ID": correlation_id}
    )
    invalid_login = anonymous_api_client.post(
        "/api/auth/login",
        json={"email": "not-an-email"},
        headers={"X-Correlation-ID": correlation_id},
    )

    for response, status_code in ((unauthorized, 401), (invalid_login, 422)):
        assert response.status_code == status_code
        assert response.headers["X-Correlation-ID"] == correlation_id
        assert response.json().keys() >= ERROR_ENVELOPE
        assert response.json()["reference_id"] == correlation_id


@allure.epic("Quality spine")
@allure.feature("API contract")
@allure.story("Error envelope and correlation ID")
def test_routing_errors_use_the_documented_envelope_and_correlation_id(
    anonymous_api_client,
) -> None:
    """Router-generated 404 and 405 errors obey the public error contract."""

    correlation_id = "routing-correlation-id"
    unknown_path = anonymous_api_client.get(
        "/api/does-not-exist", headers={"X-Correlation-ID": correlation_id}
    )
    wrong_method = anonymous_api_client.get(
        "/api/auth/login", headers={"X-Correlation-ID": correlation_id}
    )

    for response, status_code in ((unknown_path, 404), (wrong_method, 405)):
        assert response.status_code == status_code
        assert response.headers["X-Correlation-ID"] == correlation_id
        assert response.json().keys() >= ERROR_ENVELOPE
        assert response.json()["reference_id"] == correlation_id
    assert wrong_method.headers["allow"] == "POST"


@allure.epic("Quality spine")
@allure.feature("API contract")
@allure.story("OpenAPI error responses")
def test_all_documented_public_error_responses_use_the_standard_envelope(
    api_client,
) -> None:
    """Every documented 4xx response refers to one contract-wide error shape."""

    schema = api_client.get("/api/openapi.json").json()
    expected_schema = {"$ref": "#/components/schemas/ErrorResponse"}

    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"delete", "get", "patch", "post", "put"}:
                continue
            for status_code, response in operation["responses"].items():
                if int(status_code) < 400:
                    continue
                content = response["content"]
                assert (
                    content["application/json"]["schema"] == expected_schema
                ), f"{method.upper()} {path} {status_code}"


@allure.epic("Quality spine")
@allure.feature("API contract")
@allure.story("Error envelope without tracing middleware")
def test_error_handlers_preserve_envelopes_without_a_correlation_context() -> None:
    """Reusable handlers remain valid when a host app has no tracing middleware."""

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/http-error")
    def http_error() -> None:
        raise HTTPException(status_code=418, detail={"reason": "teapot"})

    @app.get("/validated")
    def validated(required: int) -> int:
        return required

    client = TestClient(app)
    http_response = client.get("/http-error")
    validation_response = client.get("/validated")

    assert http_response.status_code == 418
    assert http_response.json() == {
        "message": "{'reason': 'teapot'}",
        "detail": {"reason": "teapot"},
        "reference_id": None,
    }
    assert validation_response.status_code == 422
    assert validation_response.json()["message"] == "Request validation failed."
    assert isinstance(validation_response.json()["detail"], list)
    assert validation_response.json()["reference_id"] is None
    assert "X-Correlation-ID" not in http_response.headers
    assert "X-Correlation-ID" not in validation_response.headers
