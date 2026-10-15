//! Deepgram accurate-STT adapter (raw audio POST to /v1/listen, nova-3).

use serde_json::Value;

use super::{
    Segment, SttError, SttRequest, SttResult, SttSettings, audio_metadata, normalize, pct_encode,
    post_json, redacted_usage, segment_id, sha256_hex, words_ms,
};

const RETRYABLE: [u16; 6] = [408, 429, 500, 502, 503, 504];

#[derive(Clone, Debug)]
pub struct DeepgramStt {
    settings: SttSettings,
}

impl DeepgramStt {
    pub fn new(settings: SttSettings) -> Self {
        Self { settings }
    }

    pub async fn transcribe_sealed_audio(&self, req: &SttRequest) -> Result<SttResult, SttError> {
        let s = &self.settings;
        let cost = s.admit(&req.sealed_audio)?;
        let content_type = audio_metadata(&req.sealed_audio)?.1;
        let lang = language_param(req);
        let url = format!(
            "{}?model={}&smart_format=true&punctuate=true&utterances=true&language={}",
            s.url,
            pct_encode(&s.model),
            pct_encode(&lang)
        );
        let payload = post_json(
            s,
            &RETRYABLE,
            |c| {
                c.post(&url)
                    .header("authorization", format!("Token {}", s.api_key))
                    .header("content-type", content_type)
                    .body(req.sealed_audio.clone())
            },
            |_| false,
        )
        .await
        .map_err(|e| e.costed(cost))?;

        let duration = payload
            .pointer("/metadata/duration")
            .and_then(Value::as_f64);
        let mut segments = utterance_segments(s, req, &payload, &lang);
        if segments.is_empty() {
            let Some(fallback) = channel_segment(s, req, &payload, &lang, duration) else {
                return Err(SttError::terminal("STT_PROVIDER_INVALID_RESPONSE").costed(cost));
            };
            segments = vec![fallback];
        }
        let usage = duration.map(|d| serde_json::json!({ "duration_seconds": d }));
        Ok(SttResult {
            provider: "deepgram",
            input_hash: sha256_hex(&req.sealed_audio),
            segments,
            estimated_cost_usd: cost,
            provider_usage: redacted_usage(usage.as_ref()),
        })
    }
}

/// One hint pins the language (its primary subtag); otherwise `multi`.
fn language_param(req: &SttRequest) -> String {
    if let [hint] = req.language_hints.as_slice() {
        let primary = hint.trim().to_lowercase();
        let primary = primary.split('-').next().unwrap_or_default();
        if !primary.is_empty() {
            return primary.to_string();
        }
    }
    "multi".to_string()
}

fn to_ms(v: Option<&Value>) -> i64 {
    v.and_then(Value::as_f64)
        .filter(|s| *s >= 0.0)
        .map_or(0, |s| (s * 1000.0) as i64)
}

/// Comma-joined sorted distinct per-word language tags.
fn word_languages(item: &Value) -> Option<String> {
    let mut langs: Vec<&str> = item
        .get("words")?
        .as_array()?
        .iter()
        .filter_map(|w| w.get("language").and_then(Value::as_str))
        .filter(|l| !l.is_empty())
        .collect();
    langs.sort_unstable();
    langs.dedup();
    (!langs.is_empty()).then(|| langs.join(","))
}

fn transcript(item: &Value) -> Option<String> {
    let t = normalize(item.get("transcript")?.as_str()?);
    (!t.is_empty()).then_some(t)
}

fn utterance_segments(
    s: &SttSettings,
    req: &SttRequest,
    payload: &Value,
    lang: &str,
) -> Vec<Segment> {
    let items = payload
        .pointer("/results/utterances")
        .and_then(Value::as_array);
    let mut out: Vec<Segment> = Vec::new();
    for u in items.into_iter().flatten().filter(|u| u.is_object()) {
        let Some(text) = transcript(u) else { continue };
        let sequence = out.len() + 1;
        let start_ms = to_ms(u.get("start"));
        let mut end_ms = to_ms(u.get("end"));
        if end_ms <= start_ms {
            end_ms = start_ms + words_ms(&text);
        }
        out.push(Segment {
            id: segment_id(req, &s.model, &text, Some(sequence)),
            sequence: sequence as u32,
            start_ms,
            end_ms,
            text,
            confidence: u.get("confidence").and_then(Value::as_f64),
            language: word_languages(u).or_else(|| Some(lang.to_string())),
            model: s.model.clone(),
            supersedes_segment_ids: req.supersedes_segment_ids.clone(),
        });
    }
    out
}

/// Single-blob fallback when the optional `utterances` array is missing or unusable.
fn channel_segment(
    s: &SttSettings,
    req: &SttRequest,
    payload: &Value,
    lang: &str,
    duration: Option<f64>,
) -> Option<Segment> {
    let alt = payload
        .pointer("/results/channels/0/alternatives/0")
        .filter(|a| a.is_object())?;
    let text = transcript(alt)?;
    let end_ms = match duration {
        Some(d) if d > 0.0 => ((d * 1000.0) as i64).max(1),
        _ => words_ms(&text),
    };
    Some(Segment {
        id: segment_id(req, &s.model, &text, None),
        sequence: 1,
        start_ms: 0,
        end_ms,
        text,
        confidence: alt.get("confidence").and_then(Value::as_f64),
        language: word_languages(alt).or_else(|| Some(lang.to_string())),
        model: s.model.clone(),
        supersedes_segment_ids: req.supersedes_segment_ids.clone(),
    })
}
