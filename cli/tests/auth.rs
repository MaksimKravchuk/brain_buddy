mod common;
use serde_json::{Value, json};
#[cfg(unix)]
use std::process::Command;

fn config_dir() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    dir
}

fn start() -> Value {
    json!({"device_code":"private-device-proof-sentinel-0123456789ABC","user_code":"ABCD-EFGH","verification_uri":"FIXTURE_ORIGIN/cli/authorize","verification_uri_complete":"FIXTURE_ORIGIN/cli/authorize#user_code=ABCD-EFGH","expires_in":600,"interval":5,"protocol_version":1})
}
fn issued() -> Value {
    json!({"account":{"id":"account-1","email":"fixture@example.test","feature_flags":{"cli_auth":true}},"credential_type":"session_cookie","cookie_name":"brainbuddy_session","expires_at":"2030-01-01T00:00:00Z"})
}
fn cookie() -> String {
    "Set-Cookie: brainbuddy_session=new-session-secret-sentinel; HttpOnly; SameSite=Lax; Path=/; Expires=Tue, 01 Jan 2030 00:00:00 GMT\r\n".into()
}

#[cfg(unix)]
fn assert_uncertain_exchange_preserves_connection(fault: common::ReplyFault, cancel: bool) {
    use std::sync::{Arc, Mutex};
    let dir = config_dir();
    let path = dir.path().to_owned();
    let before = Arc::new(Mutex::new(None));
    let snapshot = before.clone();
    let (results, captured) = common::sessions_with_reply_fault(
        &[
            &["auth", "login", "--no-browser", "--store", "file"],
            &[
                "auth",
                "login",
                "--no-browser",
                "--store",
                "file",
                "--replace",
            ],
        ],
        dir.path(),
        vec![
            (200, String::new(), start()),
            (200, cookie(), issued()),
            (200, String::new(), start()),
            (200, cookie(), issued()),
            (
                409,
                String::new(),
                json!({"detail":{"code":"authorization_consumed"}}),
            ),
        ],
        Some((3, fault)),
        move |index, pid| {
            if index == 2 {
                let mut files = std::fs::read_dir(&path)
                    .unwrap()
                    .map(|entry| {
                        let entry = entry.unwrap();
                        (entry.file_name(), std::fs::read(entry.path()).unwrap())
                    })
                    .collect::<Vec<_>>();
                files.sort();
                *snapshot.lock().unwrap() = Some(files);
            }
            if index == 3 && cancel {
                assert!(pid > 0);
                assert_eq!(unsafe { libc::kill(pid as i32, libc::SIGINT) }, 0);
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
        },
    );
    assert!(results[0].status.success());
    assert_eq!(
        captured.len(),
        4,
        "An uncertain token exchange must not be polled again"
    );
    assert!(
        captured[3]
            .headers
            .starts_with("POST /api/auth/device/token ")
    );
    assert!(results[1].stdout.is_empty());
    let output = String::from_utf8_lossy(&results[1].stderr);
    assert!(!output.contains("private-device-proof-sentinel"));
    assert!(!output.contains("new-session-secret-sentinel"));
    assert!(!output.contains("authorization_consumed"));
    let error: Value = serde_json::from_str(output.lines().last().unwrap()).unwrap();
    assert_eq!(error["error"]["detail"]["new_session_may_exist"], true);
    assert_eq!(error["error"]["detail"]["cleanup_uncertain"], true);
    match fault {
        common::ReplyFault::DropBeforeHeaders => {
            assert_eq!(results[1].status.code(), Some(8));
            assert_eq!(error["error"]["code"], "transport_error");
            assert_eq!(error["error"]["delivery_unknown"], true);
        }
        common::ReplyFault::TruncatedSuccess => {
            assert_eq!(results[1].status.code(), Some(9));
            assert_eq!(error["error"]["mutation_confirmed"], true);
            assert_eq!(error["error"]["delivery_unknown"], false);
        }
    }
    let mut after = std::fs::read_dir(dir.path())
        .unwrap()
        .map(|entry| {
            let entry = entry.unwrap();
            (entry.file_name(), std::fs::read(entry.path()).unwrap())
        })
        .collect::<Vec<_>>();
    after.sort();
    assert_eq!(
        Some(after),
        *before.lock().unwrap(),
        "Previous connection and credential must stay byte-identical"
    );
}

#[cfg(unix)]
#[test]
fn lost_token_reply_stops_polling_024_fr_007_024_fr_013() {
    assert_uncertain_exchange_preserves_connection(common::ReplyFault::DropBeforeHeaders, false);
}

#[cfg(unix)]
#[test]
fn cancellation_cannot_hide_lost_token_reply_024_fr_007_024_fr_013() {
    assert_uncertain_exchange_preserves_connection(common::ReplyFault::DropBeforeHeaders, true);
}

#[cfg(unix)]
#[test]
fn cancellation_cannot_hide_confirmed_token_reply_024_fr_007_024_fr_013() {
    assert_uncertain_exchange_preserves_connection(common::ReplyFault::TruncatedSuccess, true);
}

#[cfg(unix)]
#[test]
fn cancellation_during_poll_reports_130_024_fr_013() {
    let dir = config_dir();
    let (results, captured) = common::sessions_with_hook_and_pid(
        &[&["auth", "login", "--no-browser", "--store", "file"]],
        dir.path(),
        vec![
            (200, String::new(), start()),
            (
                403,
                String::new(),
                json!({"message":"Denied","detail":{"code":"authorization_denied"}}),
            ),
        ],
        |index, pid| {
            if index == 1 {
                assert!(pid > 0);
                // Signal only the child fixture process, while its HTTP poll is in flight.
                assert_eq!(unsafe { libc::kill(pid as i32, libc::SIGINT) }, 0);
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
        },
    );
    assert_eq!(results[0].status.code(), Some(130));
    assert_eq!(captured.len(), 2);
    assert!(String::from_utf8_lossy(&results[0].stderr).contains("cancelled"));
    assert!(!dir.path().join("config.json").exists());
}

#[cfg(unix)]
#[test]
fn expiry_stops_before_another_poll_024_fr_013() {
    let dir = config_dir();
    let mut grant = start();
    grant["expires_in"] = json!(1);
    let (result, captured) = common::sequence(
        &["auth", "login", "--no-browser", "--store", "file"],
        dir.path(),
        vec![(200, String::new(), grant)],
    );
    assert_eq!(result.status.code(), Some(11));
    assert_eq!(captured.len(), 1);
    assert!(!dir.path().join("config.json").exists());
}

#[cfg(unix)]
#[test]
fn malformed_issued_cookie_reports_cleanup_uncertainty_024_fr_007_024_fr_013() {
    let dir = config_dir();
    let invalid = cookie().replace("HttpOnly; ", "");
    let (result, captured) = common::sequence(
        &["auth", "login", "--no-browser", "--store", "file"],
        dir.path(),
        vec![(200, String::new(), start()), (200, invalid, issued())],
    );
    assert!(!result.status.success());
    assert_eq!(captured.len(), 2);
    let output = String::from_utf8_lossy(&result.stderr);
    assert!(!output.contains("new-session-secret-sentinel"));
    let error: Value = serde_json::from_str(output.lines().last().unwrap()).unwrap();
    assert_eq!(error["error"]["detail"]["cleanup_uncertain"], true);
    assert_eq!(error["error"]["detail"]["new_session_may_exist"], true);
    assert_eq!(error["error"]["mutation_confirmed"], true);
    assert_eq!(error["error"]["delivery_unknown"], false);
    assert!(!dir.path().join("config.json").exists());
}

#[cfg(unix)]
#[test]
fn headless_login_persists_without_disclosing_proofs_024_fr_007_024_fr_013_024_sc_006() {
    use std::os::unix::fs::PermissionsExt;
    let dir = config_dir();
    let (result, captured) = common::sequence(
        &["auth", "login", "--no-browser", "--store", "file"],
        dir.path(),
        vec![(200, String::new(), start()), (200, cookie(), issued())],
    );
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert_eq!(captured.len(), 2);
    assert!(
        captured[0]
            .headers
            .starts_with("POST /api/auth/device/start ")
    );
    assert!(!captured[0].headers.to_lowercase().contains("cookie:"));
    assert_eq!(captured[1].body["device_code"], start()["device_code"]);
    for bytes in [&result.stdout, &result.stderr] {
        let output = String::from_utf8_lossy(bytes);
        assert!(!output.contains("private-device-proof-sentinel"));
        assert!(!output.contains("new-session-secret-sentinel"));
    }
    let config: Value =
        serde_json::from_slice(&std::fs::read(dir.path().join("config.json")).unwrap()).unwrap();
    assert!(!config.to_string().contains("new-session-secret-sentinel"));
    let connection = config["connections"]
        .as_object()
        .unwrap()
        .values()
        .next()
        .unwrap();
    let secret = dir.path().join(format!(
        "{}.credential",
        connection["locator"].as_str().unwrap()
    ));
    assert_eq!(
        std::fs::metadata(secret).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

#[cfg(unix)]
#[test]
fn reflected_device_proof_is_rejected_and_candidate_revoked_024_fr_007_024_fr_013() {
    for field in ["id", "email", "display_name"] {
        let dir = config_dir();
        let mut response = issued();
        response["account"][field] = start()["device_code"].clone();
        let (result, captured) = common::sequence(
            &["auth", "login", "--no-browser", "--store", "file"],
            dir.path(),
            vec![
                (200, String::new(), start()),
                (200, cookie(), response),
                (204, String::new(), Value::Null),
            ],
        );
        assert!(!result.status.success(), "Reflected {field} accepted");
        for output in [&result.stdout, &result.stderr] {
            assert!(!String::from_utf8_lossy(output).contains("private-device-proof-sentinel"));
            assert!(!String::from_utf8_lossy(output).contains("new-session-secret-sentinel"));
        }
        assert!(!dir.path().join("config.json").exists());
        assert_eq!(captured.len(), 3);
        let output = String::from_utf8_lossy(&result.stderr);
        let error: Value = serde_json::from_str(output.lines().last().unwrap()).unwrap();
        assert_eq!(error["error"]["mutation_confirmed"], true);
        assert_eq!(error["error"]["delivery_unknown"], false);
        assert!(captured[2].headers.starts_with("POST /api/auth/logout "));
    }
}

#[cfg(unix)]
#[test]
fn failed_logout_removal_retains_locator_for_retry_024_fr_007_024_fr_014() {
    use std::os::unix::fs::PermissionsExt;
    let dir = config_dir();
    let path = dir.path().to_owned();
    let (results, _) = common::sessions_with_hook(
        &[
            &["auth", "login", "--no-browser", "--store", "file"],
            &["auth", "logout"],
        ],
        dir.path(),
        vec![
            (200, String::new(), start()),
            (200, cookie(), issued()),
            (204, String::new(), Value::Null),
        ],
        move |index| {
            if index == 2 {
                let config: Value =
                    serde_json::from_slice(&std::fs::read(path.join("config.json")).unwrap())
                        .unwrap();
                let connection = config["connections"]
                    .as_object()
                    .unwrap()
                    .values()
                    .next()
                    .unwrap();
                let file = path.join(format!(
                    "{}.credential",
                    connection["locator"].as_str().unwrap()
                ));
                std::fs::set_permissions(file, std::fs::Permissions::from_mode(0o400)).unwrap();
            }
        },
    );
    assert!(results[0].status.success());
    assert_eq!(results[1].status.code(), Some(10));
    let config: Value =
        serde_json::from_slice(&std::fs::read(dir.path().join("config.json")).unwrap()).unwrap();
    let connections = config["connections"].as_object().unwrap();
    assert_eq!(
        connections.len(),
        1,
        "Failed deletion must retain its locator"
    );
    let connection = connections.values().next().unwrap();
    let file = dir.path().join(format!(
        "{}.credential",
        connection["locator"].as_str().unwrap()
    ));
    assert!(file.exists());
    std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
    // The fixture server is now closed: retry must still clear local state and
    // honestly report that remote revocation could not be confirmed this time.
    let result = Command::new(common::binary())
        .args(["auth", "logout"])
        .env("BB_CONFIG_DIR", dir.path())
        .env_remove("BB_SESSION_TOKEN")
        .env_remove("BB_SERVER")
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("\"local_cleared\":true"));
    assert!(!file.exists());
    let config: Value =
        serde_json::from_slice(&std::fs::read(dir.path().join("config.json")).unwrap()).unwrap();
    assert!(config["connections"].as_object().unwrap().is_empty());
}

#[cfg(unix)]
#[test]
fn logout_recovers_metadata_after_credential_is_already_gone_024_fr_007_024_fr_014() {
    let dir = config_dir();
    let (result, _) = common::sequence(
        &["auth", "login", "--no-browser", "--store", "file"],
        dir.path(),
        vec![(200, String::new(), start()), (200, cookie(), issued())],
    );
    assert!(result.status.success());
    let config: Value =
        serde_json::from_slice(&std::fs::read(dir.path().join("config.json")).unwrap()).unwrap();
    let connection = config["connections"]
        .as_object()
        .unwrap()
        .values()
        .next()
        .unwrap();
    std::fs::remove_file(dir.path().join(format!(
        "{}.credential",
        connection["locator"].as_str().unwrap()
    )))
    .unwrap();
    let result = Command::new(common::binary())
        .args(["auth", "logout"])
        .env("BB_CONFIG_DIR", dir.path())
        .env_remove("BB_SESSION_TOKEN")
        .env_remove("BB_SERVER")
        .output()
        .unwrap();
    assert!(!result.status.success());
    let error: Value = serde_json::from_slice(&result.stderr).unwrap();
    assert_eq!(error["error"]["detail"]["local_cleared"], true);
    assert_eq!(error["error"]["detail"]["server_revoked"], false);
    let config: Value =
        serde_json::from_slice(&std::fs::read(dir.path().join("config.json")).unwrap()).unwrap();
    assert!(config["connections"].as_object().unwrap().is_empty());
}

#[cfg(unix)]
#[test]
fn denied_login_preserves_existing_connection_024_fr_013_024_fr_014() {
    let dir = config_dir();
    let (result, _) = common::sequence(
        &["auth", "login", "--no-browser", "--store", "file"],
        dir.path(),
        vec![
            (200, String::new(), start()),
            (
                403,
                String::new(),
                json!({"detail":{"code":"authorization_denied","input":"secret-sentinel"}}),
            ),
        ],
    );
    assert_eq!(result.status.code(), Some(11));
    assert!(!dir.path().join("config.json").exists());
    assert!(!String::from_utf8_lossy(&result.stderr).contains("secret-sentinel"));
}

#[test]
fn external_status_uses_same_session_without_leaking_it_024_fr_014() {
    let (result, captured) = common::exchange(
        &["auth", "status"],
        200,
        "",
        br#"{"id":"account-1","email":"fixture@example.test"}"#,
    );
    assert!(result.status.success());
    assert!(captured.headers.starts_with("GET /api/auth/me "));
    let value: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(value["data"]["source"], "environment");
    assert!(!String::from_utf8_lossy(&result.stdout).contains("synthetic-cli-token"));
}

#[cfg(unix)]
#[test]
fn file_credentials_refuse_symlinks_024_fr_007() {
    let dir = config_dir();
    let other = tempfile::tempdir().unwrap();
    std::os::unix::fs::symlink(other.path(), dir.path().join("unsafe")).unwrap();
    let result = Command::new(common::binary())
        .args([
            "auth",
            "login",
            "--no-browser",
            "--store",
            "file",
            "--server",
            "http://127.0.0.1:1",
        ])
        .env("BB_CONFIG_DIR", dir.path().join("unsafe"))
        .env_remove("BB_SESSION_TOKEN")
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(10));
    assert!(std::fs::read_dir(other.path()).unwrap().next().is_none());
}

#[cfg(unix)]
#[test]
fn stored_session_survives_processes_and_logout_revokes_only_it_024_fr_007_024_fr_014() {
    let dir = config_dir();
    let actions: &[&[&str]] = &[
        &["auth", "login", "--no-browser", "--store", "file"],
        &["task", "list"],
        &["auth", "logout"],
    ];
    let (results, captured) = common::sessions(
        actions,
        dir.path(),
        vec![
            (200, String::new(), start()),
            (200, cookie(), issued()),
            (
                200,
                String::new(),
                json!({"items":[],"has_more":false,"next_cursor":null}),
            ),
            (204, String::new(), Value::Null),
        ],
    );
    for result in &results {
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
    }
    assert!(
        captured[2]
            .headers
            .contains("brainbuddy_session=new-session-secret-sentinel")
    );
    assert!(captured[3].headers.starts_with("POST /api/auth/logout "));
    let value: Value = serde_json::from_slice(&results[2].stdout).unwrap();
    assert_eq!(value["data"]["local_cleared"], true);
    assert_eq!(value["data"]["server_revoked"], true);
    assert!(!std::fs::read_dir(dir.path()).unwrap().any(|p| {
        p.unwrap()
            .path()
            .extension()
            .is_some_and(|e| e == "credential")
    }));
}

#[cfg(unix)]
#[test]
fn denied_reconnect_preserves_usable_saved_session_024_fr_013_024_fr_014() {
    let dir = config_dir();
    let actions: &[&[&str]] = &[
        &["auth", "login", "--no-browser", "--store", "file"],
        &["auth", "login", "--no-browser", "--store", "file"],
        &["auth", "status"],
    ];
    let (results, captured) = common::sessions(
        actions,
        dir.path(),
        vec![
            (200, String::new(), start()),
            (200, cookie(), issued()),
            (200, String::new(), start()),
            (
                403,
                String::new(),
                json!({"detail":{"code":"authorization_denied"}}),
            ),
            (200, String::new(), json!({"id":"account-1"})),
        ],
    );
    assert!(results[0].status.success());
    assert_eq!(results[1].status.code(), Some(11));
    assert!(results[2].status.success());
    assert!(
        captured[4]
            .headers
            .contains("brainbuddy_session=new-session-secret-sentinel")
    );
}

#[cfg(unix)]
#[test]
fn foreign_account_without_replace_revokes_only_candidate_024_fr_013_024_fr_014() {
    let dir = config_dir();
    let mut foreign = issued();
    foreign["account"]["id"] = json!("account-2");
    let actions: &[&[&str]] = &[
        &["auth", "login", "--no-browser", "--store", "file"],
        &["auth", "login", "--no-browser", "--store", "file"],
        &["auth", "status"],
    ];
    let (results, captured) = common::sessions(
        actions,
        dir.path(),
        vec![
            (200, String::new(), start()),
            (200, cookie(), issued()),
            (200, String::new(), start()),
            (
                200,
                cookie().replace(
                    "new-session-secret-sentinel",
                    "foreign-session-secret-sentinel",
                ),
                foreign,
            ),
            (204, String::new(), Value::Null),
            (200, String::new(), json!({"id":"account-1"})),
        ],
    );
    assert!(results[0].status.success());
    assert_eq!(results[1].status.code(), Some(6));
    assert!(results[2].status.success());
    assert!(
        captured[4]
            .headers
            .contains("brainbuddy_session=foreign-session-secret-sentinel")
    );
    assert!(captured[4].headers.starts_with("POST /api/auth/logout "));
    assert!(
        captured[5]
            .headers
            .contains("brainbuddy_session=new-session-secret-sentinel")
    );
}

#[cfg(unix)]
#[test]
fn post_issuance_store_failure_revokes_candidate_and_preserves_connection_024_fr_007_024_fr_013_024_fr_014()
 {
    use std::os::unix::fs::PermissionsExt;
    let dir = config_dir();
    let path = dir.path().to_owned();
    let actions: &[&[&str]] = &[
        &["auth", "login", "--no-browser", "--store", "file"],
        &["auth", "login", "--no-browser", "--store", "file"],
        &["auth", "status"],
    ];
    let (results, captured) = common::sessions_with_hook(
        actions,
        dir.path(),
        vec![
            (200, String::new(), start()),
            (200, cookie(), issued()),
            (200, String::new(), start()),
            (
                200,
                cookie().replace(
                    "new-session-secret-sentinel",
                    "candidate-session-secret-sentinel",
                ),
                issued(),
            ),
            (204, String::new(), Value::Null),
            (200, String::new(), json!({"id":"account-1"})),
        ],
        move |index| {
            if index == 3 {
                std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o500)).unwrap();
            }
            if index == 4 {
                std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
            }
        },
    );
    assert!(results[0].status.success());
    assert_eq!(results[1].status.code(), Some(10));
    assert!(results[2].status.success());
    assert!(
        captured[4]
            .headers
            .contains("brainbuddy_session=candidate-session-secret-sentinel")
    );
    assert!(
        captured[5]
            .headers
            .contains("brainbuddy_session=new-session-secret-sentinel")
    );
    assert!(
        String::from_utf8_lossy(&results[1].stderr).contains("\"new_session_server_revoked\":true")
    );
}

