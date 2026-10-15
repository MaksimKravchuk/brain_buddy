//! Mock-HTTP tests: a loopback server scripts responses; no real provider is called.

use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::{Arc, Mutex};

use super::*;

/// Serves one scripted `(status, body)` per connection; returns the endpoint and request log.
fn mock(script: Vec<(u16, String)>) -> (String, Arc<Mutex<Vec<String>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!(
        "http://{}/v1/chat/completions",
        listener.local_addr().unwrap()
    );
    let log = Arc::new(Mutex::new(Vec::new()));
    let seen = log.clone();
    std::thread::spawn(move || {
        for (status, body) in script {
            let (mut s, _) = listener.accept().unwrap();
            let mut buf = Vec::new();
            let mut chunk = [0u8; 8192];
            loop {
                let n = s.read(&mut chunk).unwrap();
                buf.extend_from_slice(&chunk[..n]);
                let text = String::from_utf8_lossy(&buf).to_string();
                if let Some((head, rest)) = text.split_once("\r\n\r\n") {
                    let want = head
                        .to_lowercase()
                        .split("content-length: ")
                        .nth(1)
                        .and_then(|v| v.split("\r\n").next()?.trim().parse::<usize>().ok())
                        .unwrap_or(0);
                    if rest.len() >= want {
                        break;
                    }
                }
                if n == 0 {
                    break;
                }
            }
            seen.lock()
                .unwrap()
                .push(String::from_utf8_lossy(&buf).to_string());
            let resp = format!(
                "HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                body.len()
            );
            s.write_all(resp.as_bytes()).unwrap();
        }
    });
    (url, log)
}

fn chat(content: &str) -> String {
    json!({"choices": [{"message": {"content": content}}]}).to_string()
}

fn adapter(endpoint: String, edit: impl FnOnce(&mut Settings)) -> OpenAiReconciler {
    let mut s = Settings::from_env(|_| None);
    s.endpoint = endpoint;
    s.retry_backoff_seconds = vec![0.0];
    edit(&mut s);
    OpenAiReconciler::new(s, "sk-test".into())
}

fn request() -> ReconcileRequest {
    ReconcileRequest {
        operation_id: "op1".into(),
        transcript_segments: vec![json!({"id": "s1", "text": "Купить молоко"})],
        ..Default::default()
    }
}

const OK: &str = r#"{"operations":[{"operation":"add","proposal_id":null,"title":"Купить молоко","source_segment_ids":["s1"],"predecessor_ids":[],"base_revision":null,"confidence":0.9}]}"#;

#[test]
fn reconciler_027_fr_012_settings_defaults_and_overrides() {
    let d = Settings::from_env(|_| None);
    assert_eq!(
        (d.provider, d.model.as_str(), d.timeout_seconds),
        (Provider::Disabled, "gpt-4o", 30.0)
    );
    assert_eq!(
        (d.max_retries, d.retry_backoff_seconds.clone()),
        (2, vec![1.0, 2.0])
    );
    assert_eq!(
        (d.max_cost_usd, d.cost_usd_per_mb, d.endpoint.as_str()),
        (0.5, 0.01, DEFAULT_ENDPOINT)
    );
    let o = Settings::from_env(|k| match k {
        "BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER" => Some("openai".into()),
        "BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS" => Some("0.5, 3".into()),
        _ => None,
    });
    assert_eq!(
        (o.provider, o.retry_backoff_seconds),
        (Provider::OpenAi, vec![0.5, 3.0])
    );
}

#[test]
fn reconciler_027_fr_012_openai_without_key_degrades_to_disabled() {
    let mut s = Settings::from_env(|_| None);
    s.provider = Provider::OpenAi;
    assert_eq!(
        Reconciler::build(s.clone(), |_| None).provider_id(),
        "disabled"
    );
    let r = Reconciler::build(s, |n| (n == "OPENAI_API_KEY").then(|| "k".into()));
    assert_eq!(
        (r.provider_id(), r.requires_external_processing()),
        ("openai", true)
    );
}

#[tokio::test]
async fn reconciler_027_fr_011_disabled_fails_closed_and_deterministic_adds() {
    let err = Reconciler::Disabled
        .reconcile(&request())
        .await
        .unwrap_err();
    assert_eq!(
        err.failure,
        Failure::Terminal("RECONCILER_PROVIDER_DISABLED")
    );
    let ok = Reconciler::Deterministic
        .reconcile(&request())
        .await
        .unwrap();
    assert_eq!(ok.operations[0].source_segment_ids, vec!["s1".to_string()]);
}

