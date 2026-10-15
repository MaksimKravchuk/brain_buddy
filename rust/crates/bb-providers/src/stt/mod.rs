//! Speech-to-text adapters over sealed original audio (OpenAI, Deepgram).
//!
//! Mirrors backend/app/workflows/voice_brain_dump/adapters: same model pins,
//! cost caps, retry classes and request shapes. Errors carry a code and the
//! worst-case estimated cost only, never provider payloads.

pub mod deepgram;
pub mod openai;

use std::time::Duration;

pub use deepgram::DeepgramStt;
pub use openai::OpenAiStt;
use serde_json::Value;

use crate::keys;

pub const OPENAI_URL: &str = "https://api.openai.com/v1/audio/transcriptions";
pub const DEEPGRAM_URL: &str = "https://api.deepgram.com/v1/listen";

#[derive(Clone, Debug, Default)]
pub struct SttRequest {
    pub operation_id: String,
    pub media_ref: String,
    pub language_hints: Vec<String>,
    pub vocabulary: Vec<String>,
    pub supersedes_segment_ids: Vec<String>,
    pub sealed_audio: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Segment {
    pub id: String,
    pub sequence: u32,
    pub start_ms: i64,
    pub end_ms: i64,
    pub text: String,
    pub confidence: Option<f64>,
    pub language: Option<String>,
    pub model: String,
    pub supersedes_segment_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SttResult {
    pub provider: &'static str,
    pub input_hash: String,
    pub segments: Vec<Segment>,
    pub estimated_cost_usd: f64,
    pub provider_usage: Vec<(String, f64)>,
}

/// Retryable failures may be retried by the caller's job; terminal ones may not.
#[derive(Clone, Debug, PartialEq)]
pub struct SttError {
    pub code: &'static str,
    pub retryable: bool,
    pub estimated_cost_usd: Option<f64>,
}

impl SttError {
    fn terminal(code: &'static str) -> Self {
        Self {
            code,
            retryable: false,
            estimated_cost_usd: None,
        }
    }

    fn retryable(code: &'static str) -> Self {
        Self {
            code,
            retryable: true,
            estimated_cost_usd: None,
        }
    }

    fn costed(mut self, cost: f64) -> Self {
        self.estimated_cost_usd = Some(cost);
        self
    }
}

#[derive(Clone, Debug)]
pub struct SttSettings {
    pub api_key: String,
    pub model: String,
    pub url: String,
    pub timeout: Duration,
    pub max_retries: u32,
    pub retry_backoff_seconds: Vec<f64>,
    pub max_cost_usd_per_operation: f64,
    pub estimated_cost_usd_per_megabyte: f64,
}

impl SttSettings {
    pub fn new(api_key: String, model: &str, url: &str) -> Self {
        Self {
            api_key,
            model: model.to_string(),
            url: url.to_string(),
            timeout: Duration::from_secs(180),
            max_retries: 2,
            retry_backoff_seconds: vec![1.0, 2.0],
            max_cost_usd_per_operation: 0.50,
            estimated_cost_usd_per_megabyte: 0.01,
        }
    }

    /// Worst case across the adapter's own retry budget (admission and recorded spend).
    fn estimated_cost(&self, audio_len: usize) -> f64 {
        (audio_len as f64 / 1_000_000.0)
            * self.estimated_cost_usd_per_megabyte
            * f64::from(self.max_retries + 1)
    }

    /// Rejects empty audio and over-cap operations before any network call.
    fn admit(&self, audio: &[u8]) -> Result<f64, SttError> {
        if audio.is_empty() {
            return Err(SttError::terminal("STT_AUDIO_MISSING"));
        }
        let cost = self.estimated_cost(audio.len());
        if cost > self.max_cost_usd_per_operation {
            return Err(SttError::terminal("STT_COST_LIMIT_EXCEEDED"));
        }
        Ok(cost)
    }

    async fn backoff(&self, attempt: u32) {
        if self.retry_backoff_seconds.is_empty() {
            return;
        }
        let i = (attempt as usize).min(self.retry_backoff_seconds.len() - 1);
        tokio::time::sleep(Duration::from_secs_f64(self.retry_backoff_seconds[i])).await;
    }
}

/// POST with the Python adapters' retry policy; returns the parsed JSON body.
/// `quota_terminal` marks a 429 that must not burn the retry budget.
async fn post_json(
    s: &SttSettings,
    retryable: &[u16],
    build: impl Fn(&reqwest::Client) -> reqwest::RequestBuilder,
    quota_terminal: impl Fn(&Value) -> bool,
) -> Result<Value, SttError> {
    let client = reqwest::Client::builder()
        .timeout(s.timeout)
        .build()
        .map_err(|_| SttError::terminal("STT_PROVIDER_UNAVAILABLE"))?;
    let mut attempt = 0;
    loop {
        let response = match build(&client).send().await {
            Ok(r) => r,
            Err(_) if attempt >= s.max_retries => {
                return Err(SttError::retryable("STT_PROVIDER_UNAVAILABLE"));
            }
            Err(_) => {
                s.backoff(attempt).await;
                attempt += 1;
                continue;
            }
        };
        let status = response.status().as_u16();
        if status < 400 {
            let bytes = response.bytes().await;
            return bytes
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .ok_or(SttError::terminal("STT_PROVIDER_INVALID_RESPONSE"));
        }
        if status == 429 {
            let body: Value = response.json().await.unwrap_or(Value::Null);
            if quota_terminal(&body) {
                return Err(SttError::terminal("STT_PROVIDER_REJECTED_REQUEST"));
            }
        }
        if retryable.contains(&status) {
            if attempt >= s.max_retries {
                return Err(SttError::retryable("STT_PROVIDER_UNAVAILABLE"));
            }
            s.backoff(attempt).await;
            attempt += 1;
            continue;
        }
        return Err(match status {
            401 | 403 => SttError::terminal("STT_PROVIDER_AUTHENTICATION_FAILED"),
            413 => SttError::terminal("STT_AUDIO_TOO_LARGE"),
            _ => SttError::terminal("STT_PROVIDER_REJECTED_REQUEST"),
        });
    }
}

/// Sniffs the container signature (never trusts upload metadata): (filename, MIME).
pub(crate) fn audio_metadata(a: &[u8]) -> Result<(&'static str, &'static str), SttError> {
    if a.starts_with(b"\x1aE\xdf\xa3") {
        Ok(("recording.webm", "audio/webm"))
    } else if a.starts_with(b"RIFF") && a.get(8..12) == Some(b"WAVE") {
        Ok(("recording.wav", "audio/wav"))
    } else if a.len() >= 12 && &a[4..8] == b"ftyp" {
        Ok(("recording.m4a", "audio/mp4"))
    } else if a.len() >= 2 && a[0] == 0xFF && a[1] & 0xF0 == 0xF0 {
        Ok(("recording.aac", "audio/aac"))
    } else {
        Err(SttError::terminal("STT_AUDIO_FORMAT_UNSUPPORTED"))
    }
}

pub(crate) fn normalize(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub(crate) fn words_ms(text: &str) -> i64 {
    (text.split_whitespace().count() as i64 * 500).max(1)
}

/// Aggregate numeric counters safe for reports (SAFE_PROVIDER_USAGE_FIELDS).
pub(crate) fn redacted_usage(v: Option<&Value>) -> Vec<(String, f64)> {
    const SAFE: [&str; 7] = [
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "input_audio_tokens",
        "output_audio_tokens",
        "seconds",
        "duration_seconds",
    ];
    let Some(map) = v.and_then(Value::as_object) else {
        return Vec::new();
    };
    map.iter()
        .filter(|(k, _)| SAFE.contains(&k.as_str()))
        .filter_map(|(k, x)| x.as_f64().map(|f| (k.clone(), f)))
        .collect()
}

pub(crate) fn segment_id(
    req: &SttRequest,
    model: &str,
    text: &str,
    index: Option<usize>,
) -> String {
    let mut parts = vec![
        req.operation_id.as_str(),
        req.media_ref.as_str(),
        model,
        text,
    ];
    let idx = index.map(|i| i.to_string());
    if let Some(i) = idx.as_deref() {
        parts.push(i);
    }
    format!("accurate_{}", &sha256_hex(parts.join("|").as_bytes())[..12])
}

pub(crate) fn pct_encode(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

/// Which accurate-STT adapter a deployment gets. A missing key degrades to
/// `Disabled`; `Deterministic` is the test-environment fake owned by the caller.
pub enum SttRole {
    Disabled,
    Deterministic,
    OpenAi(OpenAiStt),
    Deepgram(DeepgramStt),
}

impl SttRole {
    /// Resolves BRAIN_BUDDY_VOICE_ACCURATE_STT_* (as in backend core/config.py).
    /// `test_env` selects the deterministic default; production refuses it.
    pub fn from_env(get: impl Fn(&str) -> Option<String>, test_env: bool) -> Result<Self, String> {
        let var = |n: &str| get(n).filter(|v| !v.is_empty());
        let provider = var("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER").unwrap_or_else(|| {
            if test_env {
                "deterministic"
            } else if var("OPENAI_API_KEY").is_some() {
                "openai"
            } else {
                "disabled"
            }
            .to_string()
        });
        let (default_model, default_key_env, url) = match provider.as_str() {
            "deepgram" => ("nova-3", keys::DEFAULT_DEEPGRAM_KEY_ENV, DEEPGRAM_URL),
            "openai" => (
                "gpt-4o-mini-transcribe",
                keys::DEFAULT_OPENAI_KEY_ENV,
                OPENAI_URL,
            ),
            "deterministic" if !test_env => {
                return Err("Production cannot use deterministic accurate STT.".into());
            }
            "deterministic" => return Ok(Self::Deterministic),
            _ => return Ok(Self::Disabled),
        };
        let key_env = var("BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV")
            .unwrap_or_else(|| default_key_env.to_string());
        let Some(api_key) = keys::resolve_with(&key_env, &get) else {
            return Ok(Self::Disabled);
        };
        let model = var("BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL").unwrap_or(default_model.into());
        let mut s = SttSettings::new(api_key, &model, url);
        let num = |n: &str| var(&format!("BRAIN_BUDDY_VOICE_ACCURATE_STT_{n}"));
        let bad = |n: &str| format!("invalid BRAIN_BUDDY_VOICE_ACCURATE_STT_{n}");
        if let Some(v) = num("TIMEOUT_SECONDS") {
            s.timeout = Duration::from_secs_f64(v.parse().map_err(|_| bad("TIMEOUT_SECONDS"))?);
        }
        if let Some(v) = num("MAX_RETRIES") {
            s.max_retries = v.parse().map_err(|_| bad("MAX_RETRIES"))?;
        }
        if let Some(v) = num("RETRY_BACKOFF_SECONDS") {
            s.retry_backoff_seconds = v
                .split(',')
                .filter(|p| !p.trim().is_empty())
                .map(|p| p.trim().parse().map_err(|_| bad("RETRY_BACKOFF_SECONDS")))
                .collect::<Result<_, _>>()?;
        }
        if let Some(v) = num("MAX_COST_USD") {
            s.max_cost_usd_per_operation = v.parse().map_err(|_| bad("MAX_COST_USD"))?;
        }
        if let Some(v) = num("ESTIMATED_COST_USD_PER_MB") {
            s.estimated_cost_usd_per_megabyte =
                v.parse().map_err(|_| bad("ESTIMATED_COST_USD_PER_MB"))?;
        }
        Ok(if provider == "deepgram" {
            Self::Deepgram(DeepgramStt::new(s))
        } else {
            Self::OpenAi(OpenAiStt::new(s))
        })
    }
}

pub fn sha256_hex(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    for block in msg.chunks(64) {
        let mut w = [0u32; 64];
        for (i, c) in block.chunks(4).enumerate() {
            w[i] = u32::from_be_bytes([c[0], c[1], c[2], c[3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let mut v = h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ (!v[4] & v[6]);
            let t1 = v[7]
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);
            v = [
                t1.wrapping_add(t2),
                v[0],
                v[1],
                v[2],
                v[3].wrapping_add(t1),
                v[4],
                v[5],
                v[6],
            ];
        }
        for (a, b) in h.iter_mut().zip(v) {
            *a = a.wrapping_add(b);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}
#[cfg(test)]
mod tests;
