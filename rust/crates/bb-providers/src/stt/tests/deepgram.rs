use super::mock_http::{serve, text};
use super::wav;
use crate::stt::deepgram::*;
use crate::stt::*;

fn adapter(url: &str) -> DeepgramStt {
    let mut s = SttSettings::new("dg-test".into(), "nova-3", url);
    s.retry_backoff_seconds = vec![0.0];
    DeepgramStt::new(s)
}

fn request(hints: &[&str]) -> SttRequest {
    SttRequest {
        operation_id: "op1".into(),
        media_ref: "m1".into(),
        language_hints: hints.iter().map(|h| h.to_string()).collect(),
        sealed_audio: wav(64),
        ..Default::default()
    }
}

const UTTERANCES: &str = r#"{"metadata":{"duration":3.0},"results":{"utterances":[
    {"transcript":"Да.","start":0.0,"end":0.5,"confidence":0.9,"words":[{"language":"ru"},{"language":"en"},{"language":"ru"}]},
    {"transcript":"  ","start":1,"end":2},
    {"transcript":"Да.","start":1.0,"end":1.0}]}}"#;

#[tokio::test]
async fn request_shape_and_utterance_segments_match_python_027_fr_012() {
    let srv = serve(vec![(200, UTTERANCES)]);
    let r = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&["ru-RU"]))
        .await
        .unwrap();
    let raw = text(&srv.requests.lock().unwrap()[0]);
    let line = raw.lines().next().unwrap();
    assert!(
        line.contains("model=nova-3&smart_format=true&punctuate=true&utterances=true&language=ru "),
        "{line}"
    );
    let lower = raw.to_lowercase();
    assert!(lower.contains("authorization: token dg-test"));
    assert!(lower.contains("content-type: audio/wav"));
    assert_eq!(r.segments.len(), 2);
    let (a, b) = (&r.segments[0], &r.segments[1]);
    assert_eq!((a.sequence, a.start_ms, a.end_ms), (1, 0, 500));
    assert_eq!(a.language.as_deref(), Some("en,ru"));
    assert_eq!(a.confidence, Some(0.9));
    // Non-positive span falls back to 500 ms per word; identical text gets a distinct id.
    assert_eq!((b.sequence, b.start_ms, b.end_ms), (2, 1000, 1500));
    assert_eq!(b.language.as_deref(), Some("ru"));
    assert_ne!(a.id, b.id);
    assert_eq!(
        r.provider_usage,
        vec![("duration_seconds".to_string(), 3.0)]
    );
}

#[tokio::test]
async fn falls_back_to_channel_transcript_and_multi_language_027_fr_012() {
    let body = r#"{"metadata":{"duration":2.5},"results":{"channels":[{"alternatives":[{"transcript":"hello there","confidence":0.5}]}]}}"#;
    let srv = serve(vec![(200, body)]);
    let r = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&[]))
        .await
        .unwrap();
    assert!(text(&srv.requests.lock().unwrap()[0]).contains("language=multi "));
    assert_eq!((r.segments.len(), r.segments[0].end_ms), (1, 2500));
    assert_eq!(r.segments[0].language.as_deref(), Some("multi"));
}

#[tokio::test]
async fn empty_payload_and_status_classes_follow_python_027_fr_011() {
    let srv = serve(vec![(200, r#"{"results":{}}"#)]);
    let e = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&[]))
        .await
        .unwrap_err();
    assert_eq!(
        (e.code, e.retryable),
        ("STT_PROVIDER_INVALID_RESPONSE", false)
    );
    // 409 is retryable for OpenAI only; Deepgram treats it as a terminal rejection.
    let srv = serve(vec![(409, "{}")]);
    let e = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&[]))
        .await
        .unwrap_err();
    assert_eq!(
        (e.code, e.retryable),
        ("STT_PROVIDER_REJECTED_REQUEST", false)
    );
    let srv = serve(vec![(429, "{}"), (502, "{}"), (504, "{}")]);
    let e = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&[]))
        .await
        .unwrap_err();
    assert_eq!((e.code, e.retryable), ("STT_PROVIDER_UNAVAILABLE", true));
    assert_eq!(srv.requests.lock().unwrap().len(), 3);
}

#[tokio::test]
async fn cost_cap_blocks_before_any_network_call_027_fr_011() {
    let mut s = SttSettings::new("dg-test".into(), "nova-3", "http://127.0.0.1:1");
    s.max_cost_usd_per_operation = 0.0001;
    let a = DeepgramStt::new(s);
    let mut r = request(&[]);
    r.sealed_audio = wav(5_000_000);
    let e = a.transcribe_sealed_audio(&r).await.unwrap_err();
    assert_eq!(e.code, "STT_COST_LIMIT_EXCEEDED");
}
