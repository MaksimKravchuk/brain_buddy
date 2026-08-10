"""Safe Schemathesis fuzzing of the in-process OpenAPI contract."""

from __future__ import annotations

import allure
import schemathesis
from hypothesis import HealthCheck, Phase, given, settings


@allure.epic("Quality spine")
@allure.feature("API contract")
@allure.story("Safe Schemathesis fuzzing")
def test_schemathesis_fuzzes_the_isolated_authenticated_asgi_app(api_client) -> None:
    """Fuzz only the ephemeral TestClient app and reject server or schema failures."""

    app = api_client.app
    assert app.state.config.environment.value == "test"
    experimental = getattr(schemathesis, "experimental", None)
    excluded_checks = None
    if experimental is not None:
        experimental.OPEN_API_3_1.enable()
    else:
        from schemathesis.checks import CHECKS, load_all_checks

        load_all_checks()
        excluded_checks = [
            check
            for check in CHECKS.get_all()
            if check.__name__ == "positive_data_acceptance"
        ]
    schema = schemathesis.openapi.from_asgi("/api/openapi.json", app)
    cookie_header = "; ".join(
        f"{cookie.name}={cookie.value}" for cookie in api_client.cookies.jar
    )

    @settings(
        max_examples=12,
        deadline=None,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(case=schema["/api/trees"]["POST"].as_strategy())
    def run_case(case) -> None:
        response = case.call(headers={"Cookie": cookie_header})
        allure.attach(
            response.text,
            name=f"{case.method} {case.path} response",
            attachment_type=allure.attachment_type.JSON,
        )
        assert response.status_code < 500
        validation_kwargs = (
            {"excluded_checks": excluded_checks} if excluded_checks else {}
        )
        case.validate_response(response, **validation_kwargs)

    run_case()
