mod common;
use serde_json::{Value, json};

#[test]
fn success_body_cannot_echo_active_credential_024_fr_007_024_fr_006() {
    let (output, _) = common::exchange(
        &[
            "task",
            "add",
            "--title",
            "Fixture",
            "--key",
            "credential-reflection-fixture",
        ],
        201,
        "",
        br#"{"id":"fixture","revision":1,"title":"synthetic-cli-token","state":"inbox"}"#,
    );
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    assert!(!String::from_utf8_lossy(&output.stderr).contains("synthetic-cli-token"));
    let error: Value = serde_json::from_slice(&output.stderr).unwrap();
    assert_eq!(error["error"]["mutation_confirmed"], true);
    assert_eq!(error["error"]["delivery_unknown"], false);
}

#[test]
fn task_create_preserves_key_and_cookie_024_fr_001_024_fr_005_024_sc_001() {
    let (output,request)=common::exchange(&["task","add","--title","Fixture","--key","fixture-create"],201,"",br#"{"id":"task-fixture","title":"Fixture","state":"inbox","revision":1,"details":"long fixture details","priority":"none","due_date":null,"project_id":null,"tag_ids":[]}"#);
    assert!(output.status.success(), "{:?}", output);
    assert!(
        request
            .headers
            .to_lowercase()
            .contains("idempotency-key: fixture-create")
    );
    assert!(
        request
            .headers
            .contains("brainbuddy_session=synthetic-cli-token")
    );
    assert_eq!(request.body["title"], "Fixture");
    let data: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(data["data"]["id"], "task-fixture");
    assert!(data["data"].get("details").is_none());
}

#[test]
fn error_metadata_is_safe_and_rate_limit_is_not_retried_024_fr_006_024_fr_008_024_sc_003() {
    let (output,request)=common::exchange(&["task","list"],429,"Retry-After: 9\r\nX-Correlation-ID: fixture-reference\r\n",br#"{"message":"synthetic-cli-token secret-sentinel","detail":{"code":"rate_limited","input":"secret-sentinel"}}"#);
    assert_eq!(output.status.code(), Some(7));
    assert!(request.headers.starts_with("GET /api/tasks?limit=20"));
    assert!(output.stdout.is_empty());
    let error: Value = serde_json::from_slice(&output.stderr).unwrap();
    assert_eq!(error["error"]["retry_after_seconds"], 9);
    assert_eq!(error["error"]["reference_id"], "fixture-reference");
    let text = String::from_utf8(output.stderr).unwrap();
    assert!(!text.contains("secret-sentinel"));
    assert!(!text.contains("synthetic-cli-token"));
}

#[test]
fn redirect_is_refused_without_following_024_fr_007() {
    let (output, _) = common::exchange(
        &["task", "get", "fixture-id"],
        302,
        "Location: https://untrusted.invalid/steal\r\n",
        b"{}",
    );
    assert_eq!(output.status.code(), Some(9));
    assert!(output.stdout.is_empty());
    assert!(
        !String::from_utf8(output.stderr)
            .unwrap()
            .contains("untrusted")
    );
}

#[test]
fn cursor_and_minimal_page_are_preserved_024_fr_003_024_sc_002() {
    let tasks=(0..20).map(|i|json!({"id":format!("task-{i}"),"title":"Fixture","state":"inbox","revision":1,"priority":"none","due_date":null,"project_id":null,"tag_ids":[],"details":"x".repeat(3000)})).collect::<Vec<_>>();
    let body=json!({"items":tasks,"has_more":true,"next_cursor":"opaque/+== cursor","counts_by_state":{"inbox":20}}).to_string();
    let (output, _) = common::exchange(&["task", "list"], 200, "", body.as_bytes());
    assert!(output.status.success(), "{:?}", output);
    assert!(output.stdout.len() * 100 <= body.len() * 40);
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["page"]["next_cursor"], "opaque/+== cursor");
    assert_eq!(value["page"]["has_more"], true);
    assert_eq!(value["data"].as_array().unwrap().len(), 20);
}

#[test]
fn confirmed_write_response_failure_is_distinguished_024_fr_006() {
    let (output, _) = common::exchange(
        &[
            "task",
            "add",
            "--title",
            "Fixture",
            "--key",
            "fixture-create",
        ],
        201,
        "",
        b"malformed-json",
    );
    assert_eq!(output.status.code(), Some(9));
    let error: Value = serde_json::from_slice(&output.stderr).unwrap();
    assert_eq!(error["error"]["mutation_confirmed"], true);
    assert_eq!(error["error"]["delivery_unknown"], false);
    assert_eq!(error["error"]["idempotency_key"], "fixture-create");
}

#[test]
fn unsafe_remote_origin_fails_locally_024_fr_007() {
    for server in [
        "http://example.invalid",
        "https://user:password@example.invalid",
        "https://example.invalid/path",
        "https://example.invalid?token=sentinel",
    ] {
        let output = std::process::Command::new(env!("CARGO_BIN_EXE_bb"))
            .args(["task", "list", "--server", server])
            .env("BB_SESSION_TOKEN", "fixture-token")
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2));
        assert!(
            !String::from_utf8(output.stderr)
                .unwrap()
                .contains("sentinel")
        );
    }
}
