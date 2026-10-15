//! Black-box conformance suite run against a base URL (spec 027, research R4).
//!
//! Talks HTTP to `BB_CONFORMANCE_BASE_URL`, seeds only through the test control
//! API and writes the CAP-keyed run report `check_capability_inventory.py` reads.

mod client;
mod control;
mod report;

#[cfg(test)]
mod tests;

pub use client::{Client, Config, Reply};
pub use control::{Owner, TestControl};
pub use report::{LogCollector, Report, case};

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;
