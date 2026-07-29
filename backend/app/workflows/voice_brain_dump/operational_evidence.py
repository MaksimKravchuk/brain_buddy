"""Operational evidence report for the multilingual Voice Brain Dump release (T035).

This produces a privacy-safe, hash-addressed capture→review→commit report keyed
to the exact git SHA, the reference-corpus digest, and the provider/model
configuration, computing the release success criteria:

* SC-001 — committed task count from the reference recording (≥15).
* SC-002 — task-yielding utterances yielding exactly one correct proposal (≥80%).
* SC-003 — proposal titles translated out of their source language (must be 0).
* SC-004 — single-intent utterances false-split on a conjunction (must be 0).
* SC-007 — seal → awaiting-confirmation latency for the recording (≤120s).

Two production modes share one scorer (``compute_operational_evidence``):

* **Live** — ``build_run_artifact_from_operations`` projects a real run's
  persisted ``BrainDumpOperationDocument`` artifacts (the full recording plus 50
  isolated per-utterance operations) into a ``RunArtifact``. A real run on the
  release SHA fills in the live numbers.
* **Recorded** — ``run_artifact_from_dict`` loads a committed run-artifact JSON,
  so CI can verify report integrity deterministically without any provider call.

Constitution Principle I: neither the ``RunArtifact`` nor the report carries raw
transcript or audio content. Titles are reduced to a SHA-256 at capture time;
language fidelity is reduced to a coarse script label and a verdict. Only
hashes, counts, ratios, coarse labels, and ids cross this boundary. The
reference-corpus ground truth (the founder-authored script) is committed
separately as versioned test data and is the sole place utterance text lives.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.workflows.voice_brain_dump.domain import BrainDumpOperationDocument
from app.workflows.voice_brain_dump.language_fidelity import (
    FidelityVerdict,
    classify_title_fidelity,
)

SCHEMA_VERSION = 1

SC001_MIN_COMMITTED_TASKS = 15
SC002_MIN_SINGLE_CORRECT_RATIO = 0.80
SC007_MAX_SEAL_TO_CONFIRMATION_SECONDS = 120.0


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


# --- Reference corpus ground truth -----------------------------------------


@dataclass(frozen=True)
class CorpusUtterance:
    n: int
    category: str
    task_yielding: bool
    expected_task_count: int
    conjunction_single_intent: bool
    source_scripts: tuple[str, ...]
    embedded_foreign_terms: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceCorpus:
    corpus_id: str
    version: int
    digest: str
    utterances: tuple[CorpusUtterance, ...]

    def by_number(self) -> dict[int, CorpusUtterance]:
        return {utterance.n: utterance for utterance in self.utterances}


def load_reference_corpus(path: Path) -> ReferenceCorpus:
    """Load and digest the versioned reference-corpus ground truth.

    The digest is computed only over the label fields the scorer consumes, so it
    is stable against edits to descriptive prose (``source``, rule text) in the
    fixture and changes only when the ground-truth labels themselves change.
    """

    raw = json.loads(path.read_text(encoding="utf-8"))
    utterances = tuple(
        CorpusUtterance(
            n=int(entry["n"]),
            category=str(entry["category"]),
            task_yielding=bool(entry["task_yielding"]),
            expected_task_count=int(entry["expected_task_count"]),
            conjunction_single_intent=bool(entry["conjunction_single_intent"]),
            source_scripts=tuple(str(value) for value in entry["source_scripts"]),
            embedded_foreign_terms=tuple(
                str(value) for value in entry.get("embedded_foreign_terms", [])
            ),
        )
        for entry in raw["utterances"]
    )
    label_view = [
        {
            "n": utterance.n,
            "task_yielding": utterance.task_yielding,
            "expected_task_count": utterance.expected_task_count,
            "conjunction_single_intent": utterance.conjunction_single_intent,
        }
        for utterance in sorted(utterances, key=lambda item: item.n)
    ]
    return ReferenceCorpus(
        corpus_id=str(raw["corpus_id"]),
        version=int(raw["version"]),
        digest=_digest({"corpus_id": raw["corpus_id"], "labels": label_view}),
        utterances=utterances,
    )


# --- Run artifact (privacy-safe capture of one release run) -----------------


@dataclass(frozen=True)
class ProposalObservation:
    """One reviewed proposal reduced to privacy-safe signals."""

    title_sha256: str
    source_script: str
    title_script: str
    fidelity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title_sha256": self.title_sha256,
            "source_script": self.source_script,
            "title_script": self.title_script,
            "fidelity": self.fidelity,
        }


@dataclass(frozen=True)
class UtteranceRun:
    """Outcome of one isolated single-utterance operation (SC-002/003/004)."""

    utterance_n: int
    operation_ref: str
    proposal_count: int
    proposals: tuple[ProposalObservation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "utterance_n": self.utterance_n,
            "operation_ref": self.operation_ref,
            "proposal_count": self.proposal_count,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
        }


@dataclass(frozen=True)
class FullRecordingRun:
    """Outcome of the single end-to-end sealed recording (SC-001/007)."""

    operation_ref: str
    proposal_count: int
    committed_task_count: int
    seal_to_awaiting_confirmation_seconds: float
    seal_to_commit_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_ref": self.operation_ref,
            "proposal_count": self.proposal_count,
            "committed_task_count": self.committed_task_count,
            "seal_to_awaiting_confirmation_seconds": (
                self.seal_to_awaiting_confirmation_seconds
            ),
            "seal_to_commit_seconds": self.seal_to_commit_seconds,
        }


@dataclass(frozen=True)
class RunIdentity:
    git_sha: str
    corpus_id: str
    corpus_digest: str
    provider_config: dict[str, str]

    @property
    def provider_config_digest(self) -> str:
        return _digest(self.provider_config)

    @property
    def run_key(self) -> str:
        """Stable identity of this run: the exact SHA + corpus + provider config."""

        return _digest(
            {
                "git_sha": self.git_sha,
                "corpus_digest": self.corpus_digest,
                "provider_config_digest": self.provider_config_digest,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "git_sha": self.git_sha,
            "corpus_id": self.corpus_id,
            "corpus_digest": self.corpus_digest,
            "provider_config": self.provider_config,
            "provider_config_digest": self.provider_config_digest,
        }


@dataclass(frozen=True)
class RunArtifact:
    run_identity: RunIdentity
    full_recording: FullRecordingRun | None
    utterances: tuple[UtteranceRun, ...]
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_identity": self.run_identity.to_dict(),
            "full_recording": (
                self.full_recording.to_dict() if self.full_recording else None
            ),
            "utterances": [utterance.to_dict() for utterance in self.utterances],
        }


def run_artifact_to_dict(artifact: RunArtifact) -> dict[str, Any]:
    return artifact.to_dict()


def run_artifact_from_dict(raw: Mapping[str, Any]) -> RunArtifact:
    """Load a recorded run-artifact (deterministic CI path, no provider calls)."""

    if int(raw.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError("Unsupported Voice Brain Dump run-artifact schema version")
    identity_raw = raw["run_identity"]
    identity = RunIdentity(
        git_sha=str(identity_raw["git_sha"]),
        corpus_id=str(identity_raw["corpus_id"]),
        corpus_digest=str(identity_raw["corpus_digest"]),
        provider_config={
            str(key): str(value)
            for key, value in dict(identity_raw["provider_config"]).items()
        },
    )
    full_raw = raw.get("full_recording")
    full_recording = (
        FullRecordingRun(
            operation_ref=str(full_raw["operation_ref"]),
            proposal_count=int(full_raw["proposal_count"]),
            committed_task_count=int(full_raw["committed_task_count"]),
            seal_to_awaiting_confirmation_seconds=float(
                full_raw["seal_to_awaiting_confirmation_seconds"]
            ),
            seal_to_commit_seconds=(
                float(full_raw["seal_to_commit_seconds"])
                if full_raw.get("seal_to_commit_seconds") is not None
                else None
            ),
        )
        if full_raw is not None
        else None
    )
    utterances = tuple(
        UtteranceRun(
            utterance_n=int(entry["utterance_n"]),
            operation_ref=str(entry["operation_ref"]),
            proposal_count=int(entry["proposal_count"]),
            proposals=tuple(
                ProposalObservation(
                    title_sha256=str(proposal["title_sha256"]),
                    source_script=str(proposal["source_script"]),
                    title_script=str(proposal["title_script"]),
                    fidelity=str(proposal["fidelity"]),
                )
                for proposal in entry.get("proposals", [])
            ),
        )
        for entry in raw.get("utterances", [])
    )
    return RunArtifact(
        run_identity=identity,
        full_recording=full_recording,
        utterances=utterances,
        schema_version=SCHEMA_VERSION,
    )


# --- Live mode: project persisted operation artifacts into a RunArtifact -----


def _observe_proposals(
    operation: BrainDumpOperationDocument,
) -> tuple[int, list[ProposalObservation]]:
    """Reduce an operation's active proposals to privacy-safe observations.

    The raw title is used only in-process to compute its SHA-256 and its
    language-fidelity verdict against the cited segment text; it never enters the
    returned observation.
    """

    segment_text = {segment.id: segment.text for segment in operation.segments}
    observations: list[ProposalObservation] = []
    active = [
        proposal
        for proposal in operation.proposals
        if not proposal.deleted and not _is_tombstoned(proposal)
    ]
    for proposal in active:
        source_text = " ".join(
            segment_text[segment_id]
            for segment_id in proposal.source_segment_ids
            if segment_id in segment_text
        )
        fidelity = classify_title_fidelity(proposal.title, source_text)
        observations.append(
            ProposalObservation(
                title_sha256=hashlib.sha256(proposal.title.encode("utf-8")).hexdigest(),
                source_script=fidelity.source_script.value,
                title_script=fidelity.title_script.value,
                fidelity=fidelity.verdict.value,
            )
        )
    return len(active), observations


def _is_tombstoned(proposal: Any) -> bool:
    successors = getattr(proposal, "successor_ids", None)
    return bool(successors)


def _operation_ref(operation: BrainDumpOperationDocument) -> str:
    return hashlib.sha256(operation.id.encode("utf-8")).hexdigest()[:16]


def seal_to_confirmation_latency(operation: BrainDumpOperationDocument) -> float:
    """Derive the sealed → awaiting-confirmation latency from provider runs.

    Seal is the earliest persisted provider-run checkpoint; awaiting confirmation
    is the last successful provider run's update. Both are timestamps already on
    the durable operation record, so the derivation stays privacy-safe (one
    float) and needs no extra instrumentation.
    """

    runs = list(operation.provider_runs)
    if not runs:
        return 0.0
    seal = min(run.created_at for run in runs)
    completed = [run for run in runs if run.status == "succeeded"]
    awaiting = max(run.updated_at for run in (completed or runs))
    return max(0.0, (awaiting - seal).total_seconds())


def build_run_artifact_from_operations(
    *,
    git_sha: str,
    corpus: ReferenceCorpus,
    provider_config: Mapping[str, str],
    full_recording_operation: BrainDumpOperationDocument | None,
    utterance_operations: Mapping[int, BrainDumpOperationDocument],
    seal_to_commit_seconds: float | None = None,
) -> RunArtifact:
    """Project a live run's persisted operations into a privacy-safe artifact."""

    identity = RunIdentity(
        git_sha=git_sha,
        corpus_id=corpus.corpus_id,
        corpus_digest=corpus.digest,
        provider_config={
            str(key): str(value) for key, value in provider_config.items()
        },
    )
    full_recording: FullRecordingRun | None = None
    if full_recording_operation is not None:
        proposal_count, _ = _observe_proposals(full_recording_operation)
        full_recording = FullRecordingRun(
            operation_ref=_operation_ref(full_recording_operation),
            proposal_count=proposal_count,
            committed_task_count=len(full_recording_operation.committed_task_ids),
            seal_to_awaiting_confirmation_seconds=seal_to_confirmation_latency(
                full_recording_operation
            ),
            seal_to_commit_seconds=seal_to_commit_seconds,
        )
    utterance_runs: list[UtteranceRun] = []
    for utterance_n in sorted(utterance_operations):
        operation = utterance_operations[utterance_n]
        proposal_count, observations = _observe_proposals(operation)
        utterance_runs.append(
            UtteranceRun(
                utterance_n=utterance_n,
                operation_ref=_operation_ref(operation),
                proposal_count=proposal_count,
                proposals=tuple(observations),
            )
        )
    return RunArtifact(
        run_identity=identity,
        full_recording=full_recording,
        utterances=tuple(utterance_runs),
    )


