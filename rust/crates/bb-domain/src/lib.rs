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
//! * [`task_rules`]: the task lifecycle rules (`task.create`, `task.update`,
//!   `task.transition`).
//! * [`types`]: the frozen value types. The rule families and the
//!   `decide`/`query` entry points land in later slices as they are
//!   implemented, so no module here is an empty placeholder.

pub mod calendar;
pub mod formulation;
pub mod normalization;
pub mod task_rules;
pub mod types;
