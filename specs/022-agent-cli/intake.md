# Business Intake: Agent-friendly BrainBuddy CLI

Interviewed: 2026-10-06. Interviewee: Maksim Kravchuk, current Codex conversation.
Status: Scope agreed with distribution extension; terminal design approval pending.

## The ask, as given

> Так, нам нужен универсальный command line tool для Brain нижнее подчеркивание Buddy. Это моя репа, поищи, у тебя есть к ней доступ. Что я имею в виду? Так как у меня AI Focus, command line — это очень удобный интерфейс для AI. И вообще нужно посмотреть, как сделать так, чтобы этот command line был оптимизирован для AI tooling'а, чтобы агентам было удобно его использовать и решать какие-то задачи пользователя. Вот такой command line нам нужен. По оптимизации по токенам. Давай ебанем его, не знаю, там на Rust'е. Если я правильно понимаю, растовские приложения работают везде прекрасно, на всех платформах.

Follow-up scope answer, verbatim:

> Нужны также готовые сборки и установка одной командой

## 1. Problem

Agents need terminal access to BrainBuddy. Today the repository has an internal administration CLI but no general member HTTP client. Ad hoc HTTP integration repeats API discovery, quoting and verbose output costs. Without this feature that work remains duplicated.

## 2. Customer and persona

Primary: AI agents acting on the owner's explicit instructions. Secondary: the owner and scripts. A local client connects to the existing owner-scoped multi-account server; no new tenancy model.

## 3. Business objective and KPI

The owner requested agent usability and token optimization. Proposed engineering acceptance proxies: one command per task create/search/edit/complete step, zero execution prompts and at least 60% smaller default output in UTF-8 bytes for a synthetic 20-task page. Token measurements must name the tokenizer; byte reduction is not token reduction. These numeric thresholds are implementation acceptance proposals, not claimed owner-supplied numbers.

## 4. Scope boundary

The owner was shown the proposed Rust bb binary, task/project/tag/tree commands, universal member JSON API command, compact JSON, field selection, stdin, discovery, dry-run, explicit revisions/idempotency and existing sessions. The owner selected the option extending this scope with ready-made builds and one-command installation.

In scope: that client plus native release archives, checksums, Unix/PowerShell installers and release validation.

Retained non-goals from the presented proposal: offline synchronization, new MCP/TUI, server/web/iOS changes or new authentication. The former proposal to exclude distribution is superseded by the owner's answer. Platform architecture limits and code-signing exclusions are technical first-release assumptions, stated in spec.md.

## 5. Constraints

Rust is preferred. Support Linux, macOS and Windows through separate native builds, not one binary for all OSes. No deadline was given. Business commands require network; discovery and dry-run are offline. Existing ownership, transitions, consent, flags, revisions and idempotency stay authoritative. No new paid provider evaluation is needed.

## 6. Compliance obligation

No new server stores. The client retains no user-content cache or credentials. Existing account export, deletion and retention cover server data created by requested operations. Sessions come from a protected input file or environment. External-processing consent remains explicit; generic API access cannot infer it. No new content destination beyond the configured BrainBuddy server.

## 7. Existing-system dependencies

Existing member HTTP and session contracts; existing OpenAPI endpoint. Server, frontend and iOS implementations are unchanged. Distribution adds isolated CLI build automation and release assets, subject to existing least-privilege/approval rules. No new AI provider. The primary loop gains terminal capture, clarification, action and inspection; review/relay remain existing gated workflows.

## 8. Definition of done

Observable acceptance: disposable-account task journey with duplicate-create prevention and stale-edit rejection; compact/full/selected output and preserved pagination; offline discovery and redacted preview; critical structured failures; reproducible output-size comparison; native checks for five build targets; versioned installer success and integrity rejection; reviewed exact-commit release evidence and actual published installer smoke. Implementation and production release are distinct statuses.

## Deferred to /speckit-clarify

No unanswered business question. Terminal design requires the explicit repository-mandated owner approval before planning; this record does not invent that approval.

## Contradictions surfaced during the interview

Distribution changed from a proposed exclusion to required scope at the owner's request. Cross-platform Rust still needs OS-specific builds.
