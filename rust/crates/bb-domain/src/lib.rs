//! Shared Brain Buddy domain core.
//!
//! No I/O, no clocks, no random identifiers: every time and identifier a rule
//! needs is an explicit input.
//!
//! * [`normalization`]: Python-compatible NFKC, whitespace, full case folding
//!   and Unicode-scalar lengths (`backend/app/modules/tasks/repository.py`,
//!   `formulation.py`).
//! * [`calendar`]: [`calendar::CalendarDay`] and time-zone conversions that keep
//!   a calendar day distinct from an instant.
//! * [`formulation`]: the formulation clock rule (stored facts, advisory
//!   instants, stalled count, transitions without revision side effects).
//! * [`children`]: subtask and comment rules (`decide`, ordered projections).
//! * [`organize`]: project, tag and `task.tags` rules (normalized-name
//!   uniqueness, active references, archive and tag deletion).
//! * [`archive`]: archive membership, legacy marker restoration and the
//!   project listing over it.
//! * [`ai_policy`]: the pure AI route policy: local suitability, on-device-only,
//!   per-owner/provider/consent-version remote consent, input and time limits.
//! * [`proposal`]: navigator output validation, notes reduction and inert,
//!   allow-listed command proposals applied only after explicit confirmation.
//! * [`park`]: auto-park, the human yield and park acknowledgement over the
//!   formulation clock (ADR-0027 precedence, bookkeeping without an edit revision).
//! * [`queries`]: the task, project and tag reads (list, detail, counts,
//!   project display), with the server's ordering and keyset cursor.
//! * [`task_rules`]: the task lifecycle rules (`task.create`, `task.update`,
//!   `task.transition`).
//! * [`review_decisions`]: the Review decision commands (`review.decide`,
//!   `review.undo_decision`, bulk release and its Undo) over the formulation,
//!   park and task rules.
//! * [`children`]: subtask and comment rules (`decide`, ordered projections).
//! * [`formulation`]: the formulation clock rule (stored facts, advisory
//!   instants, stalled count, transitions without revision side effects).
//! * [`types`]: the frozen value types. The rule families and the
//!   `decide`/`query` entry points land in later slices as they are
//!   implemented, so no module here is an empty placeholder.

pub mod ai_policy;
pub mod archive;
pub mod calendar;
pub mod children;
pub mod formulation;
pub mod normalization;
pub mod organize;
pub mod park;
pub mod proposal;
pub mod queries;
pub mod review_decisions;
pub mod task_rules;
pub mod types;