# --- Scoring: RunArtifact + ReferenceCorpus -> report -----------------------


@dataclass(frozen=True)
class CriterionResult:
    criterion: str
    passed: bool
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class OperationalEvidenceReport:
    run_key: str
    git_sha: str
    corpus_id: str
    corpus_digest: str
    corpus_version: int
    provider_config_digest: str
    coverage: dict[str, int]
    criteria: tuple[CriterionResult, ...]
    schema_version: int = SCHEMA_VERSION

    @property
    def all_passed(self) -> bool:
        return all(result.passed for result in self.criteria)

    def criterion(self, name: str) -> CriterionResult:
        for result in self.criteria:
            if result.criterion == name:
                return result
        raise KeyError(name)

    def _content(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_key": self.run_key,
            "git_sha": self.git_sha,
            "corpus_id": self.corpus_id,
            "corpus_digest": self.corpus_digest,
            "corpus_version": self.corpus_version,
            "provider_config_digest": self.provider_config_digest,
            "coverage": self.coverage,
            "criteria": [result.to_dict() for result in self.criteria],
        }

    @property
    def report_id(self) -> str:
        """Content address of this report: identical inputs yield identical id."""

        return _digest(self._content())

    def to_dict(self) -> dict[str, Any]:
        return {"report_id": self.report_id, **self._content()}


