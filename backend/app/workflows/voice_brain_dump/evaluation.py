"""Deterministic labelled release evaluation for Voice Brain Dump.

The audio cases exercise the sealed-original-audio provider boundary with immutable byte
fixtures. Production-provider evaluations can reuse the same labels while replacing the
provider; this CI gate protects multilingual normalization, intent extraction, and the
text/audio contract without a network dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from .providers import AccurateSttRequest, DeterministicAccurateStt, _extract_titles


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    language: str
    modality: str
    transcript: str
    expected_intents: tuple[str, ...]
    structural_change: str | None = None


@dataclass(frozen=True)
class EvaluationReport:
    case_count: int
    languages: set[str]
    modalities: set[str]
    text_exact_accuracy: float
    audio_exact_accuracy: float
    intent_set_accuracy: float
    structural_lineage_cases: int
    failures: list[str]


RELEASE_DATASET = (
    EvaluationCase(
        "en-text-1",
        "en",
        "text",
        "Buy oat milk. Call the dentist.",
        ("Buy oat milk", "Call the dentist"),
        "split",
    ),
    EvaluationCase(
        "en-audio-1",
        "en",
        "audio",
        "Buy oat milk. Call the dentist.",
        ("Buy oat milk", "Call the dentist"),
        "split",
    ),
    EvaluationCase(
        "en-text-2",
        "en",
        "text",
        "Renew car insurance; email Anna",
        ("Renew car insurance", "Email Anna"),
    ),
    EvaluationCase(
        "en-audio-2",
        "en",
        "audio",
        "Renew car insurance; email Anna",
        ("Renew car insurance", "Email Anna"),
    ),
    EvaluationCase(
        "ru-text-1",
        "ru",
        "text",
        "Надо купить хлеб. Потом позвонить врачу",
        ("Купить хлеб", "Позвонить врачу"),
    ),
    EvaluationCase(
        "ru-audio-1",
        "ru",
        "audio",
        "Надо купить хлеб. Потом позвонить врачу",
        ("Купить хлеб", "Позвонить врачу"),
    ),
    EvaluationCase(
        "ru-text-2",
        "ru",
        "text",
        "Нужно починить BrainBuddy",
        ("Починить BrainBuddy",),
        "merge",
    ),
    EvaluationCase(
        "ru-audio-2",
        "ru",
        "audio",
        "Нужно починить BrainBuddy",
        ("Починить BrainBuddy",),
        "merge",
    ),
    EvaluationCase(
        "es-text-1",
        "es",
        "text",
        "Comprar leche. Llamar al dentista",
        ("Comprar leche", "Llamar al dentista"),
    ),
    EvaluationCase(
        "es-audio-1",
        "es",
        "audio",
        "Comprar leche. Llamar al dentista",
        ("Comprar leche", "Llamar al dentista"),
    ),
    EvaluationCase(
        "es-text-2",
        "es",
        "text",
        "Enviar informe; reservar hotel",
        ("Enviar informe", "Reservar hotel"),
    ),
    EvaluationCase(
        "es-audio-2",
        "es",
        "audio",
        "Enviar informe; reservar hotel",
        ("Enviar informe", "Reservar hotel"),
    ),
)


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def evaluate_release_dataset() -> EvaluationReport:
    failures: list[str] = []
    text_total = text_exact = audio_total = audio_exact = intent_exact = 0
    provider = DeterministicAccurateStt()

    for case in RELEASE_DATASET:
        transcript = case.transcript
        if case.modality == "audio":
            audio_total += 1
            result = provider.transcribe_sealed_audio(
                AccurateSttRequest(
                    operation_id=case.id,
                    media_ref=f"fixture_{case.id}",
                    language_hints=[case.language],
                    sealed_audio=case.transcript.encode(),
                )
            )
            transcript = result.segments[0].text
            if _normalized(transcript) == _normalized(case.transcript):
                audio_exact += 1
            else:
                failures.append(f"{case.id}: audio transcript mismatch")
        else:
            text_total += 1
            if _normalized(transcript) == _normalized(case.transcript):
                text_exact += 1
            else:
                failures.append(f"{case.id}: text normalization mismatch")

        predicted = tuple(_extract_titles(transcript))
        if predicted == case.expected_intents:
            intent_exact += 1
        else:
            failures.append(
                f"{case.id}: intents {predicted!r} != {case.expected_intents!r}"
            )

    return EvaluationReport(
        case_count=len(RELEASE_DATASET),
        languages={case.language for case in RELEASE_DATASET},
        modalities={case.modality for case in RELEASE_DATASET},
        text_exact_accuracy=text_exact / text_total,
        audio_exact_accuracy=audio_exact / audio_total,
        intent_set_accuracy=intent_exact / len(RELEASE_DATASET),
        structural_lineage_cases=sum(
            case.structural_change is not None for case in RELEASE_DATASET
        ),
        failures=failures,
    )
