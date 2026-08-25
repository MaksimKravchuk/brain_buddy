"""Provider-neutral validation for privacy-bounded title completions."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import AppEnvironment, TaskTitleAutocompleteSettings

_MAX_TITLE_LENGTH = 500
_SMART_ADD_LEFT_WRAPPERS = "([{"


def _has_line_break(value: str) -> bool:
    return any(char in "\r\n" for char in value)


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def _word_count(value: str) -> int:
    return len(value.split())


def _is_smart_add_name_char(char: str) -> bool:
    return char == "_" or unicodedata.category(char)[0] in {"L", "M", "N"}


def _has_smart_add_left_boundary(value: str, index: int) -> bool:
    return (
        index == 0
        or value[index - 1].isspace()
        or value[index - 1] in _SMART_ADD_LEFT_WRAPPERS
    )


def _contains_completed_smart_add_token(value: str) -> bool:
    """Mirror the normative Spec 003/frontend completed-token grammar."""
    for index, sigil in enumerate(value):
        if sigil not in "#@" or not _has_smart_add_left_boundary(value, index):
            continue
        body_start = index + 1
        if body_start >= len(value):
            continue
        if value[body_start] != '"':
            if _is_smart_add_name_char(value[body_start]):
                return True
            continue

        name: list[str] = []
        cursor = body_start + 1
        while cursor < len(value):
            char = value[cursor]
            if char == "\\" and cursor + 1 < len(value):
                escaped = value[cursor + 1]
                if escaped in {'"', "\\"}:
                    name.append(escaped)
                    cursor += 2
                    continue
            if char == '"':
                if _normalize("".join(name)):
                    return True
                break
            name.append(char)
            cursor += 1
    return False


@dataclass(frozen=True, slots=True)
class TitleCompletionRequest:
    """Validated local input; raw line breaks are rejected before normalization."""

    draft: str
    project_id: str | None = None
    project_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.draft, str) or _has_line_break(self.draft):
            raise ValueError("draft must be a single line")
        normalized = _normalize(self.draft)
        if not 1 <= len(normalized) <= _MAX_TITLE_LENGTH:
            raise ValueError("draft must contain 1-500 trimmed characters")
        if not normalized or (
            _word_count(normalized) < 1
            if self.project_id
            else _word_count(normalized) < 3
        ):
            raise ValueError("draft is not eligible for completion")


@dataclass(frozen=True, slots=True)
class TitleCompletionProviderResult:
    candidates: list[str]
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class DeterministicTitleCompletionProvider:
    """Hermetic provider used by tests; no network or persistence is involved."""

    category: str = "deterministic"

    def complete(
        self, *, draft: str, project_name: str | None, prior_titles: list[str]
    ) -> list[str]:
        suffix = f" in {project_name}" if project_name else ""
        return [
            f"{draft}{suffix} today",
            f"{draft}{suffix} this week",
            f"{draft}{suffix} tomorrow",
        ]


@dataclass(frozen=True, slots=True)
class DisabledTitleCompletionProvider:
    category: None = None
    reason: str = "provider unavailable"

    @classmethod
    def from_settings(
        cls,
        settings: TaskTitleAutocompleteSettings,
        *,
        environment: AppEnvironment,
        environ: Mapping[str, str],
    ) -> DisabledTitleCompletionProvider:
        del environment
        if settings.provider != "openai":
            return cls(reason="provider unsupported")
        if not environ.get(settings.api_key_env):
            return cls(reason="provider credentials missing")
        return cls()

    def complete(
        self, *, draft: str, project_name: str | None, prior_titles: list[str]
    ) -> list[str]:
        del draft, project_name, prior_titles
        raise OSError(self.reason)


@dataclass(frozen=True, slots=True)
class OpenAITitleCompletionProvider:
    api_key: str
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 3.0
    max_output_tokens: int = 120
    category: str = "openai"
    endpoint: str = "https://api.openai.com/v1/chat/completions"

    @classmethod
    def from_settings(
        cls,
        settings: TaskTitleAutocompleteSettings,
        *,
        environment: AppEnvironment,
        environ: Mapping[str, str],
    ) -> OpenAITitleCompletionProvider:
        del environment
        if settings.provider != "openai" or not environ.get(settings.api_key_env):
            raise ValueError("supported provider credentials are required")
        return cls(
            api_key=environ[settings.api_key_env],
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
        )

    def complete(
        self, *, draft: str, project_name: str | None, prior_titles: list[str]
    ) -> TitleCompletionProviderResult:
        try:
            response = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "max_tokens": self.max_output_tokens,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Return JSON with exactly three complete one-line task titles "
                                "under key candidates. Extend the draft; never add # or @ tokens."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "draft": draft,
                                    "project": project_name,
                                    "prior_titles": prior_titles,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise OSError("provider transport failed") from None
        try:
            body: Any = response.json()
            decoded = json.loads(body["choices"][0]["message"]["content"])
            if not isinstance(decoded, dict):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("provider returned an invalid response") from None
        candidates = decoded.get("candidates")
        if not isinstance(candidates, list) or not all(
            isinstance(candidate, str) for candidate in candidates
        ):
            raise ValueError("provider returned an invalid completion set")
        usage = body.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return TitleCompletionProviderResult(
            candidates=candidates,
            input_tokens=_token_count(usage.get("prompt_tokens")),
            output_tokens=_token_count(usage.get("completion_tokens")),
        )


def _token_count(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def build_title_completion_provider(
    settings: TaskTitleAutocompleteSettings,
    *,
    environment: AppEnvironment,
    environ: Mapping[str, str],
) -> (
    DisabledTitleCompletionProvider
    | DeterministicTitleCompletionProvider
    | OpenAITitleCompletionProvider
):
    if settings.provider == "deterministic" and environment is AppEnvironment.TEST:
        return DeterministicTitleCompletionProvider()
    if settings.provider == "openai" and environ.get(settings.api_key_env):
        return OpenAITitleCompletionProvider.from_settings(
            settings, environment=environment, environ=environ
        )
    return DisabledTitleCompletionProvider.from_settings(
        settings, environment=environment, environ=environ
    )


def validate_candidates(draft: str, candidates: list[str]) -> list[str]:
    """Return exactly three safe one-line candidates or raise ``ValueError``."""
    if not isinstance(draft, str) or _has_line_break(draft):
        raise ValueError("draft must be a single line")
    normalized_draft = _normalize(draft)
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str) or _has_line_break(candidate):
            raise ValueError("candidate must be a single line")
        if not 1 <= len(candidate) <= _MAX_TITLE_LENGTH:
            raise ValueError("candidate must contain 1-500 characters")
        if _contains_completed_smart_add_token(candidate):
            raise ValueError("candidate must not contain Smart Add tokens")
        cleaned = _normalize(candidate)
        if (
            not cleaned
            or not cleaned.casefold().startswith(normalized_draft.casefold())
            or len(cleaned) <= len(normalized_draft)
        ):
            raise ValueError("candidate must extend the draft")
        key = cleaned.casefold()
        if key not in seen:
            seen.add(key)
            result.append(cleaned)
    if len(result) != 3:
        raise ValueError("completion must contain exactly three distinct candidates")
    return result
