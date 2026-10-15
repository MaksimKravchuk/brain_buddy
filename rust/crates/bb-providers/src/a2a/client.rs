//! The six A2A JSON-RPC calls BrainBuddy makes, over pinned egress (spec 014).
//!
//! Every call answers one question: did anything leave BrainBuddy, and could it
//! already be running at the agent? *Not sent* (definitive refusal), *unconfirmed*
//! (timeout, 5xx, transport loss, malformed answer: look up, never resend) and
//! *sent* are told apart by an explicit error table, never a fallback chain.
//! Correlation ids are minted here and never taken from an inbound header.
//!
//! `egress.rs` only exposes a pinned GET, so the POST is built here with the same
//! rules: validated destination, pinned addresses, no redirects, no proxy, capped
//! body, absolute wall-clock deadline.

use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::net::SocketAddr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use reqwest::{Client, redirect};
use serde_json::{Value, json};

use super::egress::{
    Destination, EgressError, EgressPolicy, Rejection, Resolver, Response, validate_destination,
};

pub const A2A_VERSION: &str = "1.0";
pub const EXTENSION_HEADER: &str = "A2A-Extensions";
pub const CORRELATION_HEADER: &str = "X-Correlation-ID";
pub const OBSERVATION_CORRELATION_PREFIX: &str = "obs_";
pub const SINGLE_START_EXTENSION_URI: &str = "https://github.com/MaksimKravchuk/brain_buddy/blob/main/docs/a2a-extensions/single-start/v1.md";
pub const PUSH_PATH: &str = "/api/a2a/push";

pub const SHORT_CALL_DEADLINE_MARGIN: Duration = Duration::from_secs(5);
pub const EXCHANGE_DEADLINE_MARGIN: Duration = Duration::from_secs(15);
pub const EXCHANGE_CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_RETRY_AFTER_SECONDS: i64 = 24 * 60 * 60;

pub const A2A_UNREACHABLE: &str = "a2a_unreachable";
pub const A2A_TIMEOUT: &str = "a2a_timeout";
pub const A2A_SERVER_ERROR: &str = "a2a_server_error";
pub const A2A_CREDENTIALS_REJECTED: &str = "a2a_credentials_rejected";
pub const A2A_RATE_LIMITED: &str = "a2a_rate_limited";
pub const A2A_REQUEST_REJECTED: &str = "a2a_request_rejected";
pub const A2A_RESPONSE_INVALID: &str = "a2a_response_invalid";
pub const A2A_RESPONSE_OVER_CAP: &str = "a2a_response_over_cap";
pub const A2A_TASK_NOT_FOUND: &str = "a2a_task_not_found";
pub const A2A_NOT_CANCELABLE: &str = "a2a_not_cancelable";
pub const A2A_PUSH_UNSUPPORTED: &str = "a2a_push_unsupported";
pub const A2A_UNSUPPORTED_OPERATION: &str = "a2a_unsupported_operation";
pub const A2A_CONTENT_UNSUPPORTED: &str = "a2a_content_unsupported";
pub const A2A_METHOD_NOT_FOUND: &str = "a2a_method_not_found";
pub const A2A_INTERNAL_ERROR: &str = "a2a_internal_error";
pub const A2A_INVALID_AGENT_RESPONSE: &str = "a2a_invalid_agent_response";
pub const A2A_EXTENDED_CARD_NOT_CONFIGURED: &str = "a2a_extended_card_not_configured";
pub const A2A_EXTENSION_SUPPORT_REQUIRED: &str = "a2a_extension_support_required";
pub const A2A_VERSION_NOT_SUPPORTED: &str = "a2a_version_not_supported";

