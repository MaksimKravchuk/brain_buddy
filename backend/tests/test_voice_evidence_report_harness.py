"""Pure-logic coverage for the live evidence-report harness (scripts/).

The HTTP drive itself needs a live server + real providers (run by hand); these
tests pin the harness's pure helpers so a refactor cannot silently break arg
parsing, the provider-config identity, or corpus-text loading.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import voice_evidence_report as harness  # noqa: E402

_CORPUS_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "voice_brain_dump"
    / "reference_corpus"
    / "founder_ru_reading_script.v1.json"
)


def test_provider_config_from_config_captures_declared_identity() -> None:
    config = SimpleNamespace(
        voice=SimpleNamespace(
            accurate_stt=SimpleNamespace(provider="deepgram", model="nova-3"),
            reconciler=SimpleNamespace(provider="openai", model="gpt-4o"),
        )
    )
    assert harness.provider_config_from_config(config, "brain-dump-reconciler-v2") == {
        "stt_provider": "deepgram",
        "stt_model": "nova-3",
        "reconciler_provider": "openai",
        "reconciler_model": "gpt-4o",
        "reconciler_template_version": "brain-dump-reconciler-v2",
    }


def test_load_utterance_text_reads_every_numbered_utterance() -> None:
    text = harness._load_utterance_text(_CORPUS_PATH)
    assert sorted(text) == list(range(1, 51))
    assert all(isinstance(value, str) and value for value in text.values())


def test_parse_args_splits_lists_and_requires_credentials() -> None:
    args = harness.parse_args(
        [
            "--audio",
            "rec.m4a",
            "--out",
            "report.json",
            "--email",
            "you@example.com",
            "--password",
            "secret",
            "--language-hints",
            "ru,en,nl",
            "--vocabulary",
            "BrainBuddy,staging",
        ]
    )
    assert args.language_hints == ["ru", "en", "nl"]
    assert args.vocabulary == ["BrainBuddy", "staging"]

    with pytest.raises(SystemExit):
        harness.parse_args(["--audio", "rec.m4a", "--out", "report.json"])
