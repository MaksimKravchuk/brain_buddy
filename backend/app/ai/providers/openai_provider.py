"""OpenAI-backed validation provider (placeholder implementation)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.exceptions import ValidationFailure
from app.schemas.domain import ProviderConfig

from .base import ProviderContext, ProviderResult, ValidationProvider

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


@dataclass(slots=True)
class OpenAIValidationProvider(ValidationProvider):
    """Call OpenAI's chat completion API to execute validation prompts."""

    model_fallback: str = "gpt-4o-mini"
    provider_id: str = "openai"

    def _resolve_api_key(self, config: ProviderConfig | None) -> str:
        if config and config.api_key_ref:
            env_value = os.getenv(config.api_key_ref)
            if env_value:
                return env_value
        env_value = os.getenv("OPENAI_API_KEY")
        if not env_value:
            raise ValidationFailure(
                "OpenAI provider requires OPENAI_API_KEY or provider config api_key_ref."
            )
        return env_value

    def validate(
        self,
        prompt: str,
        context: ProviderContext,
        *,
        config: ProviderConfig | None = None,
    ) -> ProviderResult:
        api_key = self._resolve_api_key(config)
        model = (
            config.model if config and config.model else self.model_fallback
        ) or self.model_fallback

        payload = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    OPENAI_CHAT_COMPLETIONS_URL, json=payload, headers=headers
                )
                response.raise_for_status()
        except (
            httpx.HTTPError
        ) as exc:  # pragma: no cover - network conditions not exercised in tests
            raise ValidationFailure(f"OpenAI request failed: {exc!s}") from exc

        data: dict[str, Any] = response.json()
        message = data.get("choices", [{}])[0].get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise ValidationFailure("OpenAI response missing expected content.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValidationFailure(
                "OpenAI response did not include valid JSON."
            ) from exc

        confidence = int(parsed.get("confidence", 0))
        verdict = str(parsed.get("verdict", "uncertain"))
        observations = parsed.get("observations") or []
        questions = parsed.get("suggested_questions") or []

        return ProviderResult(
            confidence=confidence,
            verdict=verdict,
            observations=observations,
            suggested_questions=questions,
            raw=parsed,
        )