/// JSON-RPC error code to BrainBuddy category (contracts/a2a-wire.md). `-32603`
/// stays apart from `-32004`/`-32601`: only an explicit answer may harden into a
/// durable "does not support cancellation" claim.
fn category_for(code: i64) -> &'static str {
    match code {
        -32001 => A2A_TASK_NOT_FOUND,
        -32002 => A2A_NOT_CANCELABLE,
        -32003 => A2A_PUSH_UNSUPPORTED,
        -32004 => A2A_UNSUPPORTED_OPERATION,
        -32005 => A2A_CONTENT_UNSUPPORTED,
        -32006 => A2A_INVALID_AGENT_RESPONSE,
        -32007 => A2A_EXTENDED_CARD_NOT_CONFIGURED,
        -32008 => A2A_EXTENSION_SUPPORT_REQUIRED,
        -32009 => A2A_VERSION_NOT_SUPPORTED,
        -32600 | -32602 | -32700 => A2A_REQUEST_REJECTED,
        -32601 => A2A_METHOD_NOT_FOUND,
        -32603 => A2A_INTERNAL_ERROR,
        -32050 | -32052 => A2A_CREDENTIALS_REJECTED,
        -32051 => A2A_RATE_LIMITED,
        _ => A2A_RESPONSE_INVALID,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AuthScheme {
    Bearer,
    /// The credential travels in `auth_header_name`.
    Header,
}

/// Where one call goes and what it may carry. `Debug` redacts the credential.
#[derive(Clone)]
pub struct A2aTarget {
    pub interface_url: String,
    pub auth_scheme: AuthScheme,
    pub auth_header_name: Option<String>,
    pub credential: Option<String>,
    pub tenant: Option<String>,
    /// `guaranteed` tier: the single-start extension is activated on every call.
    pub guaranteed: bool,
}

impl std::fmt::Debug for A2aTarget {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("A2aTarget")
            .field("interface_url", &self.interface_url)
            .field(
                "credential",
                &self.credential.as_ref().map(|_| "<redacted>"),
            )
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ResultAvailability {
    TooLarge,
}

/// One call's outcome. Holds no credential; agent strings are ids and codes.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct A2aResult {
    pub ok: bool,
    pub correlation_id: String,
    pub task: Option<Value>,
    pub message: Option<Value>,
    pub tasks: Vec<Value>,
    pub error_code: Option<&'static str>,
    pub a2a_error_code: Option<i64>,
    pub http_status: Option<u16>,
    pub retry_after_seconds: Option<u32>,
    pub result_availability: Option<ResultAvailability>,
}

impl A2aResult {
    fn failed(correlation_id: &str, code: &'static str) -> Self {
        Self {
            correlation_id: correlation_id.to_string(),
            error_code: Some(code),
            ..Self::default()
        }
    }

    fn failed_http(correlation_id: &str, code: &'static str, status: u16) -> Self {
        Self {
            http_status: Some(status),
            ..Self::failed(correlation_id, code)
        }
    }
}

/// Per-call knobs for the observation reads.
#[derive(Clone, Debug, Default)]
pub struct CallOptions {
    /// Prefixes the correlation id with `obs_` (a scheduled observation).
    pub scheduled: bool,
    pub deadline: Option<Duration>,
}

/// `<public base>/api/a2a/push/{run}/{token}`, registered with the agent.
pub fn push_callback_url(public_base_url: &str, run_id: &str, token: &str) -> String {
    format!(
        "{}{PUSH_PATH}/{run_id}/{token}",
        public_base_url.trim_end_matches('/')
    )
}

/// The `taskPushNotificationConfig` carried by a start or reply exchange.
pub fn push_config(url: &str, token: &str) -> Value {
    json!({"url": url, "token": token})
}

fn mint_id() -> String {
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let mut out = String::with_capacity(32);
    for _ in 0..2 {
        let mut h = RandomState::new().build_hasher();
        h.write_u64(SEQ.fetch_add(1, Ordering::Relaxed));
        if let Ok(t) = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
            h.write_u128(t.as_nanos());
        }
        out.push_str(&format!("{:016x}", h.finish()));
    }
    out
}

/// A `Retry-After` in whole seconds, or nothing: a guessed countdown is a claim
/// the agent never made.
fn parse_retry_after(raw: Option<&str>) -> Option<u32> {
    let n: i64 = raw?.trim().parse().ok()?;
    if (0..=MAX_RETRY_AFTER_SECONDS).contains(&n) {
        u32::try_from(n).ok()
    } else {
        None
    }
}

fn valid_task(v: &Value) -> bool {
    v.get("id").is_some_and(Value::is_string)
        && v.get("status")
            .is_none_or(|s| s.is_object() && s.get("state").is_none_or(Value::is_string))
        && ["artifacts", "history"]
            .iter()
            .all(|k| v.get(*k).is_none_or(Value::is_array))
}

