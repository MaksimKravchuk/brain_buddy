# Business Intake: Lean external-agent relay

**Feature**: `specs/006-external-agent-relay/`  
**Interviewed**: 2026-08-09 (retrospectively recorded after the portable pipeline was added to `main`)  
**Interviewee**: Max

This file records the already-ratified product intake. It does not claim that the newer `/speckit-interview` command ran before implementation.

## The ask, as given

> «Так, и давай задизайним вторую фичу, которая у нас там должна быть в брейнбаде в нашем. Это агенты, выполняющие простые поручения. Я думаю, что на текущий момент нам нужно начинать не с нашего собственного агента, потому что это большая задача, а, например, что-нибудь типа Гернес интеграции или Клод интеграции или какой-нибудь там любой другой агентской интеграции. То есть задумка такая, что если у тебя есть облачный какой-то агент, мы могли бы его пингануть каким-нибудь вебхуком, в случае, если на него назначена задача. И он бы побежал это выполнять. Что думаешь? Давай-ка разберись. Например, по-моему, в Гермесе есть уже вебхуки. Давай, мы разберемся, можно ли такое сделать, подходят ли они для такой задачи. И приложи мне дизайн пока в общем смысле, именно как бизнесовую фичу, как бы это могло выглядеть.»

## 1. Problem

- **Whose problem**: A BrainBuddy user who already operates an external cloud agent.
- **How it shows up today**: The user can keep a Task in BrainBuddy or operate the agent elsewhere, but cannot safely hand over a reviewed Task copy and monitor the external report from the Task.
- **What it costs**: Manual copying, lost Task↔run correlation, duplicate dispatch risk, and status claims that are difficult to distinguish from verified BrainBuddy facts.
- **If we build nothing**: External execution remains an untracked, provider-specific side process.

## 2. Customer and persona

- **Primary**: Single BrainBuddy owner connecting an agent they operate.
- **Secondary**: None in v1.
- **Deployment shape**: single-user product deployment with owner-scoped records; no shared connections or team collaboration.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| Ratified measurable release outcomes passing | 0/7 for this absent capability | 7/7 SC-001–SC-007 | before internal production rollout |
| Duplicate external starts across three identical confirmation replays | not applicable | 0 duplicates | before internal production rollout |
| Required honest run states distinguishable on web and iOS | 0/required set | all states in SC-002 | before internal production rollout |

These are release acceptance measures, not adoption forecasts. No production adoption baseline or target was supplied.

## 4. Scope boundary

**In scope**

- [x] Connect, test, rotate, recover, inspect, and disconnect one owner-scoped external-agent connection.
- [x] Review and dispatch one immutable Task copy to a tested connector with one stable run/idempotency identity.
- [x] Monitor authenticated ordered reports and route capability-gated reply/cancel commands.
- [x] Show honest server projections on web and iOS with bounded retention and owner isolation.
- [x] Stage the production feature to the internal cohort first.

**Out of scope — explicitly confirmed by the human**

- [x] BrainBuddy-managed universal agent runtime, hosting, tools, provider credentials, or output verification.
- [x] Automatic Task completion, planning/decomposition, accepted-work retry, marketplace, billing, multi-agent chains, or shared connections.
- [x] Broad polish and enterprise expansion that are not required for the minimum production slice.

**Confirmed by**: Max on 2026-08-09 through exact-spec ratification.

## 5. Constraints

- **Deadline**: No calendar deadline; release only after exact-SHA gates and explicit authority approvals.
- **Platform**: Web and iOS.
- **Offline behavior**: Cached status is explicitly potentially stale; reply/cancel/credential actions are disabled rather than queued.
- **Must not break**: Canonical Task ownership/lifecycle, existing capture and Weekly Review flows, owner isolation, session auth, account purge, and verified-trunk governance.
- **Budget / provider cost limits**: The user owns external-agent/provider costs; BrainBuddy v1 adds no provider billing.

## 6. Compliance obligation

- **New durable records**: Encrypted connection credentials/signing secret, connection metadata, immutable hand-off manifest, runs, events, commands/idempotency receipts, and coarse audit/cleanup metadata.
- **Consent**: The hand-off review lists exactly what leaves BrainBuddy and warns that the external copy is outside BrainBuddy deletion guarantees; sensitive connection operations require recent server-verified reauthentication.
- **Retention**: Relayed content expires within 30 days; permitted coarse audit/cleanup metadata within 90 days; late reports cannot revive expired content.
- **Export**: Covered by the existing account export only where the ratified feature contract permits; secret values are never exported.
- **Purge**: Existing account purge removes all owner feature data and key-backed credential material.
- **Residency / other obligations**: No new residency promise; ordinary deployment rejects private/metadata destinations and requires governed HTTPS egress.

## 7. Existing-system dependencies

- **Backend surfaces**: FastAPI auth/account services, owner-scoped repository pattern, feature flags, correlation IDs, Task snapshot port, SQLite persistence, and Fly deployment.
- **Frontend surfaces**: Account settings, Task list/detail, existing shell/navigation and React Query client.
- **Mobile**: Expo settings, Task detail/history/list summaries, session lifecycle and React Query client.
- **AI providers**: Not used by BrainBuddy; Hermes is a reference connector only.
- **Primary loop impact**: Adds an optional external-run evidence lane after a canonical Task already exists. It does not alter capture, Task lifecycle, Weekly Review, or Task completion authority.

## 8. Definition of done

- [x] A user can connect/test an agent without retrieving saved secrets.
- [x] A reviewed hand-off sends one immutable payload once across ambiguous retries.
- [x] Authenticated reports, blocked questions, replies, cancellation requests, terminal reports, silence, disconnect, and expiry remain distinguishable and honest.
- [x] Web and iOS expose the same server-owned projection and capability gates.
- [ ] Exact current SHA passes Full CI, Docker, E2E, independent review, ASK landing, internal Fly smoke, EAS/TestFlight, and the applicable App Store gates.

## Deferred to /speckit-clarify

- [x] Whether webhooks alone are authoritative: resolved no; signed events/polling provide the authoritative ordered projection.
- [x] Whether BrainBuddy owns execution quality: resolved no; the agent is user-operated and completion is only reported.
- [x] Whether v1 includes a managed runtime: resolved no.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| A webhook could assign and start work | Progress monitoring and trustworthy lifecycle are required | Webhook/HTTP dispatch is transport; BrainBuddy owns the Task↔run projection from authenticated ordered reports | Max, ratified spec |
| Begin with a named Hermes/Claude integration | The product should work with any user-operated cloud agent | Provider-agnostic BYOA protocol; Hermes remains only the reference connector | Max, ratified spec |
| “Agent executes the task” could imply verified completion | BrainBuddy cannot verify external work | UI says **Agent reported complete** and never completes the canonical Task | Max, ratified spec |
