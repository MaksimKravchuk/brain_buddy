mod common;
use serde_json::{Value, json};
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
