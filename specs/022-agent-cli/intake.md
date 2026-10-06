# Business Intake: Agent-friendly BrainBuddy CLI

Interviewed: 2026-10-06. Interviewee: Maksim Kravchuk, current Codex conversation.
Status: Distribution and convenient shared authentication requested; revised terminal design approval pending.

## The ask, as given

> Так, нам нужен универсальный command line tool для Brain нижнее подчеркивание Buddy. Это моя репа, поищи, у тебя есть к ней доступ. Что я имею в виду? Так как у меня AI Focus, command line — это очень удобный интерфейс для AI. И вообще нужно посмотреть, как сделать так, чтобы этот command line был оптимизирован для AI tooling'а, чтобы агентам было удобно его использовать и решать какие-то задачи пользователя. Вот такой command line нам нужен. По оптимизации по токенам. Давай ебанем его, не знаю, там на Rust'е. Если я правильно понимаю, растовские приложения работают везде прекрасно, на всех платформах.

Follow-up scope answer, verbatim:

> Нужны также готовые сборки и установка одной командой

Additional steering, verbatim:

> Ах да, я забыл. Авторизация у нас должна быть еще какая-то же у этого ком онлайн клиента. У нас сейчас там в разработке в параллельной сессии есть какая-то работа над авторизацией общей через Google, Apple и еще что-то, и этот пароль для ком онлайн клиента тоже нужна какая-то удобная авторизация. Не уверен такая. Я здесь не шерю.

## 1. Problem

Agents need terminal access to BrainBuddy. Today the repository has an internal administration CLI but no general member HTTP client. Ad hoc HTTP integration repeats API discovery, quoting and verbose output costs. Without this feature that work remains duplicated.

## 2. Customer and persona

Primary: AI agents acting on the owner's explicit instructions. Secondary: the owner and scripts. A local client connects to the existing owner-scoped multi-account server; no new tenancy model.

## 3. Business objective and KPI

The owner requested agent usability and token optimization. Proposed engineering acceptance proxies: one command per task create/search/edit/complete step, zero execution prompts and at least 60% smaller default output in UTF-8 bytes for a synthetic 20-task page. Token measurements must name the tokenizer; byte reduction is not token reduction. These numeric thresholds are implementation acceptance proposals, not claimed owner-supplied numbers.

## 4. Scope boundary

The owner was shown the proposed Rust bb binary, task/project/tag/tree commands, universal member JSON API command, compact JSON, field selection, stdin, discovery, dry-run, explicit revisions/idempotency and existing sessions. The owner selected the option extending this scope with ready-made builds and one-command installation.

In scope: that client plus native release archives, checksums, Unix/PowerShell installers, release validation and convenient login integrated with shared account authentication. Browser/device authorization, headless approval and OS credential storage are agent-proposed technical/UX defaults, not protocol choices asserted on the owner's behalf.

Retained non-goals: offline synchronization, new MCP/TUI, unrelated server business changes or web/iOS redesign. Excluding distribution and authentication is superseded. CLI authorization support and the shared-auth approval surface are now integration dependencies. Provider login/account linking remain owned by the parallel shared-auth work. Platform architecture limits and code-signing exclusions are technical first-release assumptions, stated in spec.md.

## 5. Constraints

Rust is preferred. Support Linux, macOS and Windows through separate native builds, not one binary for all OSes. No deadline was given. Business commands require network; discovery and dry-run are offline. Existing ownership, transitions, consent, flags, revisions and idempotency stay authoritative. No new paid provider evaluation is needed.

## 6. Compliance obligation

The client retains no user-content cache or passwords. It stores a separate server/account-bound CLI credential in the OS credential store; protected-file storage requires an explicit choice. Device approvals/CLI credentials require bounded server retention, account-purge coverage and revocation in the shared-auth contract. Existing account export/deletion rules remain authoritative. External-processing consent remains explicit; generic API access cannot infer it. No new content destination beyond the configured BrainBuddy/shared authentication system.

## 7. Existing-system dependencies

Existing member HTTP/OpenAPI contracts plus the parallel Google/Apple/shared-auth work. CLI authorization support and browser approval must reuse that account authority. No provider integration or account-linking implementation is duplicated here. Distribution adds isolated CLI build automation and release assets, subject to existing least-privilege/approval rules. No new AI provider. The primary loop gains terminal capture, clarification, action and inspection; review/relay remain existing gated workflows.

## 8. Definition of done

Observable acceptance: browser/headless login and protected credential reuse, status/logout/revocation and denied/expired/storage-unavailable recovery; disposable-account task journey with duplicate-create prevention and stale-edit rejection; compact/full/selected output and preserved pagination; offline discovery/redacted preview; critical structured failures; reproducible output-size comparison; native checks for five targets; installer integrity and actual published-release smoke. Implementation and production release are distinct statuses.

## Deferred to /speckit-clarify

No protocol question is escalated to the owner: the owner explicitly said they were unsure which authentication to choose. Updated terminal/login design still requires the repository-mandated owner approval before planning. The unpublished shared-auth/CLI authorization contract is a technical integration dependency, not a claim that the owner's parallel work does not exist.

## Contradictions surfaced during the interview

Distribution and then convenient authentication changed from proposed exclusions to required scope at the owner's request. Avoiding all credential persistence is superseded by protected reusable CLI credentials. Cross-platform Rust still needs OS-specific builds.
