//! OpenAI accurate-STT adapter (multipart POST to /v1/audio/transcriptions).

use serde_json::Value;

use super::{
    Segment, SttError, SttRequest, SttResult, SttSettings, audio_metadata, normalize, post_json,
    redacted_usage, segment_id, sha256_hex, words_ms,
};

const RETRYABLE: [u16; 7] = [408, 409, 429, 500, 502, 503, 504];

#[derive(Clone, Debug)]
pub struct OpenAiStt {
    settings: SttSettings,
}

impl OpenAiStt {
    pub fn new(settings: SttSettings) -> Self {
        Self { settings }
    }

    pub async fn transcribe_sealed_audio(&self, req: &SttRequest) -> Result<SttResult, SttError> {
        let s = &self.settings;
        let cost = s.admit(&req.sealed_audio)?;
        let (filename, content_type) = audio_metadata(&req.sealed_audio)?;
        let boundary = format!("bbstt{}", &sha256_hex(&req.sealed_audio)[..24]);
        let body = multipart(
            &boundary,
            &form_fields(s, req),
            filename,
            content_type,
            &req.sealed_audio,
        );
        let ctype = format!("multipart/form-data; boundary={boundary}");
        let payload = post_json(
            s,
            &RETRYABLE,
            |c| {
                c.post(&s.url)
                    .bearer_auth(&s.api_key)
                    .header("content-type", &ctype)
                    .body(body.clone())
            },
            is_insufficient_quota,
        )
        .await
        .map_err(|e| e.costed(cost))?;
        let invalid = || SttError::terminal("STT_PROVIDER_INVALID_RESPONSE").costed(cost);
        let text = payload
            .get("text")
            .and_then(Value::as_str)
            .ok_or_else(invalid)?;
        let text = normalize(text);
        if text.is_empty() {
            return Err(invalid());
        }
        let language = (!req.language_hints.is_empty()).then(|| req.language_hints.join(","));
        Ok(SttResult {
            provider: "openai",
            input_hash: sha256_hex(&req.sealed_audio),
            segments: vec![Segment {
                id: segment_id(req, &s.model, &text, None),
                sequence: 1,
                start_ms: 0,
                end_ms: words_ms(&text),
                text,
                confidence: None,
                language,
                model: s.model.clone(),
                supersedes_segment_ids: req.supersedes_segment_ids.clone(),
            }],
            estimated_cost_usd: cost,
            provider_usage: redacted_usage(payload.get("usage")),
        })
    }
}

/// A 429 with `insufficient_quota` is a permanently exhausted quota, not a rate limit.
fn is_insufficient_quota(payload: &Value) -> bool {
    payload
        .get("error")
        .and_then(Value::as_object)
        .is_some_and(|e| {
            ["type", "code"]
                .iter()
                .any(|k| e.get(*k).and_then(Value::as_str) == Some("insufficient_quota"))
        })
}

/// A single hint pins the decode language; zero or several leave it to auto-detect.
fn form_fields(s: &SttSettings, req: &SttRequest) -> Vec<(&'static str, String)> {
    let mut f = vec![
        ("model", s.model.clone()),
        ("response_format", "json".to_string()),
    ];
    if let [hint] = req.language_hints.as_slice() {
        let h = hint.trim().to_lowercase();
        let lang = match h.as_str() {
            "en" | "en-us" | "en-gb" => "en".to_string(),
            "ru" | "ru-ru" => "ru".to_string(),
            _ => h.split('-').next().unwrap_or_default().to_string(),
        };
        f.push(("language", lang));
    }
    if !req.vocabulary.is_empty() {
        f.push((
            "prompt",
            format!("Key terms: {}", req.vocabulary.join(", ")),
        ));
    }
    f
}

fn multipart(
    boundary: &str,
    fields: &[(&str, String)],
    filename: &str,
    content_type: &str,
    audio: &[u8],
) -> Vec<u8> {
    let mut b = Vec::with_capacity(audio.len() + 512);
    for (name, value) in fields {
        let part = format!(
            "--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
        );
        b.extend_from_slice(part.as_bytes());
    }
    let head = format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n"
    );
    b.extend_from_slice(head.as_bytes());
    b.extend_from_slice(audio);
    b.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    b
}
