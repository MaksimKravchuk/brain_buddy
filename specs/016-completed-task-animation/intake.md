# Intake — completed task animation

Source: owner's browser annotations and explicit request to implement with subagents and deliver to release.

Problem/outcome: completed tasks should visibly move below open tasks and remain discoverable instead of disappearing. Show a checked state and readable grey struck title.

Latest scope clarification is authoritative: ONLY animation and placement into open/completed parts. New search, multiple-tag and status-filter capabilities are out of scope. Existing filtering and task metadata are reused unchanged. No backend/storage redesign.

Persona: current BrainBuddy owner. KPI: one completed row below loaded open rows, movement under 600ms, no duplicate or false-success row. Compliance: no new processing, retention or logging. Dependencies: existing web task list, autosave/canonical cache and include-completed queries.

Done: targeted tests, independent review, exact-SHA CI, standard release and observed completion/reload production journey. Assessment/interview extension is unnecessary because the latest owner instruction explicitly freezes the narrow outcome.
