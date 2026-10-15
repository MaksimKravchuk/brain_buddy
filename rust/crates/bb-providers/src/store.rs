//! S3-compatible object-store adapter (MinIO locally, Tigris in Fly) and the
//! startup bucket check.

use std::fmt;
use std::sync::Arc;

use object_store::aws::AmazonS3Builder;
use object_store::{ObjectStore, RetryConfig};

pub const VOICE_BUCKET: &str = "voice";
pub const CONTROL_BUCKET: &str = "control";

/// Names the bucket only; never the endpoint, credentials or the cause text.
#[derive(Debug, PartialEq, Eq)]
pub struct BucketError {
    pub bucket: String,
}

impl fmt::Display for BucketError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "object-store bucket `{}` is missing or unreachable",
            self.bucket
        )
    }
}

impl std::error::Error for BucketError {}

pub struct S3Settings {
    pub endpoint: String,
    pub access_key_id: String,
    pub secret_access_key: String,
    pub region: String,
}

/// Builds the store for one bucket (`voice` or `control`).
pub fn s3_store(s: &S3Settings, bucket: &str) -> Result<Arc<dyn ObjectStore>, BucketError> {
    AmazonS3Builder::new()
        .with_endpoint(&s.endpoint)
        .with_access_key_id(&s.access_key_id)
        .with_secret_access_key(&s.secret_access_key)
        .with_region(&s.region)
        .with_bucket_name(bucket)
        .with_allow_http(s.endpoint.starts_with("http://"))
        .with_retry(RetryConfig {
            max_retries: 0,
            ..RetryConfig::default()
        })
        .build()
        .map(|st| Arc::new(st) as Arc<dyn ObjectStore>)
        .map_err(|_| BucketError {
            bucket: bucket.to_string(),
        })
}

/// Startup check: refuses to run when the bucket cannot be listed.
pub async fn check_bucket(store: &dyn ObjectStore, bucket: &str) -> Result<(), BucketError> {
    store
        .list_with_delimiter(None)
        .await
        .map(drop)
        .map_err(|_| BucketError {
            bucket: bucket.to_string(),
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use object_store::memory::InMemory;

    #[tokio::test]
    async fn present_bucket_passes() {
        assert_eq!(check_bucket(&InMemory::new(), VOICE_BUCKET).await, Ok(()));
    }

    #[tokio::test]
    async fn missing_bucket_fails_with_a_named_value_free_error() {
        let s = S3Settings {
            endpoint: "http://127.0.0.1:1".into(),
            access_key_id: "secret-id".into(),
            secret_access_key: "secret-key".into(),
            region: "auto".into(),
        };
        let store = s3_store(&s, CONTROL_BUCKET).expect("build");
        let err = check_bucket(store.as_ref(), CONTROL_BUCKET)
            .await
            .unwrap_err();
        let text = err.to_string();
        assert!(text.contains("control"));
        assert!(!text.contains("secret") && !text.contains("127.0.0.1"));
    }
}