/// Reads the `result` object: `{"task"}`, `{"message"}`, `{"tasks"}` or a bare
/// task (id + status), which is what 1.0 reads answer.
fn read_result(result: &Value, correlation_id: &str, status: u16) -> A2aResult {
    let invalid = || A2aResult::failed_http(correlation_id, A2A_RESPONSE_INVALID, status);
    let task = match result.get("task") {
        Some(t) if valid_task(t) => Some(t.clone()),
        Some(_) => return invalid(),
        None if result.get("id").is_some() && result.get("status").is_some() => {
            if !valid_task(result) {
                return invalid();
            }
            Some(result.clone())
        }
        None => None,
    };
    let message = match result.get("message") {
        Some(m) if m.is_object() => Some(m.clone()),
        Some(_) => return invalid(),
        None => None,
    };
    let tasks = match result.get("tasks") {
        None => Vec::new(),
        Some(Value::Array(a)) if a.iter().all(valid_task) => a.clone(),
        Some(_) => return invalid(),
    };
    A2aResult {
        ok: true,
        correlation_id: correlation_id.to_string(),
        task,
        message,
        tasks,
        http_status: Some(status),
        ..A2aResult::default()
    }
}

fn id_matches(id: Option<&Value>, request_id: &str) -> bool {
    match id {
        Some(Value::String(s)) => s == request_id,
        Some(Value::Number(n)) => n.to_string() == request_id,
        _ => false,
    }
}

/// One HTTP answer to a category. Status class first.
fn interpret(resp: &Response, retry_after: Option<&str>, request_id: &str, cid: &str) -> A2aResult {
    let s = resp.status;
    match s {
        401 | 403 => return A2aResult::failed_http(cid, A2A_CREDENTIALS_REJECTED, s),
        429 => {
            return A2aResult {
                retry_after_seconds: parse_retry_after(retry_after),
                ..A2aResult::failed_http(cid, A2A_RATE_LIMITED, s)
            };
        }
        500.. => return A2aResult::failed_http(cid, A2A_SERVER_ERROR, s),
        400.. => return A2aResult::failed_http(cid, A2A_REQUEST_REJECTED, s),
        _ => {}
    }
    let invalid = || A2aResult::failed_http(cid, A2A_RESPONSE_INVALID, s);
    let Ok(Value::Object(env)) = serde_json::from_slice::<Value>(&resp.body) else {
        return invalid();
    };
    let result = env.get("result").filter(|v| !v.is_null());
    let error = env.get("error").filter(|v| !v.is_null());
    // Exactly one outcome: a body with both is not a partial success to salvage.
    if result.is_some() == error.is_some() {
        return invalid();
    }
    // An answer that does not name its request could belong to any call.
    if !id_matches(env.get("id"), request_id) {
        return invalid();
    }
    if let Some(err) = error {
        let Some(code) = err.get("code").and_then(Value::as_i64) else {
            return invalid();
        };
        return A2aResult {
            a2a_error_code: Some(code),
            ..A2aResult::failed_http(cid, category_for(code), s)
        };
    }
    match result {
        Some(r) if r.is_object() => read_result(r, cid, s),
        _ => invalid(),
    }
}

/// Timing and cap for one call.
struct Limits {
    connect: Duration,
    read: Duration,
    deadline: Duration,
    max_bytes: usize,
}

