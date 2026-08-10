# Business Intake: [FEATURE NAME]

**Feature**: `specs/[###-feature-name]/`
**Interviewed**: [date]
**Interviewee**: [who answered]

<!--
  Produced by /speckit-interview before /speckit-specify. This is the record of
  what the human actually agreed to, in their own terms. It is not a
  specification: no schemas, no endpoints, no module boundaries. Where a
  heading did not apply, say why — never delete the heading.
-->

## The ask, as given

> [The human's original words, verbatim. Do not paraphrase — this is the only
> line they can check against their own memory.]

## 1. Problem

- **Whose problem**: [persona or role]
- **How it shows up today**: [the concrete current experience]
- **What it costs**: [time, errors, abandoned work, support load]
- **If we build nothing**: [what continues to happen]

## 2. Customer and persona

- **Primary**: [who]
- **Secondary**: [who, or none]
- **Deployment shape**: [single-user | multi-tenant | team] — this changes the
  compliance and scale answers, so state it explicitly.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| [what improves] | [number] | [number] | [date] |

These become the `SC-###` success criteria. An objective with no number
produces a spec the acceptance auditor cannot grade.

## 4. Scope boundary

**In scope**

- [ ] [capability]

**Out of scope — explicitly confirmed by the human**

- [ ] [what we are deliberately not building, and why]

<!--
  Non-goals are the highest-value answers in the interview. Both lists were
  read back and confirmed; record the confirmation, not an assumption.
-->

**Confirmed by**: [name] on [date]

## 5. Constraints

- **Deadline**: [date or none]
- **Platform**: [web | mobile | both]
- **Offline behavior**: [required | best-effort | not applicable]
- **Must not break**: [existing contracts, flows, integrations]
- **Budget / provider cost limits**: [if any]

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management —
profile/email/password, ZIP data export, 14-day-grace deletion and purge — and
is never feature-flagged (see `docs/data-retention.md`). Record what **this
feature adds** to that baseline.

- **New durable records**: [what gets stored]
- **Consent**: [what needs consent, where it is captured, how revoked]
- **Retention**: [how long, deleted by what trigger]
- **Export**: [included in the ZIP export | deliberately excluded, because …]
- **Purge**: [covered by account purge | needs purge extension]
- **Residency / other obligations**: [if any]

## 7. Existing-system dependencies

- **Backend surfaces**: [services, modules]
- **Frontend surfaces**: [canvas, inspector, …]
- **Mobile**: [must change | unaffected]
- **AI providers**: [used | not used]
- **Primary loop impact**: [how this affects capture → atomic items →
  clarify/approve → route or CRT candidate → Weekly Review → evidence, or an
  explicit "no impact"]

## 8. Definition of done

What the human wants to see to believe it works. Observable, not "it works":

- [ ] [observable outcome]

## Deferred to /speckit-clarify

- [ ] [question the human could not answer yet, and what blocks the answer]

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| [—] | [—] | [—] | [—] |
