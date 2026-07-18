"""Release-gate coverage for the labelled Voice Brain Dump evaluation set."""

from app.workflows.voice_brain_dump.evaluation import evaluate_release_dataset


def test_labelled_multilingual_text_and_audio_release_metrics_meet_fixed_gates() -> (
    None
):
    report = evaluate_release_dataset()

    assert report.case_count >= 12
    assert report.languages == {"en", "es", "ru"}
    assert report.modalities == {"audio", "text"}
    assert report.text_exact_accuracy >= 0.95
    assert report.audio_exact_accuracy >= 0.95
    assert report.intent_set_accuracy >= 0.95
    assert report.structural_lineage_cases >= 2
    assert report.failures == []
