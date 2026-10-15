use super::mock_http::{serve, text};
use super::wav;
use crate::stt::openai::*;
use crate::stt::*;

fn adapter(url: &str) -> OpenAiStt {
    let mut s = SttSettings::new("sk-test".into(), "gpt-4o-mini-transcribe", url);
    s.retry_backoff_seconds = vec![0.0];
    OpenAiStt::new(s)
}

fn request(hints: &[&str]) -> SttRequest {
    SttRequest {
        operation_id: "op1".into(),
        media_ref: "m1".into(),
        language_hints: hints.iter().map(|h| h.to_string()).collect(),
        vocabulary: vec!["Brain".into(), "Buddy".into()],
        sealed_audio: wav(64),
        ..Default::default()
    }
}

#[tokio::test]
async fn request_shape_matches_python_adapter_027_fr_012() {
    let srv = serve(vec![(
        200,
        r#"{"text":"  hello   world ","usage":{"total_tokens":7,"junk":1,"seconds":2.5}}"#,
    )]);
    let r = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&["ru-RU"]))
        .await
        .unwrap();
    let raw = text(&srv.requests.lock().unwrap()[0]);
    assert!(raw.starts_with("POST "));
    assert!(raw.to_lowercase().contains("authorization: bearer sk-test"));
    assert!(raw.contains("name=\"model\"\r\n\r\ngpt-4o-mini-transcribe"));
    assert!(raw.contains("name=\"response_format\"\r\n\r\njson"));
    assert!(raw.contains("name=\"language\"\r\n\r\nru\r\n"));
    assert!(raw.contains("name=\"prompt\"\r\n\r\nKey terms: Brain, Buddy"));
    assert!(raw.contains("filename=\"recording.wav\"\r\nContent-Type: audio/wav"));
    assert_eq!(r.segments[0].text, "hello world");
    assert_eq!(r.segments[0].end_ms, 1000);
    assert_eq!(r.segments[0].language.as_deref(), Some("ru-RU"));
    assert!(r.segments[0].id.starts_with("accurate_"));
    assert_eq!(r.input_hash, sha256_hex(&wav(64)));
    assert!((r.estimated_cost_usd - 64.0 / 1e6 * 0.01 * 3.0).abs() < 1e-15);
    let mut u = r.provider_usage.clone();
    u.sort_by(|a, b| a.0.cmp(&b.0));
    assert_eq!(
        u,
        vec![
            ("seconds".to_string(), 2.5),
            ("total_tokens".to_string(), 7.0)
        ]
    );
}

#[tokio::test]
async fn multiple_hints_leave_language_unpinned_027_fr_012() {
    let srv = serve(vec![(200, r#"{"text":"x"}"#)]);
    adapter(&srv.url)
        .transcribe_sealed_audio(&request(&["en", "ru"]))
        .await
        .unwrap();
    assert!(!text(&srv.requests.lock().unwrap()[0]).contains("name=\"language\""));
}

#[tokio::test]
async fn retries_transient_statuses_then_succeeds_027_fr_012() {
    let srv = serve(vec![
        (503, "{}"),
        (429, r#"{"error":{"type":"rate_limit"}}"#),
        (200, r#"{"text":"ok"}"#),
    ]);
    let r = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&[]))
        .await
        .unwrap();
    assert_eq!(r.segments[0].text, "ok");
    assert_eq!(r.segments[0].language, None);
    assert_eq!(srv.requests.lock().unwrap().len(), 3);
}

#[tokio::test]
async fn exhausted_retries_are_retryable_with_cost_027_fr_011() {
    let srv = serve(vec![(500, "{}"), (500, "{}"), (500, "{}")]);
    let e = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&[]))
        .await
        .unwrap_err();
    assert_eq!((e.code, e.retryable), ("STT_PROVIDER_UNAVAILABLE", true));
    assert!(e.estimated_cost_usd.is_some());
}

#[tokio::test]
async fn quota_auth_and_size_errors_are_terminal_without_retry_027_fr_011() {
    for (status, body, code) in [
        (
            429,
            r#"{"error":{"code":"insufficient_quota"}}"#,
            "STT_PROVIDER_REJECTED_REQUEST",
        ),
        (401, "{}", "STT_PROVIDER_AUTHENTICATION_FAILED"),
        (413, "{}", "STT_AUDIO_TOO_LARGE"),
        (400, "{}", "STT_PROVIDER_REJECTED_REQUEST"),
    ] {
        let srv = serve(vec![(status, body)]);
        let e = adapter(&srv.url)
            .transcribe_sealed_audio(&request(&[]))
            .await
            .unwrap_err();
        assert_eq!((e.code, e.retryable), (code, false));
        assert_eq!(srv.requests.lock().unwrap().len(), 1);
    }
}

#[tokio::test]
async fn invalid_body_and_unsupported_audio_fail_closed_027_fr_012() {
    let srv = serve(vec![(200, r#"{"text":"   "}"#)]);
    let e = adapter(&srv.url)
        .transcribe_sealed_audio(&request(&[]))
        .await
        .unwrap_err();
    assert_eq!(e.code, "STT_PROVIDER_INVALID_RESPONSE");
    // Unsupported container never reaches the network (url is unroutable).
    let mut bad = request(&[]);
    bad.sealed_audio = b"not audio at all".to_vec();
    let e = adapter("http://127.0.0.1:1")
        .transcribe_sealed_audio(&bad)
        .await
        .unwrap_err();
    assert_eq!(e.code, "STT_AUDIO_FORMAT_UNSUPPORTED");
}
