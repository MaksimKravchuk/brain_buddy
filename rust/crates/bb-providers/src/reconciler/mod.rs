//! Voice text reconciler adapter (CAP-EXT-006): `disabled | deterministic | openai`.
//! Mirrors `adapters/reconciler.py`: strict structured-output request, bounded
//! retries with backoff, a worst-case cost admission check and envelope parsing.
//! Grounding and patch materialisation belong to the voice application layer.

mod prompt;

use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

pub const DEFAULT_ENDPOINT: &str = "https://api.openai.com/v1/chat/completions";
pub const TEMPLATE_VERSION: &str = "brain-dump-reconciler-v3";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Provider {
    Disabled,
    Deterministic,
    OpenAi,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Settings {
    pub provider: Provider,
    pub model: String,
    pub api_key_env: String,
    pub endpoint: String,
    pub timeout_seconds: f64,
    pub max_retries: u32,
    pub retry_backoff_seconds: Vec<f64>,
    pub max_cost_usd: f64,
    pub cost_usd_per_mb: f64,
}

impl Settings {
    /// Reads `BRAIN_BUDDY_VOICE_RECONCILER_*` through `get` (defaults as in Python).
    pub fn from_env(get: impl Fn(&str) -> Option<String>) -> Self {
        let var = |k: &str| get(&format!("BRAIN_BUDDY_VOICE_RECONCILER_{k}"));
        let num = |k: &str, d: f64| var(k).and_then(|v| v.trim().parse().ok()).unwrap_or(d);
        Self {
            provider: match var("PROVIDER").as_deref() {
                Some("openai") => Provider::OpenAi,
                Some("deterministic") => Provider::Deterministic,
                _ => Provider::Disabled,
            },
            model: var("MODEL").unwrap_or_else(|| "gpt-4o".into()),
            api_key_env: var("API_KEY_ENV").unwrap_or_else(|| "OPENAI_API_KEY".into()),
            endpoint: var("ENDPOINT").unwrap_or_else(|| DEFAULT_ENDPOINT.into()),
            timeout_seconds: num("TIMEOUT_SECONDS", 30.0),
            max_retries: num("MAX_RETRIES", 2.0) as u32,
            retry_backoff_seconds: var("RETRY_BACKOFF_SECONDS")
                .unwrap_or_else(|| "1,2".into())
                .split(',')
                .filter_map(|v| v.trim().parse().ok())
                .collect(),
            max_cost_usd: num("MAX_COST_USD", 0.50),
            cost_usd_per_mb: num("ESTIMATED_COST_USD_PER_MB", 0.01),
        }
    }
}

/// Input of one reconcile call; the nested shapes are the voice domain's.
#[derive(Clone, Debug, Default)]
pub struct ReconcileRequest {
    pub operation_id: String,
    pub transcript_segments: Vec<Value>,
    pub active_proposals: Vec<Value>,
    pub user_locks: Vec<Value>,
    pub language_hints: Vec<String>,
    pub vocabulary: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationDraft {
    pub operation: String,
    #[serde(default)]
    pub proposal_id: Option<String>,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub source_segment_ids: Vec<String>,
    #[serde(default)]
    pub predecessor_ids: Vec<String>,
    #[serde(default)]
    pub base_revision: Option<u64>,
    #[serde(default)]
    pub confidence: Option<f64>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    operations: Vec<OperationDraft>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Reconciled {
    pub operations: Vec<OperationDraft>,
    pub estimated_cost_usd: f64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Failure {
    /// Retry budget exhausted on transport errors, 429 or 5xx.
    Retryable(&'static str),
    Terminal(&'static str),
    /// The model returned an envelope that violates the schema.
    Validation,
}

/// A failure plus the worst-case spend to record for it.
#[derive(Clone, Debug, PartialEq)]
pub struct ReconcileError {
    pub failure: Failure,
    pub estimated_cost_usd: f64,
}

pub struct OpenAiReconciler {
    settings: Settings,
    api_key: String,
    client: reqwest::Client,
}

pub enum Reconciler {
    Disabled,
    Deterministic,
    OpenAi(Box<OpenAiReconciler>),
}

impl Reconciler {
    /// Mirrors `_build_text_reconciler`: `openai` without its key degrades to disabled.
    pub fn build(settings: Settings, get: impl Fn(&str) -> Option<String>) -> Self {
        match settings.provider {
            Provider::Deterministic => Self::Deterministic,
            Provider::OpenAi => match crate::keys::resolve_with(&settings.api_key_env, get) {
                Some(key) => Self::OpenAi(Box::new(OpenAiReconciler::new(settings, key))),
                None => Self::Disabled,
            },
            Provider::Disabled => Self::Disabled,
        }
    }

    pub fn provider_id(&self) -> &'static str {
        match self {
            Self::Disabled => "disabled",
            Self::Deterministic => "deterministic",
            Self::OpenAi(_) => "openai",
        }
    }

    pub fn requires_external_processing(&self) -> bool {
        !matches!(self, Self::Deterministic)
    }

    pub async fn reconcile(&self, req: &ReconcileRequest) -> Result<Reconciled, ReconcileError> {
        match self {
            Self::Disabled => Err(terminal("RECONCILER_PROVIDER_DISABLED", 0.0)),
            Self::Deterministic => Ok(Reconciled {
                operations: deterministic(req),
                estimated_cost_usd: 0.0,
            }),
            Self::OpenAi(a) => a.reconcile(req).await,
        }
    }
}

fn terminal(code: &'static str, cost: f64) -> ReconcileError {
    ReconcileError {
        failure: Failure::Terminal(code),
        estimated_cost_usd: cost,
    }
}

/// Fixture reconciler: one `add` per non-blank segment, titled with its text.
fn deterministic(req: &ReconcileRequest) -> Vec<OperationDraft> {
    let text = |s: &Value| {
        s["text"]
            .as_str()
            .map(|t| t.split_whitespace().collect::<Vec<_>>().join(" "))
    };
    req.transcript_segments
        .iter()
        .filter_map(|s| {
            Some((
                s["id"].as_str()?.to_string(),
                text(s).filter(|t| !t.is_empty())?,
            ))
        })
        .map(|(id, title)| OperationDraft {
            operation: "add".into(),
            proposal_id: None,
            title: Some(title),
            source_segment_ids: vec![id],
            predecessor_ids: vec![],
            base_revision: None,
            confidence: None,
        })
        .collect()
}

#[derive(Serialize)]
struct Context<'a> {
    operation_id: &'a str,
    transcript_segments: &'a [Value],
    proposals: &'a [Value],
    user_locks: &'a [Value],
    language_hints: &'a [String],
    vocabulary: &'a [String],
}

/// Serialises like Python's `json.dumps(..., ensure_ascii=False)` (", " and ": ").
struct PyFormat;
impl serde_json::ser::Formatter for PyFormat {
    fn begin_array_value<W: ?Sized + std::io::Write>(
        &mut self,
        w: &mut W,
        first: bool,
    ) -> std::io::Result<()> {
        if first { Ok(()) } else { w.write_all(b", ") }
    }
    fn begin_object_key<W: ?Sized + std::io::Write>(
        &mut self,
        w: &mut W,
        first: bool,
    ) -> std::io::Result<()> {
        if first { Ok(()) } else { w.write_all(b", ") }
    }
    fn begin_object_value<W: ?Sized + std::io::Write>(&mut self, w: &mut W) -> std::io::Result<()> {
        w.write_all(b": ")
    }
}

fn py_len(payload: &Value) -> usize {
    let mut out = Vec::new();
    let mut ser = serde_json::Serializer::with_formatter(&mut out, PyFormat);
    payload.serialize(&mut ser).expect("json value serialises");
    out.len()
}

impl OpenAiReconciler {
    pub fn new(settings: Settings, api_key: String) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs_f64(settings.timeout_seconds))
            .build()
            .expect("reqwest client");
        Self {
            settings,
            api_key,
            client,
        }
    }

    pub fn payload(&self, req: &ReconcileRequest) -> Value {
        let add_only = req.active_proposals.is_empty();
        let context = Context {
            operation_id: &req.operation_id,
            transcript_segments: &req.transcript_segments,
            proposals: &req.active_proposals,
            user_locks: &req.user_locks,
            language_hints: &req.language_hints,
            vocabulary: &req.vocabulary,
        };
        json!({
            "model": self.settings.model,
            "temperature": 0,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "voice_brain_dump_reconciliation", "strict": true,
                "schema": prompt::response_schema(add_only)}},
            "messages": [
                {"role": "system", "content": prompt::system_prompt(add_only)},
                {"role": "user", "content": serde_json::to_string(&context).expect("context")},
            ],
        })
    }

    /// Worst case over the bounded retry budget, used for admission and spend.
    pub fn estimated_cost(&self, payload: &Value) -> f64 {
        py_len(payload) as f64 / 1_000_000.0
            * self.settings.cost_usd_per_mb
            * f64::from(self.settings.max_retries + 1)
    }

    pub async fn reconcile(&self, req: &ReconcileRequest) -> Result<Reconciled, ReconcileError> {
        let payload = self.payload(req);
        let cost = self.estimated_cost(&payload);
        if cost > self.settings.max_cost_usd {
            return Err(terminal("RECONCILER_COST_LIMIT_EXCEEDED", cost));
        }
        let fail = |failure| ReconcileError {
            failure,
            estimated_cost_usd: cost,
        };
        let raw = self.call(&payload).await.map_err(fail)?;
        let envelope: Envelope =
            serde_json::from_value(raw).map_err(|_| fail(Failure::Validation))?;
        let valid = envelope.operations.len() <= 100
            && envelope.operations.iter().all(|o| {
                prompt::OPERATIONS.contains(&o.operation.as_str())
                    && o.title.as_ref().is_none_or(|t| t.chars().count() <= 500)
                    && o.source_segment_ids.len() <= 100
                    && o.predecessor_ids.len() <= 100
                    && o.base_revision.is_none_or(|r| r >= 1)
                    && o.confidence.is_none_or(|c| (0.0..=1.0).contains(&c))
            });
        if !valid {
            return Err(fail(Failure::Validation));
        }
        Ok(Reconciled {
            operations: envelope.operations,
            estimated_cost_usd: cost,
        })
    }

    async fn call(&self, payload: &Value) -> Result<Value, Failure> {
        const BAD: Failure = Failure::Terminal("RECONCILER_INVALID_RESPONSE");
        let body = self.post_with_retries(payload).await?;
        let parsed = match &body["choices"][0]["message"]["content"] {
            Value::String(s) => serde_json::from_str(s).map_err(|_| BAD)?,
            other => other.clone(),
        };
        if parsed.is_object() {
            Ok(parsed)
        } else {
            Err(BAD)
        }
    }

    async fn post_with_retries(&self, payload: &Value) -> Result<Value, Failure> {
        let mut attempt = 0;
        loop {
            let sent = self
                .client
                .post(&self.settings.endpoint)
                .bearer_auth(&self.api_key)
                .json(payload)
                .send()
                .await;
            let response = match sent {
                Ok(r) if r.status().as_u16() != 429 && !r.status().is_server_error() => r,
                _ => {
                    if attempt >= self.settings.max_retries {
                        return Err(Failure::Retryable("RECONCILER_PROVIDER_RETRYABLE"));
                    }
                    self.backoff(attempt).await;
                    attempt += 1;
                    continue;
                }
            };
            if !response.status().is_success() {
                return Err(Failure::Terminal("RECONCILER_PROVIDER_REJECTED"));
            }
            return response
                .json()
                .await
                .map_err(|_| Failure::Terminal("RECONCILER_INVALID_RESPONSE"));
        }
    }

    async fn backoff(&self, attempt: u32) {
        let steps = &self.settings.retry_backoff_seconds;
        if let Some(s) = steps.get((attempt as usize).min(steps.len().saturating_sub(1))) {
            tokio::time::sleep(Duration::from_secs_f64(*s)).await;
        }
    }
}

#[cfg(test)]
mod tests;
