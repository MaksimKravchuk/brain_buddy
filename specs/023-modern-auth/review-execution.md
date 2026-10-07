# Planning review execution evidence

**Campaign**: modern-auth-20261006-c1, 2026-10-06.
**Artifact digest**: 9fd7ea2418a64fa1f8f95403dae7c9cf808d1ef14a806db10984fea44b20a24c.
**Actual result**: [planning-review.json](planning-review.json), escalated, zero of six mandatory lenses produced a review. This is not a technical approval or an implementation authorization.

The deterministic preflight passed and derived high risk from auth/privacy/storage paths. Requirements-consistency and privacy-consent-security process launches were rejected by automatic approval review: transferring the private authentication planning artifacts to the Codex reviewer's network-backed process lacked specifically confirmed destination/data-transfer authorization. No workaround or indirect model execution was used after that rejection.

Architecture-consistency, testability-evidence and UX-accessibility-mobile launch attempts exited before review with an in-process app-server initialization error, Read-only file system. The adversarial lens was not attempted while the same launch blockers remained. Summarization truthfully recorded all six missing reviews.

Read-only diagnosis (no project prompt/model call) traced the runtime failure to the child Linux namespace uid_map operation, not application code or credentials. An escalated initialization-only test then successfully received app-server initialize response. This fixes the local bootstrap condition; it does not grant data-transfer permission or establish a successful model review. Codex's reviewer remains configured read-only by the unchanged repository harness.

After the prepared spec/plan/contracts and relevant-code transfer scope was explicitly presented, the owner authorized and required Codex/OpenAI review without further involvement: "Конечно ... ты его обязан делать без меня". This standing authorization was received before launching campaign two, not inferred from elapsed time or UX approval. Secrets/.env/user data remain excluded. Campaign two must record actual model provenance/findings/acceptance; campaign one remains in history with its true escalated result.

Independent local artifact checks: six design-validator tests passed; gate integrity passed (16 files, 46 invariants); all planning links exist and all 25 requirements are mapped in design/state/server invariants. Full spec artifact checking remains incomplete at this phase because tasks follow the planning gate. No product auth code, provider configuration, data migration or deployment was performed.

## Campaign two runtime evidence

Campaign `modern-auth-20261006-c2` used the same artifact digest. All five default CLI lenses exited before producing model output: HTTP 401 on the Codex responses endpoint and a token-refresh error stating the CLI login session had been invalidated. Initialization alone had succeeded; no successful planning review is inferred from it. The adversarial CLI attempt was omitted because the same shared credential failure applied. These attempts remain failed, not passes.

ADR-0025 permits an explicitly reviewed, hash-pinned external adapter. Separate collaboration sessions are now performing the actual read-only lenses from the exact unchanged harness prompts under `requests/`; their verbatim JSON responses will be bound to prompt SHA-256 and artifact digest. A temporary read-only transport executable performs no model call and invents no review; it passes those actual responses through the unchanged harness for schema, provenance and artifact-drift validation. An independent reviewer must inspect the transport before use. Provider/model identity is unverified and correlated; this route cannot claim cross-provider independence. This is a declared replacement runtime attempt within campaign two, not a hidden CLI retry or a third campaign.

## Corrected campaign-two verdict

The actual initial c2 result was technical-changes-required, six of six lenses. Original schema/provenance-bearing results are retained in reviews/c2-initial; c1 remains escalated with zero model results. Root fixed the recorded defects. The same six reviewer sessions verified those specific corrections and the final narrow interrupted-link clarification; no new fresh campaign or relitigation was launched. All six confirmed the final artifact digest 270a94d7fb7b025144e6bdbc2292e78da3476e11fae8aaaf82e2df12c8652bdd with pass/no remaining findings. Actual final results are in reviews/c2-final and planning-review.json.

The reviewed/pinned transport measured SHA256 fddafaf5f807d990b64f5521dab4f53fda526f90a38f0f1363f93fed9dfacfbf. Its model identity remains unverified/correlated; no verified multi-provider agreement is claimed. Failed CLI attempts were not converted into successes.

The human sign-off records the owner's existing explicit implementation/scope/UX authorization and instruction to do mandatory reviews without further involvement, bound to this corrected plan. It is not a claim of personal inspection of reviewer findings or live release/migration approval. The unchanged aggregator returned approved. Product code, native compile, migration, configured-provider smoke and production acceptance remain future work.
