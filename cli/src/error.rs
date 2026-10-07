use serde::Serialize;
use serde_json::{Value, json};

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Serialize)]
pub struct Error {
    pub code: &'static str,
    pub message: &'static str,
    #[serde(skip)]
    pub exit: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub http_status: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<Box<Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reference_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub retry_after_seconds: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub delivery_unknown: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mutation_confirmed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub idempotency_key: Option<String>,
}

impl Error {
    pub fn new(code: &'static str, message: &'static str, exit: i32) -> Self {
        Self {
            code,
            message,
            exit,
            http_status: None,
            detail: None,
            reference_id: None,
            retry_after_seconds: None,
            delivery_unknown: None,
            mutation_confirmed: None,
            idempotency_key: None,
        }
    }
    pub fn invalid(message: &'static str) -> Self {
        Self::new("invalid_input", message, 2)
    }
    pub fn store(message: &'static str) -> Self {
        Self::new("credential_store_unavailable", message, 10)
    }
    pub fn protocol() -> Self {
        Self::new(
            "invalid_response",
            "Server response is invalid, unsupported or too large.",
            9,
        )
    }
    pub fn auth() -> Self {
        Self::new(
            "authentication_required",
            "Run bb auth login or supply an external session credential.",
            3,
        )
    }
    pub fn emit(&self) {
        eprintln!("{}", json!({"error": self}));
    }
}