#[tokio::test]
async fn reconciler_027_fr_012_request_shape_and_parsing() {
    let (url, log) = mock(vec![(200, chat(OK))]);
    let a = adapter(url, |_| {});
    let out = a.reconcile(&request()).await.unwrap();
    assert_eq!(out.operations[0].title.as_deref(), Some("Купить молоко"));
    assert_eq!(out.operations[0].confidence, Some(0.9));
    let raw = log.lock().unwrap()[0].clone();
    assert!(raw.to_lowercase().contains("authorization: bearer sk-test"));
    let body: Value = serde_json::from_str(raw.split_once("\r\n\r\n").unwrap().1).unwrap();
    assert_eq!(
        (body["model"].as_str(), body["temperature"].as_i64()),
        (Some("gpt-4o"), Some(0))
    );
    assert_eq!(
        body["response_format"]["json_schema"]["strict"],
        json!(true)
    );
    // No active proposals: only `add` is offered, and the prompt says so.
    assert_eq!(
        body["response_format"]["json_schema"]["schema"]["properties"]["operations"]["items"]["properties"]
            ["operation"]["enum"],
        json!(["add"])
    );
    assert!(
        body["messages"][0]["content"]
            .as_str()
            .unwrap()
            .contains("only add operations are valid")
    );
    let user: Value =
        serde_json::from_str(body["messages"][1]["content"].as_str().unwrap()).unwrap();
    assert_eq!(user["operation_id"], "op1");
    assert_eq!(user["proposals"], json!([]));
}

#[tokio::test]
async fn reconciler_027_fr_012_retries_5xx_then_succeeds() {
    let (url, log) = mock(vec![
        (503, "{}".into()),
        (429, "{}".into()),
        (200, chat(OK)),
    ]);
    assert!(adapter(url, |_| {}).reconcile(&request()).await.is_ok());
    assert_eq!(log.lock().unwrap().len(), 3);
}

#[tokio::test]
async fn reconciler_027_fr_012_retry_budget_exhausted_is_retryable() {
    let (url, log) = mock(vec![(500, "{}".into()); 2]);
    let err = adapter(url, |s| s.max_retries = 1)
        .reconcile(&request())
        .await
        .unwrap_err();
    assert_eq!(
        err.failure,
        Failure::Retryable("RECONCILER_PROVIDER_RETRYABLE")
    );
    assert_eq!(log.lock().unwrap().len(), 2);
    assert!(err.estimated_cost_usd > 0.0);
}

#[tokio::test]
async fn reconciler_027_fr_012_client_errors_and_bad_bodies_are_terminal() {
    let (url, log) = mock(vec![(400, "{}".into())]);
    let err = adapter(url, |_| {})
        .reconcile(&request())
        .await
        .unwrap_err();
    assert_eq!(
        err.failure,
        Failure::Terminal("RECONCILER_PROVIDER_REJECTED")
    );
    assert_eq!(log.lock().unwrap().len(), 1);
    for body in [chat("not json"), chat("[]"), "{}".to_string()] {
        let (url, _) = mock(vec![(200, body)]);
        let err = adapter(url, |_| {})
            .reconcile(&request())
            .await
            .unwrap_err();
        assert_eq!(
            err.failure,
            Failure::Terminal("RECONCILER_INVALID_RESPONSE")
        );
    }
}

#[tokio::test]
async fn reconciler_027_fr_012_invalid_envelope_is_validation() {
    for content in [
        r#"{"operations":[],"extra":1}"#,
        r#"{"operations":[{"operation":"drop"}]}"#,
        r#"{"operations":[{"operation":"add","confidence":2}]}"#,
    ] {
        let (url, _) = mock(vec![(200, chat(content))]);
        let err = adapter(url, |_| {})
            .reconcile(&request())
            .await
            .unwrap_err();
        assert_eq!(err.failure, Failure::Validation, "{content}");
    }
}

#[tokio::test]
async fn reconciler_027_fr_011_cost_cap_blocks_before_any_call() {
    // Unreachable endpoint: the admission check must fire before any request.
    let a = adapter("http://127.0.0.1:1/".into(), |s| s.max_cost_usd = 0.0);
    let err = a.reconcile(&request()).await.unwrap_err();
    assert_eq!(
        err.failure,
        Failure::Terminal("RECONCILER_COST_LIMIT_EXCEEDED")
    );
    // Worst case scales with the retry budget.
    let p = a.payload(&request());
    let one = adapter("x".into(), |s| s.max_retries = 0).estimated_cost(&p);
    assert!((a.estimated_cost(&p) - one * 3.0).abs() < 1e-12);
}