#[test]
#[ignore = "Requires an isolated unlocked native store; required native CI runs this explicitly"]
fn native_session_survives_processes_024_fr_007_024_sc_006() {
    let dir = config_dir();
    let actions: &[&[&str]] = &[
        &["auth", "login", "--no-browser"],
        &["auth", "status"],
        &["auth", "logout"],
    ];
    let (results, captured) = common::sessions(
        actions,
        dir.path(),
        vec![
            (200, String::new(), start()),
            (200, cookie(), issued()),
            (
                200,
                String::new(),
                json!({"id":"account-1","email":"fixture@example.test"}),
            ),
            (204, String::new(), Value::Null),
        ],
    );
    for result in &results {
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
    }
    assert!(
        captured[2]
            .headers
            .contains("brainbuddy_session=new-session-secret-sentinel")
    );
}

#[cfg(target_os = "linux")]
#[test]
#[ignore = "Requires isolated Secret Service; run after native persistence, locking the collection"]
fn locked_native_store_is_refused_without_unlock_or_network_024_fr_007_024_fr_008() {
    use sha2::{Digest, Sha256};
    use std::os::unix::fs::PermissionsExt;
    let dir = config_dir();
    let origin = "http://127.0.0.1:1";
    let namespace = format!("{:x}", Sha256::digest(format!("{origin}\n/api").as_bytes()));
    let locator = "0123456789abcdef0123456789abcdef0123456789abcdef";
    let entry = keyring::Entry::new("BrainBuddy CLI", &format!("{namespace}:{locator}")).unwrap();
    entry.set_password("locked-fixture-secret").unwrap();
    let config = json!({"default":namespace,"connections":{namespace:{"server":origin,"api_prefix":"/api","account_id":"account-1","store":"native","locator":locator,"cookie_name":"brainbuddy_session","expires_at":"2030-01-01T00:00:00Z"}}});
    let path = dir.path().join("config.json");
    std::fs::write(&path, config.to_string()).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let service = dbus_secret_service::SecretService::connect_with_max_prompt_timeout(
        dbus_secret_service::EncryptionType::Dh,
        0,
    )
    .unwrap();
    let collection = service.get_default_collection().unwrap();
    collection.lock().unwrap();
    let result = Command::new(common::binary())
        .args(["task", "list"])
        .env("BB_CONFIG_DIR", dir.path())
        .env_remove("BB_SESSION_TOKEN")
        .env_remove("BB_SERVER")
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(10));
    assert!(collection.is_locked().unwrap());
    assert!(!String::from_utf8_lossy(&result.stderr).contains("locked-fixture-secret"));
}
