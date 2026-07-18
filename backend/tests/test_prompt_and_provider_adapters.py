"""Safe unit coverage for deterministic prompt and provider adapters."""

from __future__ import annotations

import httpx
import pytest

from app.ai.prompts.validation_prompt import build_validation_prompt, truncate
from app.ai.providers.base import ProviderContext
from app.ai.providers.openai_provider import OpenAIValidationProvider
from app.exceptions import ValidationFailure
from app.schemas import (
    NodeCreateRequest,
    Position,
    RelationCreateRequest,
    TreeCreateRequest,
)
from app.schemas.domain import ProviderConfig


def _context() -> ProviderContext:
    return ProviderContext(
        tree_id="tree_test",
        node_id="node_test",
        prompt_version="validation_v1",
        chain_length=1,
    )


def test_prompt_builder_uses_downstream_chain_and_truncates_values(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Prompt tree"), owner_id="owner"
    )
    cause, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="Cause", type="parent", position=Position(x=0, y=0)),
    )
    effect, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="Effect", type="child", position=Position(x=1, y=1)),
    )
    relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=cause.id,
            target_node_id=effect.id,
            kind="why",
        ),
    )
    stored = tree_service.tree_repo.load(tree.id)

    prompt = build_validation_prompt(stored, cause.id)
    upstream_prompt = build_validation_prompt(stored, effect.id)

    assert len(prompt.steps) == 1
    assert len(upstream_prompt.steps) == 1
    assert 'Effect node: "Effect"' in prompt.prompt
    assert truncate("x" * 10, limit=8) == "xxxxx..."
    assert truncate(None) == "None"


def test_prompt_builder_handles_orphan_and_unknown_nodes(
    tree_service, node_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Orphan"), owner_id="owner")
    node, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="Orphan", type="child", position=Position(x=0, y=0)),
    )
    stored = tree_service.tree_repo.load(tree.id)

    prompt = build_validation_prompt(stored, node.id)

    assert prompt.steps == []
    assert "No causal relations" in prompt.prompt
    with pytest.raises(KeyError):
        build_validation_prompt(stored, "missing")


def test_openai_provider_uses_injected_key_and_parses_fake_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAIValidationProvider()
    posted: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"confidence": 91, "verdict": "strong", "observations": [], "suggested_questions": ["why?"]}'
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout: int) -> None:
            assert timeout == 30

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self, url: str, *, json: dict[str, object], headers: dict[str, str]
        ) -> FakeResponse:
            posted.update({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setenv("TEST_OPENAI_KEY", "test-key")
    monkeypatch.setattr("app.ai.providers.openai_provider.httpx.Client", FakeClient)

    result = provider.validate(
        "prompt",
        _context(),
        config=ProviderConfig(api_key_ref="TEST_OPENAI_KEY", model="fake"),
    )

    assert result.confidence == 91
    assert result.suggested_questions == ["why?"]
    assert posted["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }


def test_openai_provider_rejects_missing_key_invalid_json_and_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAIValidationProvider()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValidationFailure, match="OPENAI_API_KEY"):
        provider.validate("prompt", _context())

    class InvalidJsonResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "not-json"}}]}

    class FailingClient:
        def __init__(self, *, timeout: int) -> None:
            assert timeout == 30

        def __enter__(self) -> FailingClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> InvalidJsonResponse:
            return InvalidJsonResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("app.ai.providers.openai_provider.httpx.Client", FailingClient)
    with pytest.raises(ValidationFailure, match="valid JSON"):
        provider.validate("prompt", _context())

    class TransportFailingClient(FailingClient):
        def post(self, *_args: object, **_kwargs: object) -> InvalidJsonResponse:
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(
        "app.ai.providers.openai_provider.httpx.Client", TransportFailingClient
    )
    with pytest.raises(ValidationFailure, match="request failed"):
        provider.validate("prompt", _context())
