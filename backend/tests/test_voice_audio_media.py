"""Branch-focused contracts for fail-closed voice media inspection."""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

import pytest

from app.exceptions import ValidationFailure
from app.workflows.voice_brain_dump import audio_media


class _Container:
    def __init__(
        self,
        *,
        format_name: str = "wav",
        streams: list[object] | None = None,
        duration: int | None = None,
        packets: list[object] | None = None,
    ) -> None:
        self.format = SimpleNamespace(name=format_name)
        self.streams = streams or []
        self.duration = duration
        self._packets = packets or []

    def __enter__(self) -> _Container:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def demux(self, *_streams: object) -> list[object]:
        return self._packets


def test_media_inspection_canonicalizes_mime_parameters_and_wave_aliases() -> None:
    assert (
        audio_media.canonical_audio_mime_type(" Audio/WebM; codecs=opus ")
        == "audio/webm"
    )
    assert audio_media.canonical_audio_mime_type("audio/x-wav") == "audio/wav"


def test_media_inspection_rejects_unknown_container_and_missing_audio_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audio_media.av,
        "open",
        lambda *_args, **_kwargs: _Container(format_name="data"),
    )
    with pytest.raises(ValidationFailure, match="FORMAT_MISMATCH"):
        audio_media.inspect_audio(b"not audio", declared_mime_type="audio/wav")

    monkeypatch.setattr(
        audio_media.av,
        "open",
        lambda *_args, **_kwargs: _Container(
            streams=[SimpleNamespace(type="video")]
        ),
    )
    with pytest.raises(ValidationFailure, match="no audio stream"):
        audio_media.inspect_audio(b"video only", declared_mime_type="audio/wav")


def test_media_inspection_derives_progressive_duration_from_packet_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = SimpleNamespace(type="audio", duration=None, time_base=None)
    packets: list[object] = [
        SimpleNamespace(pts=None, dts=None, duration=0, time_base=Fraction(1, 1000)),
        SimpleNamespace(pts=None, dts=1000, duration=100, time_base=Fraction(1, 1000)),
    ]
    monkeypatch.setattr(
        audio_media.av,
        "open",
        lambda *_args, **_kwargs: _Container(streams=[stream], packets=packets),
    )

    inspected = audio_media.inspect_audio(b"progressive", declared_mime_type="audio/wav")

    assert inspected.mime_type == "audio/wav"
    assert inspected.duration_seconds == pytest.approx(1.1)


def test_media_inspection_rejects_non_positive_or_unavailable_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = SimpleNamespace(type="audio", duration=None, time_base=None)
    packet = SimpleNamespace(pts=0, dts=None, duration=None, time_base=Fraction(1, 1000))
    monkeypatch.setattr(
        audio_media.av,
        "open",
        lambda *_args, **_kwargs: _Container(streams=[stream], packets=[packet]),
    )

    with pytest.raises(ValidationFailure, match="DURATION_UNAVAILABLE"):
        audio_media.inspect_audio(b"zero duration", declared_mime_type="audio/wav")
