# Delivery report: 023-modern-auth

**Branch**: `feat/modern-auth`  **Verified implementation input**: `29411eba1fa0f6f13e54ec55b29635b1169100ff`

> Rendered with `scripts/render_feature_report.py --stdout`, then reconciled against the actual review and execution artifacts. Historical reviewer inputs and degraded provenance are preserved. A stage that did not run is stated explicitly. Final evidence-only additions do not relabel tests as a later commit or public CI.

---

### 1-2. The ask and what was agreed

`intake.md` is present.

**The ask, as given**

> Давай ты сделаешь тогда нормальную систему авторизации, ну, ты уже в принципе все описал, что нужно. Давай ее планировать и имплементировать.

Earlier owner statements establish three priorities:

> я хочу, чтобы там уже сейчас была авторизация через Google, через Apple и через email.

> я в Европе

> я не хочу за это платить.

OpenAI was mentioned as a possible additional method, not a required launch method. The owner described the current product as an early MVP and wanted less approval friction. This is recorded as a preference for low operational friction, not as approval of unseen design or review artifacts.

The owner added during preparation:

> Важно, что базовая авторизация в MacOS приложении сейчас подъедет из другого как бы чата. Я её через Cloud уже имплементирую.

The other chat owns baseline macOS authentication. This work must preserve compatible backend password/session contracts and coordinate any necessary native contract additions; it must not duplicate or overwrite that Mac implementation. The identity scope here remains web and iOS unless the owner changes it.

**4. Scope boundary**

**In scope — confirmed playback**

- Google and Apple sign-in, on web and iOS, with provider identity verification.
- Email sign-in using a short-lived one-use code; successful verification creates an account or signs into the existing one. Existing email/password login continues to work.
- Ordinary onboarding without invites or manual account approval, with abuse controls and existing reserved operator-address protections.
- Self-service password recovery and verified email changes for existing users.
- Explicit linking/unlinking of login methods, after confirming account ownership; prevent removal of the last usable method and never merge accounts solely because provider emails match.
- Sensitive account actions remain available without a password through recent proof of account ownership. Data export and the existing deletion/grace/purge lifecycle include the new identity records safely.
- Web and iOS show configured login methods and actionable retry/cancellation/error states. iOS preserves local tasks, account binding and pending changes when login fails or a session expires.
- Configuration guide for the required provider applications and email delivery, plus an updated privacy/retention inventory and meaningful auth regression tests.

**Out of scope — explicitly confirmed by the human**

- OpenAI login for the first release; it was optional in the owner request.
- A paid authentication SaaS, billing changes, team accounts, enterprise SSO, new roles or access to another user's content.
- Passkeys and mandatory MFA in this slice; these require a separate accepted scope.
- Implementing baseline macOS authentication in this branch: the owner is implementing it in another chat. Adding the new social/email-code UI to Mac, redesigning tasks/voice/Weekly Review or changing AI processing consent is also outside this proposed slice.
- Purchasing an Apple Developer membership, an email plan or a domain; no new paid service may be silently required or provisioned.
- Claiming legal GDPR certification, signing processor agreements or publishing a release before the required release approval.

**Confirmed by**: product owner on 2026-10-06, after the numbered scope/non-goals playback and Google/Apple setup explanation: "Да. Все есть". This confirms the described scope and provider-account availability; it is not represented as approval of a future unseen design or planning-review digest.

The owner first asked what Google and Apple setup requires. After the explanation and the membership question, "Да. Все есть" confirmed scope and availability of the accounts, including Apple membership. Exact credentials and mail sender settings must still be configured through secret storage.

**3. Business objective and KPI**

The numerical targets below are proposed release acceptance measures, not fabricated business measurements or owner-approved conversion targets.

| metric | baseline today | proposed target | by when |
|---|---|---|---|
| Supported primary login methods | 1: email/password | 3: Google, Apple, email code; existing password login retained | candidate release |
| Invite approvals required for ordinary onboarding | 1 invite required | 0 | candidate release |
| Existing account IDs and owned data preserved through rollout | current account/data fixtures | 100% of migration and regression fixtures | candidate release |
| Cross-account access granted by invalid login/link attempts | security invariant | 0 in the negative acceptance cases | candidate release |
| Mandatory new subscription for the authentication service | none today | €0/month | candidate release |

No adoption deadline or post-release conversion target was supplied by the owner.


### 3-4. What was specified and designed

**Spec**: [spec.md](spec.md) — 33 requirements (FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, FR-011, FR-012, FR-013, FR-014, FR-015, FR-016, FR-017, FR-018, FR-019, FR-020, FR-021, FR-022, FR-023, FR-024, FR-025, SC-001, SC-002, SC-003, SC-004, SC-005, SC-006, SC-007, SC-008)

**Design**: [design.md](design.md), with the [interactive auth prototype](design/auth.html) — 13 screen/state ids (D-01, D-02, D-03, D-04, D-05, D-06, M-01, M-02, M-03, M-04, M-05, M-06, M-07)