/// One POST to a validated destination over its pinned addresses: no redirects,
/// no proxy, body capped, absolute wall-clock deadline.
async fn pinned_post(
    dest: &Destination,
    headers: HeaderMap,
    body: Vec<u8>,
    limits: &Limits,
) -> Result<(Response, Option<String>), EgressError> {
    let addrs: Vec<SocketAddr> = dest
        .addresses
        .iter()
        .map(|ip| SocketAddr::new(*ip, dest.port))
        .collect();
    let client = Client::builder()
        .redirect(redirect::Policy::none())
        .no_proxy()
        .connect_timeout(limits.connect)
        .read_timeout(limits.read)
        .resolve_to_addrs(&dest.host, &addrs)
        .build()
        .map_err(|_| EgressError::Transport)?;
    let classify = |e: reqwest::Error| {
        if e.is_timeout() {
            EgressError::Deadline
        } else {
            EgressError::Transport
        }
    };
    let run = async {
        let mut resp = client
            .post(dest.url.clone())
            .headers(headers)
            .body(body)
            .send()
            .await
            .map_err(classify)?;
        let status = resp.status();
        if status.is_redirection() {
            return Err(Rejection::RedirectNotAllowed.into());
        }
        let retry_after = resp
            .headers()
            .get("retry-after")
            .and_then(|v| v.to_str().ok())
            .map(str::to_string);
        let encoded = resp
            .headers()
            .get("content-encoding")
            .is_some_and(|v| !v.as_bytes().eq_ignore_ascii_case(b"identity"));
        let mut buf = Vec::new();
        while let Some(chunk) = resp.chunk().await.map_err(classify)? {
            buf.extend_from_slice(&chunk);
            if encoded || buf.len() > limits.max_bytes {
                return Err(Rejection::Invalid.into());
            }
        }
        Ok((
            Response {
                status: status.as_u16(),
                body: buf,
            },
            retry_after,
        ))
    };
    tokio::time::timeout(limits.deadline, run)
        .await
        .map_err(|_| EgressError::Deadline)?
}

/// A minimal A2A JSON-RPC client on BrainBuddy's egress path.
#[derive(Clone, Debug)]
pub struct A2aClient {
    pub timeout: Duration,
    pub reply_window: Duration,
    pub max_response_bytes: usize,
    pub task_max_response_bytes: usize,
    pub allow_private: bool,
    pub resolver: Resolver,
}

impl A2aClient {
    /// Start or continue work at the agent: the only content-bearing call.
    /// Blocking (`returnImmediately` absent), so the agent creates the task on
    /// receipt and a lookup can find it later.
    pub async fn send_message(
        &self,
        target: &A2aTarget,
        message: Value,
        push_config: Option<Value>,
    ) -> A2aResult {
        let mut message = message;
        if target.guaranteed
            && let Some(m) = message.as_object_mut()
        {
            // Activated on the first send, not only on replays.
            m.insert("extensions".into(), json!([SINGLE_START_EXTENSION_URI]));
        }
        let mut configuration = json!({"historyLength": 0});
        if let Some(p) = push_config {
            configuration["taskPushNotificationConfig"] = p;
        }
        let window = self.reply_window + EXCHANGE_DEADLINE_MARGIN;
        let limits = Limits {
            connect: EXCHANGE_CONNECT_TIMEOUT,
            read: window,
            deadline: window,
            max_bytes: self.task_max_response_bytes,
        };
        let params = json!({"message": message, "configuration": configuration});
        self.call(
            target,
            "SendMessage",
            params,
            &limits,
            &CallOptions::default(),
        )
        .await
    }

    /// Reads one task. On an over-cap body with a `context_id`, falls back to
    /// `ListTasks` so the state is still observed and marked "too large".
    pub async fn get_task(
        &self,
        target: &A2aTarget,
        task_id: &str,
        context_id: Option<&str>,
        history_length: u32,
        opts: &CallOptions,
    ) -> A2aResult {
        let params = json!({"id": task_id, "historyLength": history_length});
        let r = self
            .call(target, "GetTask", params, &self.task_limits(opts), opts)
            .await;
        // Without a contextId the fallback would list another conversation's tasks.
        let Some(ctx) = context_id.filter(|_| r.error_code == Some(A2A_RESPONSE_OVER_CAP)) else {
            return r;
        };
        let fb = self.list_tasks(target, Some(ctx), 5, opts).await;
        match fb.tasks.first() {
            Some(newest) if fb.ok => A2aResult {
                ok: true,
                correlation_id: fb.correlation_id.clone(),
                task: Some(newest.clone()),
                // The state is true; only the result is missing.
                result_availability: Some(ResultAvailability::TooLarge),
                ..A2aResult::default()
            },
            _ => r,
        }
    }

    /// Lists the tasks of one conversation. Never carries content.
    pub async fn list_tasks(
        &self,
        target: &A2aTarget,
        context_id: Option<&str>,
        page_size: u32,
        opts: &CallOptions,
    ) -> A2aResult {
        let mut params = json!({});
        if let Some(c) = context_id {
            params["contextId"] = json!(c);
        }
        params["pageSize"] = json!(page_size);
        params["includeArtifacts"] = json!(false);
        params["historyLength"] = json!(0);
        self.call(target, "ListTasks", params, &self.task_limits(opts), opts)
            .await
    }

