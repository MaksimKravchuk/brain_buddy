"""Operational evidence report for the multilingual Voice Brain Dump release (T035).

This produces a privacy-safe, hash-addressed capture→review→commit report keyed
to the exact git SHA, the reference-corpus digest, and the provider/model
configuration, computing the release success criteria:

* SC-001 — committed task count from the reference recording (≥15).
* SC-002 — task-yielding utterances yielding a *correct* proposal set (≥80%).
  Correctness is a real oracle, not a same-script singleton: the proposal count
  must equal the corpus's ``expected_task_count`` (crediting a correctly-split
  multi-task utterance), no title may be translated out of its source language,
  every title must share grounded content with the cited utterance, and all
  required embedded code-switch terms must be preserved. The single authoritative
  denominator is the corpus's task-yielding count. See ``compute_operational_
  evidence`` for exactly what the oracle does and does not check.
* SC-003 — proposal titles translated out of their source language (must be 0).
* SC-004 — single-intent utterances false-split on a conjunction (must be 0).
* SC-007 — seal → awaiting-confirmation latency for the recording (≤120s).

Every criterion is stamped with the ``evidence_mode`` that produced it, because
the corpus has no per-utterance audio: SC-001/SC-007 come from the full sealed
recording (``sealed_audio_pipeline``), while SC-002/003/004 are driven through
the real reconciler at the text level (``text_reconciler``) — honest
real-provider evidence, clearly not full-pipeline.

Producers share one scorer (``compute_operational_evidence``):

* **Live harness** — ``scripts/voice_evidence_report.py`` drives the real API and
  reconciler, assembling section runs via the pair-based builders
  (``build_full_recording_run`` / ``build_utterance_run`` / ``build_run_artifact``)
  and the API-response reader ``titled_sources_from_operation_response``.
* **Persisted operations** — ``build_run_artifact_from_operations`` projects a
  run's persisted ``BrainDumpOperationDocument`` artifacts into a ``RunArtifact``.
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
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.workflows.voice_brain_dump.domain import BrainDumpOperationDocument
from app.workflows.voice_brain_dump.language_fidelity import (
    FidelityVerdict,
    classify_title_fidelity,
)

# v2 adds the SC-002 correctness-oracle signals (``grounded_in_source`` per
# proposal, ``required_terms_preserved`` per utterance) and the per-section
# ``evidence_modes`` provenance. v1 artifacts predate the strengthened oracle
# and are intentionally not loadable.
SCHEMA_VERSION = 2

# Evidence-mode vocabulary: which real pipeline produced a section's numbers.
MODE_SEALED_AUDIO_PIPELINE = "sealed_audio_pipeline"
MODE_TEXT_RECONCILER = "text_reconciler"

SC001_MIN_COMMITTED_TASKS = 15
SC002_MIN_CORRECT_RATIO = 0.80
SC007_MAX_SEAL_TO_CONFIRMATION_SECONDS = 120.0

# A title token must be at least this long to carry grounding weight; shorter
# tokens are function words shared across unrelated commands.
_GROUND_MIN_LENGTH = 4
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _content_tokens(text: str) -> list[str]:
    return [
        token.casefold()
        for token in _WORD_RE.findall(text)
        if len(token) >= _GROUND_MIN_LENGTH
    ]


def _stem_equal(first: str, second: str) -> bool:
    """Morphology-tolerant token equality (shared ≥4-char dominant stem).

    Mirrors ``reconciler._tokens_equivalent`` so the oracle's grounding notion
    matches the reconciler's: exact match, or a shared leading stem of at least
    four characters that is at least 60% of the longer token (unifies Russian
    inflection like ``создай``/``создать`` without conflating distinct words).
    """

    if first == second:
        return True
    common = 0
    for left, right in zip(first, second, strict=False):
        if left != right:
            break
        common += 1
    return common >= 4 and common * 5 >= max(len(first), len(second)) * 3


def _shares_grounded_content(title: str, source_text: str) -> bool:
    """Whether ``title`` shares a substantial content word with its cited source.

    A minimal, deterministic grounding oracle: at least one ≥4-char title token
    matches (up to inflection) a token of the cited utterance. It rules out an
    arbitrary same-script singleton that names nothing the utterance said, while
    tolerating the grounded rewording FR-006 permits. It is weaker than the
    reconciler's full grounding (no clause binding), which is fine — the
    reconciler already rejected ungrounded titles upstream; this is corpus-level
    corroboration, not a second gate.
    """

    title_tokens = _content_tokens(title)
    source_tokens = _content_tokens(source_text)
    if not title_tokens or not source_tokens:
        return False
    return any(
        _stem_equal(title_token, source_token)
        for title_token in title_tokens
        for source_token in source_tokens
    )


def _terms_preserved(titles: Sequence[str], required_terms: Sequence[str]) -> bool:
    """Whether every required embedded code-switch term survives in some title."""

    haystack = " ".join(titles).casefold()
    return all(term.casefold() in haystack for term in required_terms)


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
    """One reviewed proposal reduced to privacy-safe signals.

    ``grounded_in_source`` records, at capture time, whether the raw title shared
    a substantial content word with its cited utterance — an SC-002 correctness
    signal computed while the title is in hand so the artifact need never carry
    it.
    """

    title_sha256: str
    source_script: str
    title_script: str
    fidelity: str
    grounded_in_source: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "title_sha256": self.title_sha256,
            "source_script": self.source_script,
            "title_script": self.title_script,
            "fidelity": self.fidelity,
            "grounded_in_source": self.grounded_in_source,
        }


@dataclass(frozen=True)
class UtteranceRun:
    """Outcome of one isolated single-utterance operation (SC-002/003/004).

    ``required_terms_preserved`` records whether the corpus utterance's required
    embedded code-switch terms all survived in some proposal title — the second
    SC-002 correctness signal, likewise computed at capture time.
    """

    utterance_n: int
    operation_ref: str
    proposal_count: int
    proposals: tuple[ProposalObservation, ...]
    required_terms_preserved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "utterance_n": self.utterance_n,
            "operation_ref": self.operation_ref,
            "proposal_count": self.proposal_count,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "required_terms_preserved": self.required_terms_preserved,
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
    evidence_modes: dict[str, str] = field(default_factory=dict)
    """Which real pipeline produced each section: ``full_recording`` and
    ``utterances`` map to a value from the ``MODE_*`` vocabulary. The report
    echoes these onto each criterion so a reader can tell full-pipeline evidence
    (SC-001/007, sealed audio) from text-reconciler evidence (SC-002/003/004),
    which is honest because there is no per-utterance audio in the corpus."""
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_identity": self.run_identity.to_dict(),
            "evidence_modes": self.evidence_modes,
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
                    grounded_in_source=bool(proposal["grounded_in_source"]),
                )
                for proposal in entry.get("proposals", [])
            ),
            required_terms_preserved=bool(entry["required_terms_preserved"]),
        )
        for entry in raw.get("utterances", [])
    )
    return RunArtifact(
        run_identity=identity,
        full_recording=full_recording,
        utterances=utterances,
        evidence_modes={
            str(key): str(value)
            for key, value in dict(raw.get("evidence_modes", {})).items()
        },
        schema_version=SCHEMA_VERSION,
    )


# --- Live capture: reduce titles + provenance into a privacy-safe artifact ---
#
# A "titled source" is a ``(title, cited_source_text)`` pair. Both the persisted
# operation path and the harness's live API/text-reconciler paths reduce to
# these pairs, so one observer produces privacy-safe signals for every mode. The
# raw title/source are used only in-process to derive a SHA-256, the fidelity
# verdict, and the grounding signal; none of them enter the artifact.
TitledSource = tuple[str, str]


def _observe_title(title: str, source_text: str) -> ProposalObservation:
    fidelity = classify_title_fidelity(title, source_text)
    return ProposalObservation(
        title_sha256=hashlib.sha256(title.encode("utf-8")).hexdigest(),
        source_script=fidelity.source_script.value,
        title_script=fidelity.title_script.value,
        fidelity=fidelity.verdict.value,
        grounded_in_source=_shares_grounded_content(title, source_text),
    )


def observe_titles(
    titled_sources: Sequence[TitledSource], *, required_terms: Sequence[str] = ()
) -> tuple[int, tuple[ProposalObservation, ...], bool]:
    """Reduce reviewed titles to (count, observations, required_terms_preserved)."""

    observations = tuple(
        _observe_title(title, source_text) for title, source_text in titled_sources
    )
    preserved = _terms_preserved(
        [title for title, _source in titled_sources], required_terms
    )
    return len(observations), observations, preserved


def _ref(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]


def build_full_recording_run(
    *,
    operation_id: str,
    titled_sources: Sequence[TitledSource],
    committed_task_count: int,
    seal_to_awaiting_confirmation_seconds: float,
    seal_to_commit_seconds: float | None = None,
) -> FullRecordingRun:
    proposal_count, _observations, _preserved = observe_titles(titled_sources)
    return FullRecordingRun(
        operation_ref=_ref(operation_id),
        proposal_count=proposal_count,
        committed_task_count=committed_task_count,
        seal_to_awaiting_confirmation_seconds=seal_to_awaiting_confirmation_seconds,
        seal_to_commit_seconds=seal_to_commit_seconds,
    )


def build_utterance_run(
    *,
    utterance_n: int,
    operation_id: str,
    titled_sources: Sequence[TitledSource],
    corpus_utterance: CorpusUtterance,
) -> UtteranceRun:
    proposal_count, observations, preserved = observe_titles(
        titled_sources, required_terms=corpus_utterance.embedded_foreign_terms
    )
    return UtteranceRun(
        utterance_n=utterance_n,
        operation_ref=_ref(operation_id),
        proposal_count=proposal_count,
        proposals=observations,
        required_terms_preserved=preserved,
    )


def build_run_artifact(
    *,
    git_sha: str,
    corpus: ReferenceCorpus,
    provider_config: Mapping[str, str],
    full_recording: FullRecordingRun | None,
    utterances: Sequence[UtteranceRun],
    evidence_modes: Mapping[str, str],
) -> RunArtifact:
    """Assemble a RunArtifact from pre-built section runs (harness entry point)."""

    return RunArtifact(
        run_identity=RunIdentity(
            git_sha=git_sha,
            corpus_id=corpus.corpus_id,
            corpus_digest=corpus.digest,
            provider_config={
                str(key): str(value) for key, value in provider_config.items()
            },
        ),
        full_recording=full_recording,
        utterances=tuple(sorted(utterances, key=lambda run: run.utterance_n)),
        evidence_modes={str(key): str(value) for key, value in evidence_modes.items()},
    )


def titled_sources_from_operation_response(
    operation: Mapping[str, Any],
) -> list[TitledSource]:
    """Extract ``(title, cited_source_text)`` pairs from a brain-dump API response.

    Reads a ``BrainDumpOperationResponse`` JSON as returned to the authenticated
    owner. Only active proposals (not deleted, not superseded) are included; each
    title is paired with the concatenated text of its cited transcript segments.
    Used by the live harness so it can build the artifact straight from the API
    without reconstructing a persisted document.
    """

    segment_text = {
        str(segment["id"]): str(segment.get("text", ""))
        for segment in operation.get("segments", [])
    }
    pairs: list[TitledSource] = []
    for proposal in operation.get("proposals", []):
        if proposal.get("deleted") or proposal.get("successor_ids"):
            continue
        source_text = " ".join(
            segment_text[segment_id]
            for segment_id in proposal.get("source_segment_ids", [])
            if segment_id in segment_text
        )
        pairs.append((str(proposal["title"]), source_text))
    return pairs


def seal_manifest_hash(chunks: Sequence[Mapping[str, Any]]) -> str:
    """Manifest hash a seal expects: sha256 of the compact ordered chunk metadata.

    Mirrors ``service._brain_dump_manifest_hash`` exactly (sorted keys, ``(",",
    ":")`` separators, ordered by ``chunk_number``) so the harness can seal a
    real operation. Pinned against the service by a test.
    """

    encoded = json.dumps(
        [
            {
                "chunk_number": int(chunk["chunk_number"]),
                "sha256": str(chunk["sha256"]),
                "size_bytes": int(chunk["size_bytes"]),
            }
            for chunk in sorted(chunks, key=lambda item: int(item["chunk_number"]))
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_tombstoned(proposal: Any) -> bool:
    successors = getattr(proposal, "successor_ids", None)
    return bool(successors)


def seal_to_confirmation_latency(operation: BrainDumpOperationDocument) -> float:
    """Derive the sealed → awaiting-confirmation latency from provider runs.

    Seal is the earliest persisted provider-run checkpoint; awaiting confirmation
    is the last successful provider run's update. Both are timestamps already on
    the durable operation record, so the derivation stays privacy-safe (one
    float). The harness prefers a wall-clock measurement around the seal→poll
    loop and only falls back to this when reconstructing from a persisted doc.
    """

    runs = list(operation.provider_runs)
    if not runs:
        return 0.0
    seal = min(run.created_at for run in runs)
    completed = [run for run in runs if run.status == "succeeded"]
    awaiting = max(run.updated_at for run in (completed or runs))
    return max(0.0, (awaiting - seal).total_seconds())


def _operation_titled_sources(
    operation: BrainDumpOperationDocument,
) -> list[TitledSource]:
    segment_text = {segment.id: segment.text for segment in operation.segments}
    active = [
        proposal
        for proposal in operation.proposals
        if not proposal.deleted and not _is_tombstoned(proposal)
    ]
    return [
        (
            proposal.title,
            " ".join(
                segment_text[segment_id]
                for segment_id in proposal.source_segment_ids
                if segment_id in segment_text
            ),
        )
        for proposal in active
    ]


def build_run_artifact_from_operations(
    *,
    git_sha: str,
    corpus: ReferenceCorpus,
    provider_config: Mapping[str, str],
    full_recording_operation: BrainDumpOperationDocument | None,
    utterance_operations: Mapping[int, BrainDumpOperationDocument],
    seal_to_commit_seconds: float | None = None,
) -> RunArtifact:
    """Project a live run's persisted operations into a privacy-safe artifact.

    Both sections are full sealed-audio-pipeline evidence here (they come from
    real operations). The harness uses the pair-based builders instead when its
    per-utterance section is text-reconciler evidence.
    """

    full_recording: FullRecordingRun | None = None
    if full_recording_operation is not None:
        full_recording = build_full_recording_run(
            operation_id=full_recording_operation.id,
            titled_sources=_operation_titled_sources(full_recording_operation),
            committed_task_count=len(full_recording_operation.committed_task_ids),
            seal_to_awaiting_confirmation_seconds=seal_to_confirmation_latency(
                full_recording_operation
            ),
            seal_to_commit_seconds=seal_to_commit_seconds,
        )
    utterance_runs = [
        build_utterance_run(
            utterance_n=utterance_n,
            operation_id=utterance_operations[utterance_n].id,
            titled_sources=_operation_titled_sources(utterance_operations[utterance_n]),
            corpus_utterance=corpus.by_number()[utterance_n],
        )
        for utterance_n in sorted(utterance_operations)
        if utterance_n in corpus.by_number()
    ]
    return build_run_artifact(
        git_sha=git_sha,
        corpus=corpus,
        provider_config=provider_config,
        full_recording=full_recording,
        utterances=utterance_runs,
        evidence_modes={
            "full_recording": MODE_SEALED_AUDIO_PIPELINE,
            "utterances": MODE_SEALED_AUDIO_PIPELINE,
        },
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

    # SC-002 correctness oracle. The denominator is the corpus's task-yielding
    # count (the single authoritative denominator). A task-yielding utterance is
    # a correct hit only when ALL of the following hold — a stricter test than an
    # arbitrary same-script singleton:
    #   1. proposal_count == the corpus's expected_task_count (right number of
    #      tasks; credits a correctly-split multi utterance, not just singletons),
    #   2. no proposal was translated out of the source language (FR-006),
    #   3. every proposal shares grounded content with the cited utterance
    #      (rules out an invented/off-topic title), and
    #   4. all required embedded code-switch terms were preserved.
    # What it does NOT check: an exact canonical title string (the corpus carries
    # no per-utterance gold title), full semantic equivalence beyond token
    # grounding + term preservation, or non-title fields (due date, priority,
    # context) which are out of the title's scope.
    task_yielding = [
        utterance
        for utterance in scored
        if by_number[utterance.utterance_n].task_yielding
    ]
    sc002_hits = 0
    sc002_misses = {
        "count_mismatch": 0,
        "translated": 0,
        "ungrounded": 0,
        "missing_required_terms": 0,
    }
    for utterance in task_yielding:
        expected = by_number[utterance.utterance_n].expected_task_count
        if utterance.proposal_count != expected:
            sc002_misses["count_mismatch"] += 1
        elif any(
            proposal.fidelity == FidelityVerdict.TRANSLATED.value
            for proposal in utterance.proposals
        ):
            sc002_misses["translated"] += 1
        elif not all(proposal.grounded_in_source for proposal in utterance.proposals):
            sc002_misses["ungrounded"] += 1
        elif not utterance.required_terms_preserved:
            sc002_misses["missing_required_terms"] += 1
        else:
            sc002_hits += 1
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

    full_mode = artifact.evidence_modes.get("full_recording", "unknown")
    utterance_mode = artifact.evidence_modes.get("utterances", "unknown")

    criteria = (
        CriterionResult(
            criterion="SC-001",
            passed=full is not None and sc001_committed >= SC001_MIN_COMMITTED_TASKS,
            detail={
                "committed_task_count": sc001_committed,
                "threshold": SC001_MIN_COMMITTED_TASKS,
                "has_full_recording": full is not None,
                "evidence_mode": full_mode,
            },
        ),
        CriterionResult(
            criterion="SC-002",
            passed=sc002_total > 0 and sc002_ratio >= SC002_MIN_CORRECT_RATIO,
            detail={
                "correct_hits": sc002_hits,
                "task_yielding_total": sc002_total,
                "ratio": round(sc002_ratio, 4),
                "threshold": SC002_MIN_CORRECT_RATIO,
                "miss_breakdown": sc002_misses,
                "oracle": (
                    "count==expected AND language-faithful AND grounded content "
                    "AND required embedded terms preserved"
                ),
                "evidence_mode": utterance_mode,
            },
        ),
        CriterionResult(
            criterion="SC-003",
            passed=sc003_translated == 0,
            detail={
                "translated_titles": sc003_translated,
                "titles_total": sc003_titles,
                "evidence_mode": utterance_mode,
            },
        ),
        CriterionResult(
            criterion="SC-004",
            passed=sc004_false_splits == 0,
            detail={
                "conjunction_false_splits": sc004_false_splits,
                "conjunction_eligible": len(conjunction),
                "evidence_mode": utterance_mode,
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
                "evidence_mode": full_mode,
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