### Technical plan

`plan.md` is present (131 lines).


### 5. What review found

Two planning campaigns ran under the original `022-modern-auth` feature identity. The first escalated with all six reviews unavailable; it did not approve implementation. The second initially requested changes, then all six actual lenses passed after recorded corrections: requirements, architecture, testability, privacy/security, UX/accessibility/mobile, and adversarial risk. The first campaign recorded six unavailable reviews after401 failures. The second campaign initially requested changes; all six final lens verdicts are approve, at the retained planning digest. Final gate: **approved**, digest recorded in [planning-review.json](planning-review.json).

All six final lenses have **degraded, model-unverified provenance** through the declared collaboration transport; `panel_correlated` is null and no verified separate model oracles are claimed. Default CLI attempts failed with 401 before producing reviews. See [review-execution.md](review-execution.md) and the verbatim [final review files](reviews/c2-final/). The mechanical renumbering to 023 preserves those historical identities and digests; [renumbering-review.json](renumbering-review.json) records its independent bounded audit.

No unresolved product decisions or missing final reviewers were recorded. Standing owner authorization covers this isolated implementation and mandatory review without another routine approval; it does not claim personal inspection of technical findings, production credentials, a migrated live store or approval of a release SHA. Design approval and its limitations are recorded in [design.md](design.md). There is no founder-accepted gate record.


### 6. Task decomposition

`tasks.md` records 44 tasks; **40 are checked**. T043 local writer-receipt work is complete, with independent receipt/code/QA/readiness inspection. T033, T041, T042 and T044 retain incomplete required native-device/current CI/formal acceptance/publication/release evidence. No missing required lane is marked complete.



### 7. What was built

Google, Apple and one-use email codes for web/iOS, while existing password accounts, session cookies and native password callers retain their contract. Registration through configured modern methods does not require an invitation. Recovery, verified email changes, recent ownership proof, explicit method linking/removal, passwordless export/deletion, and bounded Apple cleanup are implemented in the existing self-hosted backend. No paid auth SaaS was introduced.

The current implementation candidate is `29411eba1fa0f6f13e54ec55b29635b1169100ff`, integrated with public main `143f1e813a466a7a000cd1f7e39bf4aae06c268d`. Its seven incoming commits include native Weekly Review and the latest 30 Mac-spec documents. Mac PR265 was inspected at `1e63e42acb3206980cc66b297eee315f1893dcb7` and rechecked before delivery: GitHub reports it closed on 2026-10-06T17:57:59Z without a PR merge. Its 30-file spec package is already present in the integrated main. The other chat retains ownership of Mac implementation. Modern workspace completion reuses the new common account-linking conversion and guards cancellation afterward. Three real engine/server regressions prove parks remain Someday and prevent credential submission on failed/cancelled local preparation.

Implementation locations and bounded deviations are listed in [verification.md](verification.md). The auth inventory is 167 changed paths against the integrated main; source manifests distinguish incoming main work from this feature.

### 8. What was verified

At exact integrated `29411eba1fa0f6f13e54ec55b29635b1169100ff`, the fresh browser chain passed **65 legacy +14 modern cases**, one optional external-model test skipped, zero flaky cases or retries. All 80 records passed taxonomy, 79 executed cases passed freshness and the six required native-product stories had meaningful evidence. Real application/SQLite/session/signature paths used isolated signed synthetic Google/Apple upstreams and SMTP capture; live configured providers were not exercised.

Ten actual headed Chromium 151 interactions at 1440×1000 and 390×851 reached visible pending feedback within **16.2 ms maximum**, with one dispatch, disabled duplicate controls, visible keyboard focus, 44 CSS-pixel targets and no horizontal overflow. Fourteen masked screenshots and fourteen Axe summaries were retained; zero violations were reported, but three account-surface scans each retain one incomplete check. Root and the independent reviewer actually inspected current [mobile](evidence/local-29411eb/mobile-pending-email.png) and [desktop](evidence/local-29411eb/desktop-pending-email.png) pending-email screenshots. See the [independent browser QA](reviews/final-implementation/modern-auth-browser-qa-29411eb.json). These are bounded web checks, not physical native or full accessibility certification.

Legacy CRT keeps its original budgets and actual 294 identifier: 120 raw samples, 104.5 ms aggregate p95, 119/120 within 200 ms against the required 114. Each operation p95 is at most 134.6 ms. The earlier failed budget measurement remains historical evidence rather than being overwritten.

The complete frontend passed **1,726 tests / 74 files** in 425.30 s, with taxonomy and unchanged floors: 98.99% statements / 97.83% branches / 98.76% functions / 99.51% lines. The fresh complete **`make verify-all` passed with exit 0**. Backend: **4,324 passed** in 1,325.76 s, 98.61% lines / 95.86% branches, taxonomy 4,324; all immutable floors passed. The 167 frozen feature paths matched before and after execution. See the [actual aggregate](evidence/local-29411eb/aggregate-summary.json) and [source manifest](evidence/local-29411eb/source-manifest.json).

