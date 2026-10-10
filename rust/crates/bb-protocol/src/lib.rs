//! Versioned sync v1 wire codecs for the Tasks aggregate and native-task Review.
//!
//! The frozen contract is `specs/026-rust-core-sync/contracts/sync-v1.md` and its
//! generated `sync-v1.schema.json`. This crate parses and serializes; it holds
//! no business rules and performs no I/O.
//!
//! * [`wire`]: validated scalars, [`wire::CodecError`] and [`wire::decode`].
//! * [`catalog`]: the closed entity and command type lists.
//! * [`command`]: two-step command decoding (recovery form, then executable).
//! * [`receipt`]: receipts, errors and result lookup.
//! * [`feed`]: change feed, transfers, snapshots and hint events.
//! * [`capabilities`]: device registration and capabilities.
//! * [`strict_json`]: duplicate-key rejection used by every decoder.

pub mod canonical;
pub mod capabilities;
pub mod catalog;
pub mod command;
pub mod feed;
pub mod receipt;
pub mod strict_json;
pub mod wire;

pub use wire::{CodecError, Wire, decode};
