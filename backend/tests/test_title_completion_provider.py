from __future__ import annotations

import httpx
import pytest

from app.ai.title_completion import (
    DisabledTitleCompletionProvider,
    OpenAITitleCompletionProvider,
    TitleCompletionRequest,
    build_title_completion_provider,
    validate_candidates,
)
from app.core.config import AppEnvironment, TaskTitleAutocompleteSettings


def test_title_completion_request_rejects_raw_multiline_draft() -> None:
    """012-FR-002 rejects raw multiline drafts before normalization."""
    with pytest.raises(ValueError):
        TitleCompletionRequest(draft="buy\n milk")


def test_title_completion_request_rejects_out_of_bounds_draft() -> None:
    with pytest.raises(ValueError, match="1-500"):
        TitleCompletionRequest(draft="x" * 501)


def test_title_completion_request_uses_trimmed_draft_length() -> None:
    request = TitleCompletionRequest(draft=f" {('x' * 500)} ", project_id="project-1")

    assert request.draft.strip() == "x" * 500


def test_provider_settings_are_bounded_and_disabled_by_default() -> None:
    settings = TaskTitleAutocompleteSettings()

    assert settings.provider == "disabled"
    assert settings.model == "gpt-4o-mini"
    assert settings.timeout_seconds == 3.0
    assert settings.max_history_titles == 50
    assert settings.max_output_tokens == 120


def test_provider_factory_requires_supported_provider_and_credentials() -> None:
    disabled = DisabledTitleCompletionProvider.from_settings(
        TaskTitleAutocompleteSettings(provider="openai"),
        environment=AppEnvironment.PRODUCTION,
        environ={},
    )
    assert disabled.category is None

    provider = OpenAITitleCompletionProvider.from_settings(
        TaskTitleAutocompleteSettings(provider="openai"),
        environment=AppEnvironment.PRODUCTION,
        environ={"OPENAI_API_KEY": "test-key"},
    )
    assert provider.category == "openai"
    assert provider.endpoint == "https://api.openai.com/v1/chat/completions"
    assert provider.timeout_seconds == 3.0

    with pytest.raises(ValueError, match="credentials"):
        OpenAITitleCompletionProvider.from_settings(
            TaskTitleAutocompleteSettings(provider="disabled"),
            environment=AppEnvironment.PRODUCTION,
            environ={},
        )


def test_provider_builds_openai_and_disabled_failure_paths() -> None:
    settings = TaskTitleAutocompleteSettings(provider="openai")
    provider = build_title_completion_provider(
        settings,
        environment=AppEnvironment.PRODUCTION,
        environ={"OPENAI_API_KEY": "test-key"},
    )
    assert isinstance(provider, OpenAITitleCompletionProvider)

    disabled = DisabledTitleCompletionProvider.from_settings(
        settings,
        environment=AppEnvironment.PRODUCTION,
        environ={"OPENAI_API_KEY": "test-key"},
    )
    with pytest.raises(OSError, match="unavailable"):
        disabled.complete(draft="prepare launch", project_name=None, prior_titles=[])


def test_validate_candidates_requires_three_distinct_one_line_extensions() -> None:
    """012-FR-007 returns no partial candidate set."""
    with pytest.raises(ValueError):
        validate_candidates("buy milk", ["buy milk", "buy milk later"])


@pytest.mark.parametrize(
    "draft,candidate_with_token",
    [
        ("#home plan", "#home plan today"),
        ("buy milk", "buy milk #home today"),
        ("buy milk", "buy milk (#home) today"),
        ("buy milk", "buy milk [#work] tomorrow"),
        ("buy milk", "buy milk {@project} this week"),
        ("buy milk", 'buy milk #"deep work" today'),
        ("buy milk", 'buy milk #"deep \\"work\\"" today'),
        ("buy milk", 'buy milk #"deep \\\\work" today'),
        ("buy milk", 'buy milk (@"Launch v2") tomorrow'),
    ],
)
def test_validate_candidates_rejects_canonical_completed_smart_add_tokens(
    draft: str,
    candidate_with_token: str,
) -> None:
    """012-FR-008 mirrors Spec 003 boundaries and quoted-token grammar."""
    with pytest.raises(ValueError, match="Smart Add"):
        validate_candidates(
            draft,
            [candidate_with_token, f"{draft} today", f"{draft} tomorrow"],
        )


