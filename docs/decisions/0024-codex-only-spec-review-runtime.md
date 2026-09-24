# ADR-0024: The portable spec review gate uses Codex only

Date: 2026-09-19
Status: Accepted by the product owner
Supersedes: ADR-0011, ADR-0012 and ADR-0014 only where they assign planning-review lenses to Claude or define Claude fallback behavior
Related: ADR-0011 (portable review stage), ADR-0012 (risk and gate integrity), ADR-0014 (recorded degradation)

## Context

The repository's planning review campaign assigned three standard lenses and the high-risk adversarial lens to the `claude` CLI. This environment does not provision that CLI. A real feature review therefore failed before those lenses could produce evidence, while a Codex process continued until timeout. The gate was not portable in the environment where it is used.

Keeping an unavailable runtime in a mandatory gate creates a constant `escalated` result unrelated to artifact quality. A constant blocker trains operators to bypass the gate instead of improving the reviewed work.

## Decision

Every standard planning-review lens and the high-risk adversarial lens runs through the installed `codex` CLI using the configured review model and the existing read-only, ephemeral sandbox.

- `INTEGRATION_CLI` contains only `codex`.
- Every `ROLE_CONFIGS` entry uses `integration: codex`.
- There is no Claude fallback and no invocation of the `claude` executable.
- Dedicated rubric files under `.claude/agents/` remain rubric documents only; their directory name does not select a runtime.
- Missing Codex fails closed before a lens starts. A non-zero reviewer exit remains a hard evidence failure.
- Summarization recomputes deterministic preflight defects and ASK-risk from current artifacts; missing harness provenance escalates, so hand-written reviews cannot bypass the Codex-only gate.
- The five standard lenses, the high-risk adversarial lens, schema validation, provenance stamping, campaign cap, risk derivation and human-signoff rules remain unchanged.
- Summary provenance must report the resulting single-provider/correlated panel honestly. It must never describe the configured panel as cross-provider or independent.

## Consequences

**Positive:** The mandatory gate is executable with the repository's actual toolchain. One missing vendor CLI can no longer block every feature regardless of artifact quality. The runtime contract is simpler and testable.

**Accepted cost:** The panel is intentionally single-provider and model-correlated. Multiple lenses remain useful as distinct rubrics, not as independent model votes. Their agreement is weaker evidence than cross-provider review and the summary must say so. High-risk work still requires run-bound human sign-off in addition to the automated panel.

**Preserved history:** ADR-0014 remains the record of the former hybrid fallback and of historical review artifacts that may contain degraded Claude provenance. Readers and report rendering may continue to understand those records; new campaigns do not create them.

## Rejected alternatives

**Install Claude solely for the gate.** This adds an unavailable credentialed runtime and contradicts the owner's explicit decision that the repository does not use Claude.

**Keep Claude entries and manually skip failed lenses.** Missing mandatory evidence must escalate; silently shrinking the panel weakens the gate.

**Replace the gate with one unstructured review.** This loses the five constitutional lenses, structured findings, deterministic aggregation and traceable campaign evidence.