| Coverage | Actual | Unchanged minimum |
|---|---:|---:|
| Backend lines | 98.61% | 98.47% |
| Backend branches | 95.86% | 95.61% |
| Frontend statements | 98.99% | 98.76% |
| Frontend branches | 97.83% | 97.77% |
| Frontend functions | 98.76% | 98.64% |
| Frontend lines | 99.51% | 98.84% |

The [complete local Swift package suite](evidence/local-29411eb/native-summary.json) at exact 294 passed: framework summary **776 tests / 74 suites / 56.959 s**, including all five modern workspace cases. One opt-in live-backend endpoint test and its suite were skipped. The older merged source failed all three new workspace regressions before the repair. All 160 native source/script hashes were verified before and after the green run. Default Docker container creation first failed with ENOSPC; the actual canonical script used its supported `SWIFT_IMAGE` override with preserved official Swift 6.2.4 compiler/runtime in the package bind mount and a small original Ubuntu runtime image. The adaptation, failed pre-test attempts and immutable provenance are retained. This is local full-package evidence, not current Xcode, public CI or physical-device evidence.

Requirement-to-test trace coverage passed **33/33**; named traceability does not establish full feature acceptance. The completed prior `630e812` aggregate and all earlier failures remain recorded in [verification.md](verification.md) with their actual input SHAs. No result is relabelled as a later documentation commit, production run or skipped required lane.

### 9. Independent review and acceptance

Planning review remains approved at digest `270a94d7fb7b025144e6bdbc2292e78da3476e11fae8aaaf82e2df12c8652bdd` with the recorded degraded, model-unverified provenance. The [exact 294 bounded static review](reviews/final-implementation/modern-auth-final-code-review-29411eb-static-scan-safe.json) and [independent native follow-up](reviews/final-implementation/modern-auth-final-code-review-29411eb-native-followup.json) approve the changed code with zero new concrete findings. The static artifact is an explicitly recorded scan-safe serialization derivative: one misleading historical hash-field name was renamed; reverse-normalized content equals the immutable original, including verdict and source fingerprints. No scanner policy was widened. Their raw artifacts are preserved; this is not full feature or production acceptance. Historical request-changes findings and closures are retained, including the deac retention-scheduling finding and its 056252d repair approval. Original implementation reviews remain: 5fc4 requested changes, 8f3 Apple-focused approval, e4e requested changes, df94 bounded approval (with model-unverified provenance), deac requested changes, 056/850/630 bounded approval, 294 static/native/browser approval. No failed runtime or empty Claude response is counted as an assessment.

Formal acceptance: **not run**, explicitly recorded in [acceptance.md](acceptance.md). The [speckit-accept instruction](../../.specify/agent-commands/speckit-accept/SKILL.md#preconditions) requires “Stop and say so if any is unmet” and every task checked; four required evidence tasks remain incomplete. The accepted workflow requires all tasks and mandatory delivery evidence before grading. Native UI/device, live configured providers, public disclosure inputs and current exact-SHA CI remain incomplete. The [independent33-row readiness audit](reviews/final-implementation/modern-auth-acceptance-readiness-29411eb.json) records **19 covered / 13 weak / 1 missing**,50 representative inspected test references, current local counts and validated four-gate writer receipt. [Traceability](traceability.md) is byte-preserved reviewer output. It remains **not_ready / not_graded**, distinct from a formal acceptance verdict.

### 10. Delivery and remaining work

ASK review destination: [draft PR270](https://github.com/MaksimKravchuk/brain_buddy/pull/270). Its public head remains `4439c003f63ef501df8c5ae6e582e95531be239e`; current local repairs are not uploaded. Automatic approval review rejected uploading auth code/tests/spec to this public repository because explicit permission for this payload and public destination was not established. The specific publication decision remains pending; the blocked action has not been retried. No main merge, live migration or deployment is claimed.

For launch, the actual Google/Apple applications, SMTP configuration, production keyring/origins and controller/provider disclosures must be verified; current `ios-kit`/`ios-app` CI and supported native-device checks remain required. [Operations guide](../../docs/modern-auth-operations.md) gives the concrete setup and rollback steps. Production smoke, intended audience and exact deployed SHA are **not run/unverified**.

Existing out-of-scope issue `BASELINE-TASK-ACK-SYNC-001` remains P2: an intervening sync can make a valid task-save acknowledgement fail revision verification. It was independently reproduced in unchanged baseline code. A passing browser repeat does not repair it or prove the exact ordering of the earlier failed run. Original failures and the reproduction are preserved in verification/readiness evidence.

The [typed writer receipt](pre-freeze-writer-receipt.json) was actually validated at implementation input294 and independently inspected. Final delivery-document additions are separate from that input: product, test, build and runtime sources remain unchanged. Their later documentation commit does not turn this local result into exact-SHA public CI or release evidence. The prepared local Git bundle retains the real merge history and feature scope; publication remains blocked as stated above.
