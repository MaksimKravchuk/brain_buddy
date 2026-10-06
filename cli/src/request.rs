use crate::{
    command::Request,
    config::Config,
    credential::Credential,
    error::{Error, Result},
};
use reqwest::{
    blocking::{Client, Response},
    header::{CONTENT_TYPE, COOKIE, HeaderValue},
};
use serde_json::{Value, json};
use std::{
    io::Read,
    time::{Duration, SystemTime},
};

pub const RESPONSE_LIMIT: usize = 8 * 1024 * 1024;
pub struct Reply {
    pub value: Value,
    pub headers: reqwest::header::HeaderMap,
}
pub fn client() -> Result<Client> {
    Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(30))
        .user_agent(concat!("BrainBuddyCLI/", env!("CARGO_PKG_VERSION")))
        .build()
        .map_err(|_| Error::protocol())
}

pub fn send(
    client: &Client,
    config: &Config,
    r: &Request,
    credential: Option<&Credential>,
) -> Result<Reply> {
    let method = reqwest::Method::from_bytes(r.method.as_bytes())
        .map_err(|_| Error::invalid("Unsupported method."))?;
    let mut request = client
        .request(method, config.url(&r.path)?)
        .query(&r.query)
        .header("Accept", "application/json");
    if let Some(credential) = credential {
        let mut header =
            HeaderValue::from_str(&format!("{}={}", credential.cookie_name, *credential.token))
                .map_err(|_| Error::auth())?;
        header.set_sensitive(true);
        request = request.header(COOKIE, header);
    }
    if let Some(key) = &r.key {
        request = request.header("Idempotency-Key", key);
    }
    if let Some(body) = &r.body {
        request = request.json(body);
    }
    let response = request.send().map_err(|_| {
        let mut error = Error::new(
            "transport_error",
            "Request failed or timed out. Inspect state before repeating a write.",
            8,
        );
        if r.method != "GET" {
            error.delivery_unknown = Some(true);
            error.idempotency_key = r.key.clone();
        }
        error
    })?;
    decode(response, r, credential)
}

fn decode(mut response: Response, r: &Request, credential: Option<&Credential>) -> Result<Reply> {
    let status = response.status();
    let headers = response.headers().clone();
    let reference = headers
        .get("X-Correlation-ID")
        .and_then(|h| h.to_str().ok())
        .filter(|v| {
            v.len() <= 128
                && v.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_-.:".contains(&b))
                && credential.is_none_or(|c| !v.contains(&*c.token))
                && r.body
                    .as_ref()
                    .and_then(|b| b.get("device_code"))
                    .and_then(Value::as_str)
                    .is_none_or(|proof| !v.contains(proof))
        })
        .map(str::to_owned);
    let limit = if status.is_success() {
        RESPONSE_LIMIT
    } else {
        16384
    };
    let mut bytes = Vec::new();
    let body_ok = response
        .content_length()
        .is_none_or(|length| length <= limit as u64)
        && Read::take(&mut response, (limit + 1) as u64)
            .read_to_end(&mut bytes)
            .is_ok()
        && bytes.len() <= limit;
    let mut failure = if status.is_success() || status.is_redirection() {
        Error::protocol()
    } else {
        let (code, message, exit) = match status.as_u16() {
            401 => (
                "authentication_required",
                "Session is invalid or expired. Run bb auth login.",
                3,
            ),
            403 => (
                "forbidden",
                "This account cannot perform this operation.",
                4,
            ),
            404 => ("not_found", "Resource or capability is unavailable.", 5),
            409 => (
                "conflict",
                "Revision or request conflicts with current server state.",
                6,
            ),
            429 => (
                "rate_limited",
                "Request was rate limited; respect retry timing.",
                7,
            ),
            500..=599 => ("server_error", "Server could not complete the request.", 9),
            _ => ("invalid_request", "Server rejected the request.", 2),
        };
        Error::new(code, message, exit)
    };
    failure.http_status = Some(status.as_u16());
    failure.reference_id = reference;
    failure.retry_after_seconds = headers
        .get("Retry-After")
        .and_then(|h| h.to_str().ok())
        .and_then(|v| {
            v.parse::<u64>().ok().or_else(|| {
                httpdate::parse_http_date(v)
                    .ok()
                    .and_then(|time| time.duration_since(SystemTime::now()).ok())
                    .map(|d| d.as_secs())
            })
        })
        .map(|v| v.min(86400));
    if status.is_success() && r.method != "GET" {
        failure.mutation_confirmed = Some(true);
        failure.delivery_unknown = Some(false);
        failure.idempotency_key = r.key.clone();
    }
    if status.as_u16() == 204 {
        return Ok(Reply {
            value: Value::Null,
            headers,
        });
    }
    let json_type = headers
        .get(CONTENT_TYPE)
        .and_then(|h| h.to_str().ok())
        .is_some_and(|t| {
            let media = t.split(';').next().unwrap_or("").trim();
            media == "application/json" || media.ends_with("+json")
        });
    let value = if body_ok && json_type {
        serde_json::from_slice::<Value>(&bytes).ok()
    } else {
        None
    };
    if status.is_success() {
        return value.map(|value| Reply { value, headers }).ok_or(failure);
    }
    if let Some(value) = value {
        let mut detail = serde_json::Map::new();
        if let Some(source) = value.get("detail").and_then(Value::as_object) {
            for key in ["expected_revision", "actual_revision", "current_revision"] {
                if let Some(v) = source.get(key).filter(|v| v.is_u64()) {
                    detail.insert(key.into(), v.clone());
                }
            }
            if let Some(code) = source
                .get("code")
                .and_then(Value::as_str)
                .filter(|_| r.path.starts_with("/auth/device/"))
            {
                let auth = match code {
                    "authorization_pending" => Some((
                        "authorization_pending",
                        "Waiting for explicit browser approval.",
                        2,
                    )),
                    "slow_down" => Some(("slow_down", "Increase the polling interval.", 2)),
                    "authorization_denied" => {
                        Some(("authorization_denied", "Authorization was denied.", 11))
                    }
                    "authorization_expired" => Some((
                        "authorization_expired",
                        "Authorization expired; start a fresh login.",
                        11,
                    )),
                    "authorization_consumed" => Some((
                        "authorization_consumed",
                        "Authorization was consumed; start a fresh login.",
                        11,
                    )),
                    "invalid_device_code" => {
                        Some(("invalid_device_code", "Authorization proof is invalid.", 11))
                    }
                    "cli_auth_unavailable" => Some((
                        "cli_auth_unavailable",
                        "CLI connections are unavailable.",
                        5,
                    )),
                    _ => None,
                };
                if let Some((code, message, exit)) = auth {
                    failure.code = code;
                    failure.message = message;
                    failure.exit = exit;
                    detail.insert("code".into(), json!(code));
                }
            }
        }
        if !detail.is_empty() {
            failure.detail = Some(Box::new(Value::Object(detail)));
        }
    }
    Err(failure)
}