    /// Asks the agent to stop. Short call; never queued behind an exchange.
    pub async fn cancel_task(
        &self,
        target: &A2aTarget,
        task_id: &str,
        command_id: Option<&str>,
    ) -> A2aResult {
        let mut params = json!({"id": task_id});
        if let Some(c) = command_id {
            params["metadata"] = json!({"brainbuddy.command_id": c});
        }
        self.short_call(target, "CancelTask", params).await
    }

    /// Registers a push callback for an adopted task. Failures are silent to the
    /// user: push only accelerates an observation the schedule performs anyway.
    pub async fn create_push_config(
        &self,
        target: &A2aTarget,
        task_id: &str,
        url: &str,
        token: &str,
    ) -> A2aResult {
        let params = json!({"taskId": task_id, "url": url, "token": token});
        self.short_call(target, "CreateTaskPushNotificationConfig", params)
            .await
    }

    fn short_limits(&self, max_bytes: usize, deadline: Option<Duration>) -> Limits {
        Limits {
            connect: self.timeout,
            read: self.timeout,
            deadline: deadline.unwrap_or(self.timeout + SHORT_CALL_DEADLINE_MARGIN),
            max_bytes,
        }
    }

    fn task_limits(&self, opts: &CallOptions) -> Limits {
        self.short_limits(self.task_max_response_bytes, opts.deadline)
    }

    async fn short_call(&self, target: &A2aTarget, method: &str, params: Value) -> A2aResult {
        let limits = self.short_limits(self.max_response_bytes, None);
        self.call(target, method, params, &limits, &CallOptions::default())
            .await
    }

    fn headers(target: &A2aTarget, correlation_id: &str) -> Option<HeaderMap> {
        let mut h = HeaderMap::new();
        let mut put = |k: &str, v: &str| -> Option<()> {
            h.insert(
                HeaderName::from_bytes(k.as_bytes()).ok()?,
                HeaderValue::from_str(v).ok()?,
            );
            Some(())
        };
        put("Content-Type", "application/json")?;
        put("Accept", "application/json")?;
        put("A2A-Version", A2A_VERSION)?;
        put(CORRELATION_HEADER, correlation_id)?;
        if let Some(c) = target.credential.as_deref().filter(|c| !c.is_empty()) {
            match (target.auth_scheme, target.auth_header_name.as_deref()) {
                (AuthScheme::Bearer, _) => put("Authorization", &format!("Bearer {c}"))?,
                (AuthScheme::Header, Some(name)) => put(name, c)?,
                (AuthScheme::Header, None) => {}
            }
        }
        if target.guaranteed {
            put(EXTENSION_HEADER, SINGLE_START_EXTENSION_URI)?;
        }
        Some(h)
    }

