use serde_json::Value;
use std::io::Write;
use std::process::{Command, Output, Stdio};

fn bb(args: &[&str], input: Option<&[u8]>) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_bb"));
    command
        .args(args)
        .env_remove("BB_SESSION_TOKEN")
        .env_remove("BB_SERVER");
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = command.spawn().unwrap();
    if let Some(bytes) = input {
        let _ = child.stdin.take().unwrap().write_all(bytes);
    } else {
        drop(child.stdin.take());
    }
    child.wait_with_output().unwrap()
}

#[test]
fn offline_discovery_024_fr_004_024_fr_008() {
    let result = bb(&["commands", "task", "update"], None);
    assert!(result.status.success(), "{:?}", result);
    let value: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(value["data"]["name"], "update");
    assert!(
        value["data"]["options"]
            .as_array()
            .unwrap()
            .iter()
            .any(|v| v["name"] == "revision")
    );
    assert!(result.stderr.is_empty());
}

#[test]
fn invalid_arguments_have_json_exit_024_fr_006_024_sc_003() {
    let result = bb(&["not-a-command"], None);
    assert_eq!(result.status.code(), Some(2));
    assert!(result.stdout.is_empty());
    let value: Value = serde_json::from_slice(&result.stderr).unwrap();
    assert_eq!(value["error"]["code"], "invalid_input");
}

#[test]
fn preview_stdin_redacts_content_and_uses_no_credentials_024_fr_004_024_fr_007() {
    let result = bb(
        &[
            "task",
            "add",
            "--json",
            "@-",
            "--key",
            "fixture-create",
            "--dry-run",
        ],
        Some(br#"{"title":"secret-sentinel","description":"private text"}"#),
    );
    assert!(result.status.success(), "{:?}", result);
    let text = String::from_utf8(result.stdout).unwrap();
    assert!(!text.contains("secret-sentinel"));
    assert!(!text.contains("private text"));
    let value: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["data"]["method"], "POST");
    assert_eq!(value["data"]["path"], "/tasks");
    assert_eq!(value["data"]["body_fields"]["title"], "string");
}

#[test]
fn missing_revision_is_local_failure_024_fr_005() {
    let result = bb(
        &[
            "task",
            "update",
            "fixture-id",
            "--title",
            "changed",
            "--key",
            "fixture-update",
            "--dry-run",
        ],
        None,
    );
    assert_eq!(result.status.code(), Some(2));
    assert_eq!(
        serde_json::from_slice::<Value>(&result.stderr).unwrap()["error"]["code"],
        "invalid_input"
    );
}

#[test]
fn generic_scope_and_mutation_selectors_fail_before_dispatch_024_fr_002() {
    for args in [
        vec!["api", "GET", "/auth/me", "--dry-run"],
        vec!["api", "DELETE", "/admin/users/id", "--dry-run"],
        vec![
            "api",
            "POST",
            "/tasks",
            "--fields",
            "title",
            "--json",
            "{}",
            "--dry-run",
        ],
        vec!["api", "GET", "/tasks/%2e%2e/admin", "--dry-run"],
    ] {
        let result = bb(&args, None);
        assert_eq!(result.status.code(), Some(2), "{:?}", result);
    }
}

#[test]
fn oversized_stdin_is_bounded_024_fr_008() {
    let input = vec![b' '; 1024 * 1024 + 1];
    let result = bb(
        &[
            "task",
            "add",
            "--key",
            "fixture-create",
            "--json",
            "@-",
            "--dry-run",
        ],
        Some(&input),
    );
    assert_eq!(result.status.code(), Some(2));
    assert!(!result.stderr.is_empty());
}

#[test]
fn unknown_selector_is_rejected_even_in_preview_024_fr_003_024_fr_004() {
    let result = bb(&["task", "list", "--fields", "unknown", "--dry-run"], None);
    assert_eq!(result.status.code(), Some(2));
}
