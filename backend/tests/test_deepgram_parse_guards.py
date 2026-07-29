"""Fail-safe parsing guards in the Deepgram response walkers.

The adapter never trusts the provider payload shape: each helper returns a safe
default when a nested field is missing or the wrong type. These unit tests pin
every defensive branch directly, which the full-transcription tests (which pass
well-formed payloads) do not reach.
"""

from __future__ import annotations

from app.workflows.voice_brain_dump.adapters.deepgram_stt import (
    _distinct_word_languages,
    _first_alternative,
    _metadata_duration,
    _to_ms,
    _utterances,
)


def test_first_alternative_returns_none_for_every_malformed_shape() -> None:
    assert _first_alternative("not-a-dict") is None
    assert _first_alternative({"results": "not-a-dict"}) is None
    assert _first_alternative({"results": {"channels": "not-a-list"}}) is None
    assert _first_alternative({"results": {"channels": []}}) is None
    assert _first_alternative({"results": {"channels": ["not-a-dict"]}}) is None
    assert (
        _first_alternative({"results": {"channels": [{"alternatives": "no"}]}}) is None
    )
    assert (
        _first_alternative({"results": {"channels": [{"alternatives": ["no"]}]}})
        is None
    )
    assert _first_alternative(
        {"results": {"channels": [{"alternatives": [{"transcript": "ok"}]}]}}
    ) == {"transcript": "ok"}


def test_utterances_returns_empty_for_every_malformed_shape() -> None:
    assert _utterances("not-a-dict") == []
    assert _utterances({"results": "not-a-dict"}) == []
    assert _utterances({"results": {"utterances": "not-a-list"}}) == []
    assert _utterances({"results": {"utterances": [{"a": 1}, "skip-me"]}}) == [{"a": 1}]


def test_to_ms_defaults_on_missing_or_negative_and_scales_otherwise() -> None:
    assert _to_ms(None, default=7) == 7
    assert _to_ms(-1.0, default=7) == 7
    assert _to_ms(1.5, default=7) == 1500


def test_distinct_word_languages_guards_each_shape() -> None:
    assert _distinct_word_languages(None) is None
    assert _distinct_word_languages({"words": "not-a-list"}) is None
    assert _distinct_word_languages({"words": []}) is None
    assert (
        _distinct_word_languages(
            {"words": ["skip", {"language": "en"}, {"language": ""}, {"other": 1}]}
        )
        == "en"
    )


def test_metadata_duration_guards_each_shape() -> None:
    assert _metadata_duration("not-a-dict") is None
    assert _metadata_duration({"metadata": "not-a-dict"}) is None
    assert _metadata_duration({"metadata": {"duration": 3.0}}) == 3.0