    /// The one place a request is built.
    async fn call(
        &self,
        target: &A2aTarget,
        method: &str,
        mut params: Value,
        limits: &Limits,
        opts: &CallOptions,
    ) -> A2aResult {
        let minted = mint_id();
        let correlation_id = if opts.scheduled {
            format!("{OBSERVATION_CORRELATION_PREFIX}{minted}")
        } else {
            minted
        };
        if let Some(t) = target.tenant.as_deref().filter(|t| !t.is_empty()) {
            params["tenant"] = json!(t);
        }
        let request_id = mint_id();
        let body = json!({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params});
        let policy = EgressPolicy {
            timeout: limits.read,
            max_response_bytes: limits.max_bytes,
            allow_private: self.allow_private,
        };
        let dest = match validate_destination(&target.interface_url, &policy, &self.resolver).await
        {
            Ok(d) => d,
            Err(r) => return A2aResult::failed(&correlation_id, r.code()),
        };
        let (Some(headers), Ok(bytes)) = (
            Self::headers(target, &correlation_id),
            serde_json::to_vec(&body),
        ) else {
            // An unsendable header value: definitively not sent.
            return A2aResult::failed(&correlation_id, A2A_REQUEST_REJECTED);
        };
        match pinned_post(&dest, headers, bytes, limits).await {
            // Contacted but not answered in time: unconfirmed, never "not sent".
            Err(EgressError::Deadline) => A2aResult::failed(&correlation_id, A2A_TIMEOUT),
            Err(EgressError::Rejected(Rejection::Invalid)) => {
                A2aResult::failed(&correlation_id, A2A_RESPONSE_OVER_CAP)
            }
            Err(EgressError::Rejected(r)) => A2aResult::failed(&correlation_id, r.code()),
            Err(EgressError::Transport) => A2aResult::failed(&correlation_id, A2A_UNREACHABLE),
            Ok((resp, retry_after)) => {
                interpret(&resp, retry_after.as_deref(), &request_id, &correlation_id)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};

    use super::*;

    type Seen = Arc<Mutex<Vec<(String, Value)>>>;

    /// Mock peer: records (raw headers, JSON body) of each request and answers
    /// with `reply(request_json)` (a full HTTP response). Returns (port, seen).
    fn peer(reply: impl Fn(&Value) -> String + Send + 'static) -> (u16, Seen) {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        let seen: Seen = Arc::default();
        let log = seen.clone();
        std::thread::spawn(move || {
            for mut s in l.incoming().flatten() {
                let mut raw = Vec::new();
                let mut buf = [0u8; 4096];
                let (head, body) = loop {
                    let n = s.read(&mut buf).unwrap_or(0);
                    raw.extend_from_slice(&buf[..n]);
                    let text = String::from_utf8_lossy(&raw).to_string();
                    if let Some((h, b)) = text.split_once("\r\n\r\n") {
                        let len = h
                            .to_ascii_lowercase()
                            .lines()
                            .find_map(|l| l.strip_prefix("content-length:").map(str::to_string))
                            .and_then(|v| v.trim().parse::<usize>().ok())
                            .unwrap_or(0);
                        if b.len() >= len || n == 0 {
                            break (h.to_string(), b.to_string());
                        }
                    }
                    if n == 0 {
                        break (String::new(), String::new());
                    }
                };
                let json: Value = serde_json::from_str(&body).unwrap_or(Value::Null);
                let out = reply(&json);
                log.lock().unwrap().push((head, json));
                let _ = s.write_all(out.as_bytes());
            }
        });
        (port, seen)
    }

    fn http(status: &str, extra: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {status}\r\nContent-Type: application/json\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    fn rpc_ok(req: &Value, result: Value) -> String {
        http(
            "200 OK",
            "",
            &json!({"jsonrpc": "2.0", "id": req["id"], "result": result}).to_string(),
        )
    }

    fn rpc_err(req: &Value, code: i64) -> String {
        let e = json!({"jsonrpc": "2.0", "id": req["id"], "error": {"code": code, "message": "x"}});
        http("200 OK", "", &e.to_string())
    }

    fn client() -> A2aClient {
        A2aClient {
            timeout: Duration::from_secs(2),
            reply_window: Duration::from_secs(300),
            max_response_bytes: 4_000,
            task_max_response_bytes: 4_000,
            allow_private: true,
            resolver: Resolver::System,
        }
    }

    fn target(port: u16) -> A2aTarget {
        A2aTarget {
            interface_url: format!("http://127.0.0.1:{port}/rpc"),
            auth_scheme: AuthScheme::Bearer,
            auth_header_name: None,
            credential: Some("sekret".into()),
            tenant: None,
            guaranteed: false,
        }
    }

    fn task() -> Value {
        json!({"id": "t1", "contextId": "run1", "status": {"state": "TASK_STATE_WORKING"}})
    }

    #[tokio::test]
    async fn t027_fr_014_send_message_wire_body_and_headers_match_spec_014() {
        let (port, seen) = peer(|r| rpc_ok(r, json!({"task": task()})));
        let mut t = target(port);
        t.guaranteed = true;
        t.tenant = Some("acme".into());
        let msg = json!({"messageId": "run1:start", "contextId": "run1", "role": "ROLE_USER",
                         "parts": [{"text": "hi"}]});
        let cfg = push_config("https://bb.example/api/a2a/push/run1/tok", "tok");
        let got = client().send_message(&t, msg, Some(cfg)).await;
        assert!(got.ok, "{got:?}");
        assert_eq!(got.task.unwrap()["id"], "t1");
        let (head, body) = seen.lock().unwrap()[0].clone();
        let head = head.to_ascii_lowercase();
        assert!(head.contains("authorization: bearer sekret"));
        assert!(head.contains("a2a-version: 1.0"));
        assert!(head.contains(
            &format!("a2a-extensions: {SINGLE_START_EXTENSION_URI}").to_ascii_lowercase()
        ));
        assert_eq!(body["jsonrpc"], "2.0");
        assert_eq!(body["method"], "SendMessage");
        assert_eq!(body["params"]["tenant"], "acme");
        assert_eq!(
            body["params"]["message"]["extensions"][0],
            SINGLE_START_EXTENSION_URI
        );
        let c = &body["params"]["configuration"];
        assert_eq!(c["historyLength"], 0);
        assert_eq!(c["taskPushNotificationConfig"]["token"], "tok");
        assert!(c.get("returnImmediately").is_none());
        // The agent sees a server-minted id, never an inbound label.
        assert!(head.contains(&format!("x-correlation-id: {}", got.correlation_id)));
    }

    #[tokio::test]
    async fn t027_fr_014_read_calls_cancel_and_push_registration_bodies() {
        let (port, seen) = peer(|r| match r["method"].as_str() {
            Some("GetTask") => rpc_ok(r, task()),
            Some("ListTasks") => rpc_ok(r, json!({"tasks": [task()]})),
            Some("CancelTask") => rpc_ok(r, json!({})),
            _ => rpc_ok(r, json!({})),
        });
        let (c, t) = (client(), target(port));
        let scheduled = CallOptions {
            scheduled: true,
            deadline: None,
        };
        let g = c.get_task(&t, "t1", None, 0, &scheduled).await;
        assert!(g.ok && g.task.is_some(), "bare task result: {g:?}");
        assert!(g.correlation_id.starts_with("obs_"));
        let l = c
            .list_tasks(&t, Some("run1"), 5, &CallOptions::default())
            .await;
        assert_eq!(l.tasks.len(), 1);
        let x = c.cancel_task(&t, "t1", Some("cmd1")).await;
        assert!(x.ok && x.task.is_none());
        let p = c.create_push_config(&t, "t1", "https://u", "tok").await;
        assert!(p.ok);
        let bodies: Vec<Value> = seen.lock().unwrap().iter().map(|s| s.1.clone()).collect();
        assert_eq!(bodies[0]["params"], json!({"id": "t1", "historyLength": 0}));
        assert_eq!(
            bodies[1]["params"],
            json!({"contextId": "run1", "pageSize": 5, "includeArtifacts": false, "historyLength": 0})
        );
        assert_eq!(
            bodies[2]["params"],
            json!({"id": "t1", "metadata": {"brainbuddy.command_id": "cmd1"}})
        );
        assert_eq!(bodies[3]["method"], "CreateTaskPushNotificationConfig");
        assert_eq!(
            bodies[3]["params"],
            json!({"taskId": "t1", "url": "https://u", "token": "tok"})
        );
    }

    #[tokio::test]
    async fn t027_fr_014_errors_map_to_categories_and_retry_after_is_bounded() {
        let cases: [(&str, &str, &str); 5] = [
            ("401 Unauthorized", "", A2A_CREDENTIALS_REJECTED),
            ("500 Internal Server Error", "", A2A_SERVER_ERROR),
            ("404 Not Found", "", A2A_REQUEST_REJECTED),
            ("429 Too Many", "Retry-After: 30\r\n", A2A_RATE_LIMITED),
            ("200 OK", "", A2A_RESPONSE_INVALID),
        ];
        for (status, extra, want) in cases {
            let reply = http(status, extra, "not json");
            let (port, _) = peer(move |_| reply.clone());
            let got = client().cancel_task(&target(port), "t", None).await;
            assert_eq!(got.error_code, Some(want), "{status}");
            assert_eq!(got.retry_after_seconds, extra.contains("30").then_some(30));
        }
        assert_eq!(parse_retry_after(Some("999999")), None);
        assert_eq!(parse_retry_after(Some("-1")), None);
        assert_eq!(parse_retry_after(Some("soon")), None);
        for (code, want) in [
            (-32001, A2A_TASK_NOT_FOUND),
            (-32004, A2A_UNSUPPORTED_OPERATION),
            (-32602, A2A_REQUEST_REJECTED),
            (-32603, A2A_INTERNAL_ERROR),
            (-32051, A2A_RATE_LIMITED),
            (-1, A2A_RESPONSE_INVALID),
        ] {
            let (port, _) = peer(move |r| rpc_err(r, code));
            let got = client().cancel_task(&target(port), "t", None).await;
            assert_eq!(got.error_code, Some(want), "{code}");
            assert_eq!(got.a2a_error_code, Some(code));
        }
    }

    #[tokio::test]
    async fn t027_fr_014_mismatched_ids_and_both_outcomes_are_invalid() {
        let wrong = http(
            "200 OK",
            "",
            r#"{"jsonrpc":"2.0","id":"other","result":{}}"#,
        );
        let (port, _) = peer(move |_| wrong.clone());
        let got = client().cancel_task(&target(port), "t", None).await;
        assert_eq!(got.error_code, Some(A2A_RESPONSE_INVALID));
        let (port, _) = peer(|r| {
            let b = json!({"id": r["id"], "result": {}, "error": {"code": -32001}});
            http("200 OK", "", &b.to_string())
        });
        let got = client().cancel_task(&target(port), "t", None).await;
        assert_eq!(got.error_code, Some(A2A_RESPONSE_INVALID));
    }

    #[tokio::test]
    async fn t027_fr_014_oversize_get_task_falls_back_to_list_tasks_with_too_large() {
        let big = "x".repeat(6_000);
        let (port, seen) = peer(move |r| match r["method"].as_str() {
            Some("GetTask") => rpc_ok(r, json!({"id": "t1", "status": {}, "pad": big})),
            _ => rpc_ok(r, json!({"tasks": [task()]})),
        });
        let (c, t) = (client(), target(port));
        let got = c
            .get_task(&t, "t1", Some("run1"), 0, &CallOptions::default())
            .await;
        assert!(got.ok);
        assert_eq!(got.result_availability, Some(ResultAvailability::TooLarge));
        assert_eq!(got.task.unwrap()["id"], "t1");
        assert_eq!(seen.lock().unwrap().len(), 2);
        // No contextId: the over-cap failure is reported as is.
        let got = c.get_task(&t, "t1", None, 0, &CallOptions::default()).await;
        assert_eq!(got.error_code, Some(A2A_RESPONSE_OVER_CAP));
    }

    #[tokio::test]
    async fn t027_fr_014_refused_destinations_redirects_and_transport_loss() {
        let mut c = client();
        c.allow_private = false;
        let got = c.cancel_task(&target(9), "t", None).await;
        assert_eq!(got.error_code, Some("destination_network_not_allowed"));
        let redirect = http("302 Found", "Location: http://127.0.0.1:1/\r\n", "");
        let (port, _) = peer(move |_| redirect.clone());
        let got = client().cancel_task(&target(port), "t", None).await;
        assert_eq!(got.error_code, Some("destination_redirect_not_allowed"));
        let closed = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = closed.local_addr().unwrap().port();
        drop(closed);
        let got = client().cancel_task(&target(port), "t", None).await;
        assert_eq!(got.error_code, Some(A2A_UNREACHABLE));
    }

    #[tokio::test]
    async fn t027_fr_014_a_silent_peer_is_a_timeout_not_unreachable() {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        std::thread::spawn(move || {
            let held: Vec<_> = l.incoming().flatten().collect();
            std::thread::sleep(Duration::from_secs(10));
            drop(held);
        });
        let mut c = client();
        c.timeout = Duration::from_millis(300);
        let got = c.cancel_task(&target(port), "t", None).await;
        assert_eq!(got.error_code, Some(A2A_TIMEOUT));
    }

    #[test]
    fn t027_fr_014_push_url_and_credential_redaction() {
        assert_eq!(
            push_callback_url("https://bb.example/", "run1", "tok"),
            "https://bb.example/api/a2a/push/run1/tok"
        );
        let t = target(1);
        assert!(!format!("{t:?}").contains("sekret"));
    }
}
