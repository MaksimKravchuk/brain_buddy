"""Fail-closed media inspection for persisted Voice Brain Dump audio."""

from __future__ import annotations

import io
from dataclasses import dataclass

import av
from av.error import FFmpegError

from app.exceptions import ValidationFailure

_MIME_ALIASES = {
    "audio/wave": "audio/wav",
    "audio/x-wav": "audio/wav",
}
_FORMAT_MIME_TYPES = {
    "aac": "audio/aac",
    "adts": "audio/aac",
    "ipod": "audio/mp4",
    "m4a": "audio/mp4",
    "matroska": "audio/webm",
    "mov": "audio/mp4",
    "mp4": "audio/mp4",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "webm": "audio/webm",
}


@dataclass(frozen=True, slots=True)
class InspectedAudio:
    mime_type: str
    duration_seconds: float


def canonical_audio_mime_type(mime_type: str) -> str:
    normalized = mime_type.partition(";")[0].strip().casefold()
    return _MIME_ALIASES.get(normalized, normalized)


def inspect_audio(audio: bytes, *, declared_mime_type: str) -> InspectedAudio:
    """Verify container/audio-stream identity and derive duration from media bytes."""

    declared = canonical_audio_mime_type(declared_mime_type)
    try:
        with av.open(io.BytesIO(audio), mode="r") as container:
            format_names = {
                name.strip().casefold() for name in container.format.name.split(",")
            }
            detected = next(
                (
                    _FORMAT_MIME_TYPES[name]
                    for name in format_names
                    if name in _FORMAT_MIME_TYPES
                ),
                None,
            )
            if detected is None or detected != declared:
                raise ValidationFailure(
                    "AUDIO_CHUNK_FORMAT_MISMATCH: declared MIME type does not "
                    "match the uploaded media container."
                )
            audio_streams = [stream for stream in container.streams if stream.type == "audio"]
            if not audio_streams:
                raise ValidationFailure(
                    "AUDIO_CHUNK_FORMAT_MISMATCH: uploaded media has no audio stream."
                )
            durations = [
                float(stream.duration * stream.time_base)
                for stream in audio_streams
                if stream.duration is not None and stream.time_base is not None
            ]
            if container.duration is not None:
                durations.append(float(container.duration / av.time_base))
            if not durations:
                for packet in container.demux(*audio_streams):
                    timestamp = packet.pts if packet.pts is not None else packet.dts
                    if timestamp is None or packet.time_base is None:
                        continue
                    durations.append(
                        float((timestamp + (packet.duration or 0)) * packet.time_base)
                    )
            if not durations or max(durations) <= 0:
                raise ValidationFailure(
                    "AUDIO_DURATION_UNAVAILABLE: uploaded media duration could not be derived."
                )
            return InspectedAudio(
                mime_type=detected,
                duration_seconds=max(durations),
            )
    except ValidationFailure:
        raise
    except (FFmpegError, EOFError, ValueError) as exc:
        raise ValidationFailure(
            "AUDIO_CHUNK_FORMAT_MISMATCH: uploaded bytes are not valid declared audio."
        ) from exc
