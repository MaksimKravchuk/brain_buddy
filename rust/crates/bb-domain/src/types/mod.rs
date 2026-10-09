//! Frozen domain value types (026 PR-61): state subsets, command and query
//! inputs, query outputs, the [`ChangeSet`] and typed [`DomainError`]s that
//! `decide` and `query` exchange.
//!
//! Wire primitives (counters, instants, command and entity IDs, the command and
//! entity catalogs) come from `bb_protocol` and are re-exported, not redefined.
//! Everything else is checked when it is parsed: Unicode-scalar length limits,
//! identifier shapes, PATCH omitted/null/value ([`Patch`]) and closed
//! vocabularies. The modules group by what changes together:
//!
//! * [`primitives`], [`vocabulary`], [`errors`]: checked scalars, closed
//!   vocabularies and refusals.
//! * [`tasks`]: task, project, tag, subtask and comment state and payloads.
//! * [`review_state`]: native Review state subsets.
//! * [`review_commands`]: native Review command payloads.
//! * [`catalog`]: the [`Command`] union, [`DomainCommand::from_envelope`],
//!   [`ReadSet`], [`Record`], [`ChangeSet`] and the execution/query inputs.
//! * [`query_results`]: what `query` returns.

pub mod catalog;
pub mod errors;
pub mod primitives;
pub mod query_results;
pub mod review_commands;
pub mod review_state;
pub mod tasks;
pub mod vocabulary;

pub use bb_protocol::catalog::{CommandType, EntityType};
pub use bb_protocol::receipt::Binding;
pub use bb_protocol::wire::{CommandId, Counter, Id, Instant, RecordKey};

pub use catalog::*;
pub use errors::*;
pub use primitives::*;
pub use query_results::*;
pub use review_commands::*;
pub use review_state::*;
pub use tasks::*;
pub use vocabulary::*;
