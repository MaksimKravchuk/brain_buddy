//! JWKS cache that fails closed: an unknown `kid` triggers one refresh that
//! replaces the whole set (rotation); a failed fetch never yields a key.

use std::future::Future;
use std::sync::Mutex;

use super::jose::{Expect, JoseError, Jwk, Verified, token_kid, verify};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FetchError;

pub trait JwksSource: Send + Sync {
    fn fetch(&self) -> impl Future<Output = Result<Vec<Jwk>, FetchError>> + Send;
}

pub struct JwksVerifier<S> {
    source: S,
    keys: Mutex<Vec<Jwk>>,
}

impl<S: JwksSource> JwksVerifier<S> {
    pub fn new(source: S) -> Self {
        Self {
            source,
            keys: Mutex::new(Vec::new()),
        }
    }

    fn cached(&self, kid: &str) -> Option<Jwk> {
        let keys = self.keys.lock().expect("jwks cache lock");
        keys.iter().find(|k| k.kid == kid).cloned()
    }

    async fn key(&self, kid: &str) -> Result<Jwk, JoseError> {
        if let Some(key) = self.cached(kid) {
            return Ok(key);
        }
        let fresh = self.source.fetch().await.map_err(|_| JoseError::Rejected)?;
        *self.keys.lock().expect("jwks cache lock") = fresh;
        self.cached(kid).ok_or(JoseError::Rejected)
    }

    pub async fn verify(&self, token: &str, expect: &Expect<'_>) -> Result<Verified, JoseError> {
        let key = self.key(&token_kid(token)?).await?;
        verify(token, &key, expect)
    }
}
