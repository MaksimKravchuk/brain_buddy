//! AI, STT, SMTP, Apple/Google and A2A egress adapters.
//!
//! Provider traits, mocks with a content-free call ledger and the hold/release
//! seam (contracts/test-control.md), and the object-store startup check.

pub mod a2a;
pub mod identity;
pub mod mock;
pub mod openai;
pub mod reconciler;
pub mod smtp;
pub mod store;
pub mod stt;
pub mod traits;

pub use mock::MockProvider;
pub use traits::{
    A2aTransport, ChatCompletion, IdentityProvider, Mail, ProviderError, Transcription,
};
pub use traits::{CallMeta, CallRecord, Ledger};

/// API key indirection: configuration names an environment variable
/// (`*_API_KEY_ENV`); the key is read at use and never logged.
pub mod keys {
    pub const DEFAULT_OPENAI_KEY_ENV: &str = "OPENAI_API_KEY";
    pub const DEFAULT_DEEPGRAM_KEY_ENV: &str = "DEEPGRAM_API_KEY";

    /// Resolves the key named by `env_name`; `None` when unset or empty.
    pub fn resolve(env_name: &str) -> Option<String> {
        resolve_with(env_name, |n| std::env::var(n).ok())
    }

    pub fn resolve_with(env_name: &str, get: impl Fn(&str) -> Option<String>) -> Option<String> {
        get(env_name).filter(|v| !v.is_empty())
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn resolves_through_the_named_variable_only() {
            let get = |n: &str| (n == "X_KEY").then(|| "k".to_string());
            assert_eq!(resolve_with("X_KEY", get), Some("k".into()));
            assert_eq!(resolve_with(DEFAULT_OPENAI_KEY_ENV, get), None);
            assert_eq!(resolve_with("E", |_| Some(String::new())), None);
        }
    }
}
