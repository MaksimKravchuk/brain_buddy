//! A2A egress (spec 014 wire contract): destination checks, pinned DNS, bounded
//! bodies and agent-card discovery. The JSON-RPC client lands in a later slice.

pub mod card;
pub mod egress;

pub use card::{CardDiscovery, card_url_for, fetch_card};
pub use egress::{EgressError, EgressPolicy, Rejection, Resolver, Response};