@pytest.mark.parametrize(
    "safe_literal",
    [
        "buy milk word,#home today",
        'buy milk "#home" today',
        "buy milk \\#home today",
        "buy milk # today",
        "buy milk #",
        'buy milk #"" today',
        'buy milk @"Launch v2 today',
    ],
)
def test_validate_candidates_keeps_non_tokens_literal_like_canonical_parser(
    safe_literal: str,
) -> None:
    """012-FR-008 must not broaden suppression beyond the Spec 003 parser."""
    assert validate_candidates(
        "buy milk",
        [safe_literal, "buy milk today", "buy milk tomorrow"],
    ) == [safe_literal, "buy milk today", "buy milk tomorrow"]


@pytest.mark.parametrize(
    "draft,candidates,message",
    [
        ("buy\nmilk", ["buy milk today"] * 3, "single line"),
        ("buy milk", ["buy milk today", 7, "buy milk tomorrow"], "single line"),
        (
            "buy milk",
            ["buy milk " + "x" * 500, "buy milk today", "buy milk tomorrow"],
            "1-500",
        ),
        (
            "buy milk",
            ["buy milk today", " BUY MILK TODAY ", "buy milk tomorrow"],
            "exactly three",
        ),
    ],
)
def test_validate_candidates_rejects_invalid_complete_sets(
    draft: str, candidates: list[object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_candidates(draft, candidates)  # type: ignore[arg-type]


def test_openai_provider_rejects_non_string_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {"message": {"content": '{"candidates":["valid",2,"other"]}'}}
                ]
            }

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: Response())

    with pytest.raises(ValueError, match="invalid completion set"):
        OpenAITitleCompletionProvider(api_key="secret").complete(
            draft="prepare launch", project_name=None, prior_titles=[]
        )


def test_openai_provider_sanitizes_malformed_response_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"private-provider-body": "must-not-escape"}

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: Response())

    with pytest.raises(ValueError, match="invalid response"):
        OpenAITitleCompletionProvider(api_key="secret").complete(
            draft="prepare launch", project_name=None, prior_titles=[]
        )


def test_openai_provider_rejects_non_object_json_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "[]"}}]}

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: Response())

    with pytest.raises(ValueError, match="invalid response"):
        OpenAITitleCompletionProvider(api_key="secret").complete(
            draft="prepare launch", project_name=None, prior_titles=[]
        )


def test_openai_provider_uses_one_fixed_origin_call_with_three_second_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"candidates":["prepare launch today","prepare launch this week","prepare launch tomorrow"]}'
                        }
                    }
                ]
            }

    def post(url: str, **kwargs: object) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(httpx, "post", post)
    provider = OpenAITitleCompletionProvider(api_key="secret")

    result = provider.complete(
        draft="prepare launch", project_name="Launch", prior_titles=["prior"]
    )

    assert result.candidates == [
        "prepare launch today",
        "prepare launch this week",
        "prepare launch tomorrow",
    ]
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert calls[0]["timeout"] == 3.0


def test_openai_provider_extracts_available_token_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"candidates":["prepare launch today","prepare launch this week","prepare launch tomorrow"]}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 41, "completion_tokens": 17},
            }

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: Response())

    result = OpenAITitleCompletionProvider(api_key="secret").complete(
        draft="prepare launch", project_name=None, prior_titles=[]
    )

    assert result.candidates == [
        "prepare launch today",
        "prepare launch this week",
        "prepare launch tomorrow",
    ]
    assert result.input_tokens == 41
    assert result.output_tokens == 17


def test_openai_transport_failure_is_mapped_to_provider_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise httpx.ConnectError("private-provider-body")

    monkeypatch.setattr(httpx, "post", fail)

    with pytest.raises(OSError, match="provider transport failed"):
        OpenAITitleCompletionProvider(api_key="secret").complete(
            draft="prepare launch", project_name=None, prior_titles=[]
        )
