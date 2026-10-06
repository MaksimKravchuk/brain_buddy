# Persistence/migration contract and proposed Identity ADR

**Decision status**: proposed, part of this reviewed artifact digest. Promote to ADR-0028 only after accountable planning acceptance; no accepted ADR is rewritten. Identity remains the existing modular-monolith authority (ADR-0001). This narrowly replaces its file-backed auth assumption and invite-only ordinary onboarding; task owners/opaque sessions/operator scope/grace semantics remain.

## Store facade

AuthStore extends neutral SQLiteRepositorySupport with WAL, foreign_keys, busy_timeout, secure_delete and thread-local transaction reuse. Inject the same store into UserRepository, SessionRepository and auth metadata. Preserve constructor/method signatures via optional injected store and identical model results. BEGIN IMMEDIATE serializes authority writes across connections/processes. Every indexed field/preserved payload is changed together.

Existing user facade get/create/mutate/update_email/update_profile/delete/list remains. save becomes UPDATE-only/NotFound, seeding fresh-mutates instead of stale upsert. Session facade preserves hashed opaque cookie CRUD/revocation; imported expiry/token hashes unchanged. Foreign keys enforce real account/session relationships. No JSON fallback if DB fails.

## Import prerequisites

Existing nonempty users/sessions root does not silently import during ordinary startup. Operator must drain/stop every old API/CLI writer against the volume; old code does not know new locks. CLI migration explicitly records this prerequisite and runs before new readiness. Empty roots initialize directly. Migration needs configured persistent backup/credential key through secret storage; no secret output/argument value.

Deployment sequence is an approved maintenance/migration step, not normal rolling overlap. Default release gates are unchanged; do not mutate Fly or disable protection ad hoc to execute it. A nonempty-root deployment without completed migration fails readiness visibly. Rehearse on synthetic copy before production approval.

## Import transaction/checkpoints

1. Acquire exclusive migration lock. Inventory expected credential/journal files only; reject unexpected unsafe file/ID/path forms. Validate _profile_transaction.json before applying existing prepared=old/committed=new recovery semantics. Never recover malformed arbitrary journal payload.
2. Read every canonical user file, preserve unknown model fields, validate filename/id/timestamps/normalized email. Reject malformed, duplicate IDs/normalized emails and unexplained divergence from independently reconstructed _by_email.json. Do not trust index as authority or silently repair it.
3. Validate every session/file token-hash relationship. Classify expired/orphaned sessions as revoked; record nonsecret counts. Malformed entries abort, not skip. Keep valid ID/hash/expiry data; legacy email verification remains null.
4. Create access-restricted AEAD encrypted <=24-hour backup with measured manifest/count/content verification. No permanent plaintext staging/archive or printed personal records. Any precommit failure leaves original authority intact and readiness stopped.
5. In one SQLite transaction import users/sessions and ledger. Check foreign keys/integrity and measured counts/content digests before commitment. Fail atomically on discrepancy. Other-module owner IDs are unchanged.
6. After verified commit SQLite is authoritative. Remove original user/session/index/journal credential copies idempotently; do not touch unrelated module data. Mark cleanup complete only after removal read-back. Crash resumes cleanup, never reimports or rolls back to old files. Readiness remains blocked until cleanup succeeds.
7. Remove entire aggregate backup on any account purge or at TTL. Startup/periodic sweep retries bounded cleanup; no remaining plaintext credential copies. Record only checkpoint/count/coarse failure events.

## Rollback boundary

Before import commit, old image/files remain usable while writes are stopped. After new auth writes resume, normal rollback must use an auth.sqlite3-capable binary. Old JSON image or preimport backup would discard later bindings/resets/deletions and can resurrect access; never deploy it as automatic rollback. Restoring backup is separately reviewed data recovery with explicit loss boundary, not ordinary release fallback. The first transition uses a migration-aware fail-closed guard plus explicit containment/forward repair, not a new legacy storage mode. Implement the guard in scripts/auth_migration_guard.py and the capture/pre-mutation/failure paths of .github/workflows/deploy-fly-production.yml. A trusted read-only stdlib probe inspects the volume's authoritative import ledger and coarse running-image storage capability; it emits only schema epoch/commit/cleanup/capability, never records or credentials. Verify that the observed running image matches the captured immutable image; unknown/unreachable/malformed evidence is unsafe, not "no migration".

Before mutation record actual captured images/capability and exact-SHA candidate migration/parity evidence. Immediately before any automatic backend restore, re-read the authoritative ledger, including a commit that happened after capture. A committed Identity epoch refuses a JSON-only or unverified captured backend image; the workflow stays failed and never restores preimport files. A validated SQLite-capable captured image may be selected and restored by the actual existing rollback step. Frontend rollback is permitted only with the compatible existing password contract.

When the first transition has no compatible previous image, perform explicit containment: keep migrated volume intact, drain/stop failing backend writers, report migration checkpoint/correlation and failed deployment, and retain local native work. Restore service by forward repair built from the committed-epoch code, green exact-SHA CI, recorded ASK landing and the normal release workflow. Redeploying the failed candidate is not called a rollback or success. Backup restoration stays separately approved data recovery. Rehearse the real failure-handler command path after import commit, source cleanup and resumed auth writes; its guard must prevent unsafe image restoration in every case.

## Authority operations

- Fresh-read account/version/session/current reservation/deletion marker, validate exact purpose/client/proof, conditional consume, mutation/revocation and allowed session issuance commit together. Password verification snapshot hash/version must still match. No known-owner missing/past-due proof can recreate a new account.
- Invalid-code counters commit before generic exception, so rollback cannot refund guesses. Send/resend budgets persist and are never refunded on transport failure. External I/O always outside writes, with leases/CAS and bounded timeout/cleanup.
- Admin/legacy email edits atomically clear verification/old-address authority; admin cannot strand email-only passwordless user. Name-only edits preserve verification. Reserved-config change revokes/denies external-origin sessions and pending proof, never elevates them.
- Past-due marker precedes cross-module purge and user removal remains last. New auth rows/jobs cascade on final delete; Apple failure cannot block local purge. Session/grant replacement and provider cleanup are generation-aware.

## Keys/retention

Configure versioned 32-byte auth master keyring outside DB/data directory; derive separate HMAC-code/HMAC-budget/AEAD labels through HKDF, never reuse agent-relay private repository/key authority. Pin key ID/AAD to kind/attempt/binding/owner/client/generation. New ciphertext uses current key; previous key IDs support existing decrypt/budget windows during controlled rotation. Missing key fails the affected method safely while password/data erasure remain available; no random restart key or plaintext fallback.

Proof/code/attempt payload expires <=10 min; recent grants <=5 min; callback grant <=60 s. Temporarily encrypted mail payload erased after once-only dispatch/failure. Apple cleanup <=5 attempts/24 h, capped by purge; active binding retains only revocation-required grant. Budget fingerprints <=24 h, notices <=8 days, encrypted migration backup <=24 h or any purge. Export excludes all secrets/fingerprints. secure_delete and bounded WAL truncate reduce local remnants; no forensic platform-snapshot promise.

## Required tests

Migration parity for IDs/hashes/cookies/owners; prepared/committed journals; corrupt/duplicate/divergent/unknown-field fixtures; crash before commit/after commit/during cleanup/repeated init; no reimport/resurrection/fallback; two-connection/process unique claims and proof consume; stale password login vs reset/purge; failed-counter persistence and resend/restart; operator configuration elevation/admin last-method protection; bounded backup/secret erasure; Apple outage/lease/generation/purge; export exclusion. Replace JSON-count tests rather than letting empty old directories satisfy them.
