//! Base-URL HTTP client with the session cookie and `X-Client-Epoch`.

use crate::Result;
use reqwest::Method;
use serde_json::Value;

/// Environment-driven run configuration.
#[derive(Clone, Debug)]
pub struct Config {
    pub base_url: String,
    /// Report name: `python` or `rust`.
    pub server: String,
    pub control_token: String,
    pub epoch: Option<u32>,
}

impl Config {
    /// Reads `BB_CONFORMANCE_BASE_URL` (required), `BB_CONFORMANCE_SERVER`,
    /// `BRAIN_BUDDY_TEST_CONTROL_TOKEN` and `BB_CONFORMANCE_CLIENT_EPOCH`.
    pub fn from_env() -> Result<Self> {
        let get = |k: &str| std::env::var(k).ok().filter(|v| !v.is_empty());
        Ok(Self {
            base_url: get("BB_CONFORMANCE_BASE_URL").ok_or("BB_CONFORMANCE_BASE_URL is not set")?,
            server: get("BB_CONFORMANCE_SERVER").unwrap_or_else(|| "python".into()),
            control_token: get("BRAIN_BUDDY_TEST_CONTROL_TOKEN").unwrap_or_default(),
            epoch: get("BB_CONFORMANCE_CLIENT_EPOCH").and_then(|v| v.parse().ok()),
        })
    }
}

/// One HTTP response.
#[derive(Debug)]
pub struct Reply {
    pub status: u16,
    pub headers: reqwest::header::HeaderMap,
    pub body: String,
}

impl Reply {
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers.get(name)?.to_str().ok()
    }

    pub fn json(&self) -> Result<Value> {
        Ok(serde_json::from_str(&self.body)?)
    }
}

/// A client with its own cookie, so each synthetic owner is one session.
#[derive(Clone)]
pub struct Client {
    base: String,
    http: reqwest::Client,
    epoch: Option<u32>,
    cookie: Option<String>,
    extra: Vec<(String, String)>,
}

impl Client {
    pub fn new(cfg: &Config) -> Result<Self> {
        Ok(Self {
            base: cfg.base_url.trim_end_matches('/').to_string(),
            http: reqwest::Client::builder()
                .redirect(reqwest::redirect::Policy::none())
                .build()?,
            epoch: cfg.epoch,
            cookie: None,
            extra: Vec::new(),
        })
    }

    pub fn fresh(&self) -> Self {
        Self {
            cookie: None,
            extra: Vec::new(),
            ..self.clone()
        }
    }

    pub fn with_header(mut self, name: &str, value: &str) -> Self {
        self.extra.push((name.into(), value.into()));
        self
    }

    pub async fn post(&mut self, path: &str, body: &Value) -> Result<Reply> {
        self.send(Method::POST, path, Some(body)).await
    }

    pub async fn send(
        &mut self,
        method: Method,
        path: &str,
        body: Option<&Value>,
    ) -> Result<Reply> {
        let mut req = self.http.request(method, format!("{}{path}", self.base));
        if let Some(epoch) = self.epoch {
            req = req.header("X-Client-Epoch", epoch.to_string());
        }
        if let Some(cookie) = &self.cookie {
            req = req.header("Cookie", cookie);
        }
        for (k, v) in &self.extra {
            req = req.header(k, v);
        }
        if let Some(body) = body {
            req = req.json(body);
        }
        let resp = req.send().await?;
        let (status, headers) = (resp.status().as_u16(), resp.headers().clone());
        self.absorb_cookies(&headers);
        Ok(Reply {
            status,
            headers,
            body: resp.text().await?,
        })
    }

    fn absorb_cookies(&mut self, headers: &reqwest::header::HeaderMap) {
        for raw in headers.get_all("set-cookie") {
            let pair = raw.to_str().unwrap_or("").split(';').next().unwrap_or("");
            match pair.split_once('=') {
                Some((_, "")) => self.cookie = None,
                Some(_) => self.cookie = Some(pair.to_string()),
                None => {}
            }
        }
    }
}
