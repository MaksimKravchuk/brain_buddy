//! Pure domain primitives shared by every client and the server.
//!
//! No I/O, no clocks, no random identifiers: every time and identifier a rule
//! needs is an explicit input.
//!
//! * [`normalization`]: Python-compatible NFKC, whitespace, full case folding
//!   and Unicode-scalar lengths (`backend/app/modules/tasks/repository.py`,
//!   `formulation.py`).
//! * [`calendar`]: [`calendar::CalendarDay`] and time-zone conversions that keep
//!   a calendar day distinct from an instant.

pub mod calendar;
pub mod normalization;
