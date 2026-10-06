# Task MCP intake

Date: 2026-10-06. Source: the owner's request to add MCP task creation/deletion
for GPT and independently write the documentation. The owner explicitly deferred
review and adjacent capabilities: «документацию сам пиши»; «ревью и всё такое
мы сделаем позже». This session instruction overrides the repository's requirement
to complete an independent planning review before implementation for this slice.
No review approval or production release is claimed.

Outcome: a GPT/MCP client can find, create and remove its authenticated user's
active tasks. Removal uses the existing reversible cancel command. Acceptance
evidence is a real MCP SDK handshake/task roundtrip plus ownership, replay and
revocation checks.

Scope: one backend endpoint and four tools, reused native task services,
dedicated existing sessions, opt-in exposure, connection documentation.
Untouched: task persistence/schema, browser/mobile clients, Weekly Review,
voice, agent relay and CRT. OAuth onboarding and independent review are deferred.
