//! One scriptable mock for every provider kind, with the hold/release seam.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use tokio::sync::watch;

use crate::traits::{
    A2aTransport, CallMeta, ChatCompletion, IdentityProvider, Ledger, Mail, ProviderError,
    Transcription,
};

#[derive(Clone)]
pub struct MockProvider {
    ledger: Ledger,
    script: Arc<Mutex<VecDeque<Result<String, ProviderError>>>>,
    hold: Arc<watch::Sender<bool>>,
}

impl Default for MockProvider {
    fn default() -> Self {
        Self {
            ledger: Ledger::default(),
            script: Arc::default(),
            hold: Arc::new(watch::channel(false).0),
        }
    }
}

impl MockProvider {
    pub fn ledger(&self) -> &Ledger {
        &self.ledger
    }

    /// Queues responses; an empty script answers `Ok("")`.
    pub fn script(&self, replies: Vec<Result<String, ProviderError>>) {
        *self.script.lock().expect("script lock") = replies.into();
    }

    /// While held, every call blocks (after being recorded) until `release`.
    pub fn hold(&self) {
        self.hold.send_replace(true);
    }

    pub fn release(&self) {
        self.hold.send_replace(false);
    }

    async fn call(&self, meta: &CallMeta) -> Result<String, ProviderError> {
        self.ledger.record(meta);
        let mut held = self.hold.subscribe();
        let _ = held.wait_for(|h| !*h).await;
        self.script
            .lock()
            .expect("script lock")
            .pop_front()
            .unwrap_or_else(|| Ok(String::new()))
    }
}

impl ChatCompletion for MockProvider {
    async fn complete(&self, meta: &CallMeta, _prompt: &str) -> Result<String, ProviderError> {
        self.call(meta).await
    }
}

impl Transcription for MockProvider {
    async fn transcribe(&self, meta: &CallMeta, _audio: &[u8]) -> Result<String, ProviderError> {
        self.call(meta).await
    }
}

impl Mail for MockProvider {
    async fn send(&self, meta: &CallMeta, _to: &str, _body: &str) -> Result<(), ProviderError> {
        self.call(meta).await.map(drop)
    }
}

impl IdentityProvider for MockProvider {
    async fn verify(&self, meta: &CallMeta, _token: &str) -> Result<String, ProviderError> {
        self.call(meta).await
    }
}

impl A2aTransport for MockProvider {
    async fn deliver(
        &self,
        meta: &CallMeta,
        _url: &str,
        _body: &[u8],
    ) -> Result<(), ProviderError> {
        self.call(meta).await.map(drop)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn meta() -> CallMeta {
        CallMeta {
            purpose: "p".into(),
            owner_id: "o".into(),
            correlation_id: "c".into(),
        }
    }

    #[tokio::test]
    async fn mock_records_calls_without_content() {
        let m = MockProvider::default();
        m.script(vec![Ok("hi".into())]);
        assert_eq!(m.complete(&meta(), "secret prompt").await, Ok("hi".into()));
        assert_eq!(m.ledger().calls(), vec![meta()]);
    }

    #[tokio::test]
    async fn held_call_blocks_until_released() {
        let m = MockProvider::default();
        m.hold();
        let m2 = m.clone();
        let task = tokio::spawn(async move { m2.verify(&meta(), "t").await });
        tokio::time::sleep(Duration::from_millis(50)).await;
        assert!(!task.is_finished());
        assert_eq!(m.ledger().count(), 1);
        m.release();
        assert!(task.await.expect("join").is_ok());
    }
}
