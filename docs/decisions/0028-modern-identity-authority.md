# ADR-0028: One transactional Identity authority and additive login proofs

Date: 2026-10-06
Status: Accepted for the owner-authorized implementation scope; technical decision by the implementing agent
Supersedes: ADR-0001 only where Identity assumes JSON-backed accounts/sessions and invite-only ordinary onboarding
Related: ADR-0008, ADR-0017, ADR-0021, spec 022

Google, Apple and email codes must grant access to the same immutable account as
the existing password login. A consumed proof, account mutation and session
issuance cannot be independently committed to several JSON files. Adding a
sidecar identity store would require cross-store recovery at every sensitive
operation and leave duplicate authority during failures.

Identity therefore owns one `auth.sqlite3`, behind the existing user/session
repository interfaces. A shared transaction rechecks the current account,
version, session, owner and proof purpose before consuming authority and
changing credentials or sessions. Indexed uniqueness and foreign keys enforce
the same rules across processes. Other modules keep their current storage and
immutable owner IDs. HTTP cookie/password/Me contracts and shared native Mac
interfaces remain compatible.

Ordinary new onboarding uses a verified provider/mailbox proof without an
invite. Existing unverified password addresses are not retroactively trusted:
their holder first proves the current password and mailbox. Matching provider
email never links an account. Operators retain the reserved password-only path.
Empty password hashes mean unset; dummy verification equalizes cost but cannot
authenticate a passwordless account.

Nonempty legacy roots require an explicit stopped-writer, validated import.
After one committed import, SQLite is authoritative; original credential copies
are removed before readiness, with a short-lived encrypted recovery backup.
There is no fallback, dual write or rolling overlap with JSON writers. The
actual release failure handler rechecks the storage epoch and refuses a JSON
or unverified backend rollback. First-transition failure without a compatible
previous image contains access and needs exact-SHA forward repair; it remains a
failed deployment. Restoring preimport data is a separate recovery decision.

New methods use configured provider/mail services directly and maintained free
JOSE/cryptography libraries. No new auth-service subscription is introduced.
Versioned keys remain outside persisted data; proofs, mail payloads, Apple
cleanup and abuse records have the bounded retention in spec 022. Provider
cleanup cannot extend local purge. Export contains safe personal metadata and
no usable credential.

The owner confirmed the concrete scope and rendered UX, requested implementation
and required routine work/reviews to proceed autonomously. This record does not
assert a live provider configuration, successful native build, legal
certification, production migration or approved release SHA. Those outcomes
still require their actual acceptance evidence.
