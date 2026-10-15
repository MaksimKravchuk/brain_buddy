//! Provider traits the application depends on. Object storage is the
//! `object_store::ObjectStore` trait (see `store`).

use std::future::Future;
use std::sync::{Arc, Mutex};

/// A provider failure. Carries a class only, never request content.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProviderError {
    Unavailable,
    Rejected(String),
}

pub trait ChatCompletion: Send + Sync {
    fn complete(
        &self,
        meta: &CallMeta,
        prompt: &str,
    ) -> impl Future<Output = Result<String, ProviderError>> + Send;
}

pub trait Transcription: Send + Sync {
    fn transcribe(
        &self,
        meta: &CallMeta,
        audio: &[u8],
    ) -> impl Future<Output = Result<String, ProviderError>> + Send;
}

pub trait Mail: Send + Sync {
    fn send(
        &self,
        meta: &CallMeta,
        to: &str,
        body: &str,
    ) -> impl Future<Output = Result<(), ProviderError>> + Send;
}

pub trait IdentityProvider: Send + Sync {
    /// Verifies a provider token and returns the subject.
    fn verify(
        &self,
        meta: &CallMeta,
        token: &str,
    ) -> impl Future<Output = Result<String, ProviderError>> + Send;
}

pub trait A2aTransport: Send + Sync {
    fn deliver(
        &self,
        meta: &CallMeta,
        url: &str,
        body: &[u8],
    ) -> impl Future<Output = Result<(), ProviderError>> + Send;
}

// Content-free call ledger: proves "zero provider calls" without storing payloads.
/// Who made a call and why; never the request or response content.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CallMeta {
    pub purpose: String,
    pub owner_id: String,
    pub correlation_id: String,
}

pub type CallRecord = CallMeta;

#[derive(Clone, Debug, Default)]
pub struct Ledger(Arc<Mutex<Vec<CallRecord>>>);

impl Ledger {
    pub fn record(&self, meta: &CallMeta) {
        self.0.lock().expect("ledger lock").push(meta.clone());
    }

    pub fn calls(&self) -> Vec<CallRecord> {
        self.0.lock().expect("ledger lock").clone()
    }

    pub fn count(&self) -> usize {
        self.0.lock().expect("ledger lock").len()
    }
}
