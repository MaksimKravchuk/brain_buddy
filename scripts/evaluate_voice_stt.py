#!/usr/bin/env python3
"""Run credentialed STT evaluation over an external founder corpus."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.container import _build_accurate_stt  # noqa: E402
from app.core.config import get_config  # noqa: E402
from app.workflows.voice_brain_dump.evaluation import (  # noqa: E402
    evaluate_real_audio_corpus,
)


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the configured accurate-STT provider. The corpus stays external; "
            "only aggregate metrics are printed."
        )
    )
    parser.add_argument("corpus", type=Path)
    parser.add_argument(
        "--consent-external-processing",
        action="store_true",
        help="Confirm that corpus audio may be sent to the configured provider.",
    )
    args = parser.parse_args()

    provider = _build_accurate_stt(get_config())
    report = evaluate_real_audio_corpus(
        args.corpus,
        provider,
        external_processing_allowed=args.consent_external_processing,
    )
    print(json.dumps(_json_value(asdict(report)), indent=2, sort_keys=True))
    return 0 if report.status in {"completed", "disabled"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
