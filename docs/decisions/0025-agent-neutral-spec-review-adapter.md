# ADR-0025: Agent-neutral Spec Kit review adapter without false model attestation

Date: 2026-09-19
Status: Accepted by the product owner
Supersedes: ADR-0024 only where it requires Codex as the *only* planning-review runtime; its default Codex route, fail-closed gate, and honest single-provider reporting remain.
Related: ADR-0011, ADR-0012, ADR-0014, ADR-0024

## Context

Spec Kit `v1.0.11` uses the upstream `generic` integration. Its planning-review
stage must also permit a reviewed agent-independent runtime. ADR-0024 removed an
unavailable mandatory Claude dependency by making Codex the only runtime; that
solved one environment but made the gate vendor-dependent again. The product
owner explicitly chose an agent-neutral review adapter before this migration
lands. Accepted decisions are narrowed by a new ADR rather than edited in place.

## Decision

Keep Codex as a supported **default**, not a mandatory dependency. Each review
lens may instead run through a single executable implementing `external-stdin-v1`:
read the complete prompt on stdin, return schema-valid review JSON on stdout,
and enforce read-only repository access in the adapter's own runtime. The caller
must supply a SHA-256 pin for the reviewed executable and a declared provider
and model; the harness resolves and hashes the executable **before** running it,
rejects any mismatch, and passes only a minimal environment allowlist. It
validates the review and stamps the executable path, measured hash, artifact
digest, and caller-declared labels. The harness recomputes the reviewed
artifact digest both before and after every lens; changed content discards the
verdict. A non-zero exit fails the lens; there is no silent runtime fallback.

The pin measures local adapter bytes, **not** the provider's actual model or the
safety of the adapter. Declared provider/model are explicitly unverified; these
lenses are marked degraded and cannot count as verified cross-provider evidence.
Summarization validates the complete adapter provenance shape, still escalates
missing or malformed evidence, detects artifact drift, and preserves high-risk
human sign-off. This is a reviewed operator choice of executable, not remote
cryptographic model attestation or an OS sandbox. Do not use an unreviewed
adapter or claim proof of independence from caller labels.

## Consequences

A machine without Codex can run the gate using a separately reviewed adapter
with an explicit pin, without changing the Spec Kit authoring integration.
There is no preinstalled universal adapter: the operator supplies and reviews
one for the runtime they actually use. A missing runtime without a configured
adapter still fails closed. The default Codex panel remains correlated; external
panels carry weaker, explicitly labelled provenance. Future attested provider
identity would require a separate protocol and decision.