def _sc003_translated(utterances: Iterable[UtteranceRun]) -> tuple[int, int]:
    translated = total = 0
    for utterance in utterances:
        for proposal in utterance.proposals:
            total += 1
            if proposal.fidelity == FidelityVerdict.TRANSLATED.value:
                translated += 1
    return translated, total


def compute_operational_evidence(
    artifact: RunArtifact, corpus: ReferenceCorpus
) -> OperationalEvidenceReport:
    """Score a run artifact against the reference corpus into the SC report.

    Pure and deterministic: no provider calls, no time source, no filesystem. A
    recorded artifact and a live artifact are scored identically, so CI verifies
    the computation while a real run supplies the live numbers.
    """

    if artifact.run_identity.corpus_digest != corpus.digest:
        raise ValueError(
            "Run artifact corpus digest does not match the reference corpus; "
            "evidence must be anchored to the exact corpus it was captured against."
        )

    by_number = corpus.by_number()
    scored = [
        utterance
        for utterance in artifact.utterances
        if utterance.utterance_n in by_number
    ]

    # SC-002: a task-yielding utterance is a single-correct hit when it yielded
    # exactly one proposal and no proposal was translated out of its language.
    task_yielding = [
        utterance
        for utterance in scored
        if by_number[utterance.utterance_n].task_yielding
    ]
    sc002_hits = sum(
        1
        for utterance in task_yielding
        if utterance.proposal_count == 1
        and all(
            proposal.fidelity != FidelityVerdict.TRANSLATED.value
            for proposal in utterance.proposals
        )
    )
    sc002_total = len(task_yielding)
    sc002_ratio = sc002_hits / sc002_total if sc002_total else 0.0

    # SC-003: proposal titles translated out of their source language, corpus-wide.
    sc003_translated, sc003_titles = _sc003_translated(scored)

    # SC-004: single-intent utterances split into more than one proposal.
    conjunction = [
        utterance
        for utterance in scored
        if by_number[utterance.utterance_n].conjunction_single_intent
    ]
    sc004_false_splits = sum(
        1 for utterance in conjunction if utterance.proposal_count > 1
    )

    # SC-001 / SC-007: from the single full-recording operation.
    full = artifact.full_recording
    sc001_committed = full.committed_task_count if full else 0
    sc007_latency = full.seal_to_awaiting_confirmation_seconds if full else None

    criteria = (
        CriterionResult(
            criterion="SC-001",
            passed=full is not None and sc001_committed >= SC001_MIN_COMMITTED_TASKS,
            detail={
                "committed_task_count": sc001_committed,
                "threshold": SC001_MIN_COMMITTED_TASKS,
                "has_full_recording": full is not None,
            },
        ),
        CriterionResult(
            criterion="SC-002",
            passed=sc002_total > 0 and sc002_ratio >= SC002_MIN_SINGLE_CORRECT_RATIO,
            detail={
                "single_correct_hits": sc002_hits,
                "task_yielding_total": sc002_total,
                "ratio": round(sc002_ratio, 4),
                "threshold": SC002_MIN_SINGLE_CORRECT_RATIO,
            },
        ),
        CriterionResult(
            criterion="SC-003",
            passed=sc003_translated == 0,
            detail={
                "translated_titles": sc003_translated,
                "titles_total": sc003_titles,
            },
        ),
        CriterionResult(
            criterion="SC-004",
            passed=sc004_false_splits == 0,
            detail={
                "conjunction_false_splits": sc004_false_splits,
                "conjunction_eligible": len(conjunction),
            },
        ),
        CriterionResult(
            criterion="SC-007",
            passed=(
                sc007_latency is not None
                and sc007_latency <= SC007_MAX_SEAL_TO_CONFIRMATION_SECONDS
            ),
            detail={
                "seal_to_awaiting_confirmation_seconds": sc007_latency,
                "threshold_seconds": SC007_MAX_SEAL_TO_CONFIRMATION_SECONDS,
            },
        ),
    )

    return OperationalEvidenceReport(
        run_key=artifact.run_identity.run_key,
        git_sha=artifact.run_identity.git_sha,
        corpus_id=corpus.corpus_id,
        corpus_digest=corpus.digest,
        corpus_version=corpus.version,
        provider_config_digest=artifact.run_identity.provider_config_digest,
        coverage={
            "utterances_scored": len(scored),
            "utterances_in_corpus": len(corpus.utterances),
        },
        criteria=criteria,
    )
