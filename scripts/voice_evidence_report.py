#!/usr/bin/env python3
"""Produce the live T035 operational-evidence report for Voice Brain Dump.

Drives the REAL local API and the REAL configured reconciler to emit a
privacy-safe, hash-addressed capture→review→commit report keyed to the current
git SHA, the reference-corpus digest, and the declared provider/model config.
This is the release-evidence gate the final review's "operational-evidence"
finding requires: unit tests prove the scorer mechanics; this proves the numbers
on the reviewed SHA with real providers.

Two evidence sections, honestly labelled by mode (the report stamps every
criterion):

* full_recording (mode ``sealed_audio_pipeline``) — SC-001/SC-007. Uploads the
  reference m4a, seals, polls to awaiting_confirmation (SC-007 is the wall-clock
  seal→awaiting latency), and commits (SC-001 is the committed task count).
* utterances (mode ``text_reconciler``) — SC-002/SC-003/SC-004. There is no
  per-utterance audio in the corpus, so each utterance's text is driven through
  the real reconciler (not the full audio pipeline). This is real-provider
  evidence at the text-reconciler level, and the report says so per criterion.

Privacy (constitution Principle I): raw transcript/title text is used only
in-process to derive hashes, script labels, and verdicts; it is never printed or
written. Only the privacy-safe artifact/report JSON is emitted.

Example:

    OPENAI_API_KEY=... DEEPGRAM_API_KEY=... \\
    BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER=deepgram \\
    BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL=nova-3 \\
    BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER=openai \\
    BRAIN_BUDDY_VOICE_RECONCILER_MODEL=gpt-4o \\
    BRAIN_BUDDY_FEATURE_VOICE_BRAIN_DUMP=on \\
    python scripts/voice_evidence_report.py \\
        --audio "$HOME/Downloads/Jekerstraat 35-3.m4a" \\
        --email you@example.com --password 'secret' \\
        --out backend/tests/fixtures/voice_brain_dump/reference_corpus/live_report.<sha>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.container import _build_text_reconciler  # noqa: E402
from app.core.config import get_config  # noqa: E402
from app.workflows.voice_brain_dump.domain import TranscriptHypothesis  # noqa: E402
from app.workflows.voice_brain_dump.operational_evidence import (  # noqa: E402
    MODE_SEALED_AUDIO_PIPELINE,
    MODE_TEXT_RECONCILER,
    build_full_recording_run,
    build_run_artifact,
    build_utterance_run,
    compute_operational_evidence,
    load_reference_corpus,
    seal_manifest_hash,
    titled_sources_from_operation_response,
)
from app.workflows.voice_brain_dump.providers import ReconcileTextRequest  # noqa: E402

_DEFAULT_CORPUS = (
    REPO_ROOT
    / "backend/tests/fixtures/voice_brain_dump/reference_corpus"
    / "founder_ru_reading_script.v1.json"
)


def provider_config_from_config(config: Any, template_version: str) -> dict[str, str]:
    """The declared provider/model identity this run is anchored to."""

    return {
        "stt_provider": config.voice.accurate_stt.provider,
        "stt_model": config.voice.accurate_stt.model,
        "reconciler_provider": config.voice.reconciler.provider,
        "reconciler_model": config.voice.reconciler.model,
        "reconciler_template_version": template_version,
    }


def current_git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def _idempotency() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


def _authenticate(client: httpx.Client, args: argparse.Namespace) -> None:
    if args.invite_code:
        client.post(
            "/api/auth/signup",
            json={
                "email": args.email,
                "password": args.password,
                "invite_code": args.invite_code,
            },
        )
    response = client.post(
        "/api/auth/login", json={"email": args.email, "password": args.password}
    )
    response.raise_for_status()


def _poll_until_terminal(
    client: httpx.Client, operation_id: str, timeout: float, interval: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    terminal = {"awaiting_confirmation", "completed", "terminal_error", "cancelled"}
    while True:
        operation: dict[str, Any] = client.get(
            f"/api/brain-dump-operations/{operation_id}"
        ).json()
        if operation["status"] in terminal:
            return operation
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"operation did not reach awaiting_confirmation within {timeout}s "
                f"(last status: {operation['status']})"
            )
        time.sleep(interval)


def drive_full_recording(
    client: httpx.Client, args: argparse.Namespace, providers: dict[str, Any]
) -> Any:
    consent_providers = [
        value
        for value in (providers.get("accurate_stt"), providers.get("reconciler"))
        if value
    ]
    start = client.post(
        "/api/brain-dump-operations",
        headers=_idempotency(),
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": True,
                "providers": consent_providers,
                "language_hints": args.language_hints,
                "vocabulary": args.vocabulary,
            }
        },
    )
    start.raise_for_status()
    operation = start.json()
    operation_id = operation["id"]

    audio = Path(args.audio).read_bytes()
    put = client.put(
        f"/api/brain-dump-operations/{operation_id}/audio/0",
        content=audio,
        headers={
            "Content-Type": args.audio_mime,
            "X-Content-SHA256": hashlib.sha256(audio).hexdigest(),
        },
    )
    put.raise_for_status()
    operation = put.json()

    manifest = seal_manifest_hash(
        [
            {
                "chunk_number": chunk["chunk_number"],
                "sha256": chunk["sha256"],
                "size_bytes": chunk["size_bytes"],
            }
            for chunk in operation["audio_chunks"]
        ]
    )
    seal_started = time.monotonic()
    seal = client.post(
        f"/api/brain-dump-operations/{operation_id}/seal",
        headers=_idempotency(),
        json={
            "expected_revision": operation["revision"],
            "expected_chunks": len(operation["audio_chunks"]),
            "manifest_hash": manifest,
        },
    )
    seal.raise_for_status()

    operation = _poll_until_terminal(
        client, operation_id, args.poll_timeout, args.poll_interval
    )
    if operation["status"] != "awaiting_confirmation":
        raise RuntimeError(
            f"recording did not reach review (status {operation['status']}); "
            "inspect provider_runs error codes on the server"
        )
    seal_to_awaiting = time.monotonic() - seal_started
    titled_sources = titled_sources_from_operation_response(operation)

    commit = client.post(
        f"/api/brain-dump-operations/{operation_id}/commit",
        headers=_idempotency(),
        json={"expected_revision": operation["revision"]},
    )
    commit.raise_for_status()
    committed = commit.json()
    seal_to_commit = time.monotonic() - seal_started

    print(
        f"[full_recording] proposals={len(titled_sources)} "
        f"committed={len(committed['committed_task_ids'])} "
        f"seal->awaiting={seal_to_awaiting:.1f}s seal->commit={seal_to_commit:.1f}s"
    )
    return build_full_recording_run(
        operation_id=operation_id,
        titled_sources=titled_sources,
        committed_task_count=len(committed["committed_task_ids"]),
        seal_to_awaiting_confirmation_seconds=round(seal_to_awaiting, 3),
        seal_to_commit_seconds=round(seal_to_commit, 3),
    )


def drive_utterances(
    reconciler: Any, corpus: Any, utterance_text: dict[int, str]
) -> list[Any]:
    from app.exceptions import (
        ProviderRetryableError,
        ProviderTerminalError,
        ValidationFailure,
    )

    by_number = corpus.by_number()
    runs = []
    for number in sorted(utterance_text):
        text = utterance_text[number]
        segment = TranscriptHypothesis(
            id=f"seg_{number}",
            sequence=1,
            start_ms=0,
            end_ms=max(1, len(text) * 60),
            text=text,
            stability="stable",
            provider_role="accurate",
        )
        try:
            result = reconciler.reconcile(
                ReconcileTextRequest(
                    operation_id=f"utterance_{number}",
                    transcript_segments=[segment],
                    active_proposals=[],
                    language_hints=["ru", "en"],
                )
            )
            titled = [(patch.title, text) for patch in result.patches if patch.title]
        except (
            ValidationFailure,
            ProviderRetryableError,
            ProviderTerminalError,
        ) as exc:
            # A whole-call rejection (e.g. every operation ungrounded) yields no
            # proposals for this utterance. Record the code, never the text.
            print(f"[utterance {number}] no proposals ({type(exc).__name__})")
            titled = []
        runs.append(
            build_utterance_run(
                utterance_n=number,
                operation_id=f"utterance_{number}",
                titled_sources=titled,
                corpus_utterance=by_number[number],
            )
        )
        print(f"[utterance {number}] proposals={len(titled)}")
    return runs


def _load_utterance_text(corpus_path: Path) -> dict[int, str]:
    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    return {int(entry["n"]): str(entry["text"]) for entry in raw["utterances"]}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audio", type=Path, required=True, help="Reference recording (m4a/webm/wav)."
    )
    parser.add_argument("--audio-mime", default="audio/mp4")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", default=os.getenv("BRAINBUDDY_EMAIL"))
    parser.add_argument("--password", default=os.getenv("BRAINBUDDY_PASSWORD"))
    parser.add_argument(
        "--invite-code", default=None, help="Sign up first with this invite."
    )
    parser.add_argument("--corpus", type=Path, default=_DEFAULT_CORPUS)
    parser.add_argument(
        "--out", type=Path, required=True, help="Report JSON output path."
    )
    parser.add_argument("--artifact-out", type=Path, default=None)
    parser.add_argument("--language-hints", default="ru,en")
    parser.add_argument("--vocabulary", default="")
    parser.add_argument("--skip-utterances", action="store_true")
    parser.add_argument("--poll-timeout", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    args = parser.parse_args(argv)
    args.language_hints = [item for item in args.language_hints.split(",") if item]
    args.vocabulary = [item for item in args.vocabulary.split(",") if item]
    if not args.email or not args.password:
        parser.error("--email/--password (or BRAINBUDDY_EMAIL/PASSWORD) are required")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    corpus = load_reference_corpus(args.corpus)
    config = get_config()
    reconciler = _build_text_reconciler(config)
    provider_config = provider_config_from_config(
        config, getattr(reconciler, "template_version", "unknown")
    )
    git_sha = current_git_sha()

    with httpx.Client(base_url=args.base_url, timeout=args.poll_timeout + 30) as client:
        _authenticate(client, args)
        providers = client.get("/api/brain-dump-providers").json()
        full_recording = drive_full_recording(client, args, providers)

    utterance_runs: list[Any] = []
    utterances_mode = "not_produced"
    if not args.skip_utterances:
        if not getattr(reconciler, "requires_external_processing", False):
            raise SystemExit(
                "reconciler is not an external provider; set "
                "BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER=openai and OPENAI_API_KEY, "
                "or pass --skip-utterances"
            )
        utterance_runs = drive_utterances(
            reconciler, corpus, _load_utterance_text(args.corpus)
        )
        utterances_mode = MODE_TEXT_RECONCILER

    artifact = build_run_artifact(
        git_sha=git_sha,
        corpus=corpus,
        provider_config=provider_config,
        full_recording=full_recording,
        utterances=utterance_runs,
        evidence_modes={
            "full_recording": MODE_SEALED_AUDIO_PIPELINE,
            "utterances": utterances_mode,
        },
    )
    report = compute_operational_evidence(artifact, corpus)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.artifact_out:
        args.artifact_out.write_text(
            json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"\nrun_key={report.run_key}  report_id={report.report_id}")
    print(f"git_sha={git_sha}  all_passed={report.all_passed}")
    for result in report.criteria:
        print(
            f"  {result.criterion} pass={result.passed} "
            f"[{result.detail.get('evidence_mode')}] {result.detail}"
        )
    print(f"\nreport written to {args.out}")
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
