#![cfg(feature = "live")]
//! Black-box conformance for the platform rows (spec 027, T043): health, docs,
//! correlation IDs, request logging, privacy headers, CORS absence, error
//! envelopes, request validation, body caps, Idempotency-Key and the
//! release-epoch exempt set. The tests encode today's Python behavior and are
//! green against the frozen server first. Seeds only through the test control
//! API.

use bb_conformance::{Client, Config, LogCollector, Reply, TestControl, case};
use reqwest::Method;
use serde_json::{Value, json};
use std::future::Future;
use std::sync::atomic::{AtomicU64, Ordering};
use tokio::sync::Mutex;

/// The run report is one JSON file that every `case` rewrites, so the tests of
/// this binary run one at a time to keep the merge from losing entries.
static SERIAL: Mutex<()> = Mutex::const_new(());

async fn run<F: Future<Output = ()> + Send + 'static>(caps: &[&str], title: &str, body: F) {
    let _guard = SERIAL.lock().await;
    case(caps, title, body).await;
}

fn config() -> Config {
    Config::from_env().expect("BB_CONFORMANCE_BASE_URL is set")
}

fn anon() -> Client {
    Client::new(&config()).expect("client")
}

async fn get(client: &mut Client, path: &str) -> Reply {
    client
        .send(Method::GET, path, None)
        .await
        .expect("GET answered")
}

/// A synthetic signed-in owner; the cookie lives on the returned client.
///
/// Not `TestControl::new_owner`: that signs up as `@conformance.invalid`, a
/// special-use domain the Python server rejects with 422 as an email address.
async fn owner() -> Client {
    static N: AtomicU64 = AtomicU64::new(0);
    let cfg = config();
    let control = TestControl::new(&cfg).expect("test control");
    let invites = control.invites(1).await.expect("invite");
    let code = invites["codes"][0]
        .as_str()
        .expect("invite code")
        .to_string();
    let email = format!(
        "owner-{}-{}@example.com",
        std::process::id(),
        N.fetch_add(1, Ordering::Relaxed)
    );
    let mut client = Client::new(&cfg).expect("client");
    let body = json!({
        "email": email, "password": "Conformance-pass-1!", "invite_code": code
    });
    let reply = client
        .post("/api/auth/signup", &body)
        .await
        .expect("signup answered");
    assert_eq!(reply.status, 201, "synthetic signup");
    client
}

/// A raw body, for the byte-level caps that a JSON helper cannot express.
async fn raw_post(path: &str, content_type: &str, body: Vec<u8>) -> (u16, String) {
    let base = config().base_url.trim_end_matches('/').to_string();
    let reply = reqwest::Client::new()
        .post(format!("{base}{path}"))
        .header("Content-Type", content_type)
        .body(body)
        .send()
        .await
        .expect("POST answered");
    let status = reply.status().as_u16();
    (status, reply.text().await.expect("body"))
}

fn is_uuid_v4_text(value: &str) -> bool {
    value.len() == 36
        && value.chars().enumerate().all(|(i, c)| match i {
            8 | 13 | 18 | 23 => c == '-',
            _ => c.is_ascii_hexdigit(),
        })
}

// ---------------------------------------------------------------- CAP-HTTP

#[tokio::test]
async fn cap_http_001_health() {
    run(&["CAP-HTTP-001"], "cap_http_001_health", async {
        let reply = get(&mut anon(), "/health").await;
        assert_eq!(reply.status, 200);
        let body = reply.json().expect("json");
        assert_eq!(body["status"], "ok");
        assert!(body["environment"].is_string());
        assert!(body["schema_version"].is_string());
    })
    .await;
}

#[tokio::test]
async fn cap_http_002_api_health() {
    run(&["CAP-HTTP-002"], "cap_http_002_api_health", async {
        let health = get(&mut anon(), "/health").await.json().expect("json");
        let reply = get(&mut anon(), "/api/health").await;
        assert_eq!(reply.status, 200);
        assert_eq!(reply.json().expect("json"), health);
    })
    .await;
}

#[tokio::test]
async fn cap_http_003_openapi() {
    run(&["CAP-HTTP-003"], "cap_http_003_openapi", async {
        let health = get(&mut anon(), "/health").await.json().expect("json");
        let reply = get(&mut anon(), "/api/openapi.json").await;
        assert_eq!(reply.status, 200);
        let spec = reply.json().expect("json");
        assert_eq!(spec["info"]["version"], health["schema_version"]);
        assert!(spec["paths"]["/api/health"].is_object());
    })
    .await;
}

#[tokio::test]
async fn cap_http_004_docs() {
    run(&["CAP-HTTP-004"], "cap_http_004_docs", async {
        let reply = get(&mut anon(), "/api/docs").await;
        assert_eq!(reply.status, 200);
        assert!(
            reply
                .header("content-type")
                .unwrap_or("")
                .starts_with("text/html")
        );
        assert!(reply.body.contains("swagger-ui"));
    })
    .await;
}

/// Served at `/docs/oauth2-redirect` (FastAPI's default sits outside the docs
/// prefix), not at the `/api/docs/oauth2-redirect` the inventory row cites.
#[tokio::test]
async fn cap_http_005_oauth2_redirect() {
    run(&["CAP-HTTP-005"], "cap_http_005_oauth2_redirect", async {
        let reply = get(&mut anon(), "/docs/oauth2-redirect").await;
        assert_eq!(reply.status, 200);
        assert!(
            reply
                .header("content-type")
                .unwrap_or("")
                .starts_with("text/html")
        );
        assert!(reply.body.contains("OAuth2 Redirect"));
    })
    .await;
}

#[tokio::test]
async fn cap_http_006_redoc() {
    run(&["CAP-HTTP-006"], "cap_http_006_redoc", async {
        let reply = get(&mut anon(), "/api/redoc").await;
        assert_eq!(reply.status, 200);
        assert!(
            reply
                .header("content-type")
                .unwrap_or("")
                .starts_with("text/html")
        );
        assert!(reply.body.contains("redoc"));
    })
    .await;
}

// ------------------------------------------------------------ release epoch

/// The exempt set answers without `X-Client-Epoch` (contracts/release-epoch.md).
/// `/api/meta` is not on the old server, which is the "old server" signal the
/// contract defines; the Rust server answers it, so that check is Python-only.
#[tokio::test]
async fn release_epoch_exempt_set_needs_no_client_epoch() {
    run(
        &[
            "CAP-HTTP-001",
            "CAP-HTTP-002",
            "CAP-HTTP-003",
            "CAP-HTTP-004",
            "CAP-HTTP-006",
        ],
        "release_epoch_exempt_set_needs_no_client_epoch",
        async {
            let cfg = Config {
                epoch: None,
                ..config()
            };
            for path in [
                "/health",
                "/api/health",
                "/api/openapi.json",
                "/api/docs",
                "/api/redoc",
            ] {
                let mut client = Client::new(&cfg).expect("client");
                assert_eq!(get(&mut client, path).await.status, 200, "{path}");
            }
            if cfg.server == "python" {
                let mut client = Client::new(&cfg).expect("client");
                assert_eq!(get(&mut client, "/api/meta").await.status, 404);
            }
        },
    )
    .await;
}

// ---------------------------------------------------------------- CAP-MW

#[tokio::test]
async fn cap_mw_001_correlation_id() {
    run(&["CAP-MW-001"], "cap_mw_001_correlation_id", async {
        let mut echoed = anon().with_header("X-Correlation-ID", "conf-abc.123_X");
        let reply = get(&mut echoed, "/health").await;
        assert_eq!(reply.header("x-correlation-id"), Some("conf-abc.123_X"));

        let mut fallback = anon().with_header("X-Request-ID", "req-1");
        let reply = get(&mut fallback, "/health").await;
        assert_eq!(reply.header("x-correlation-id"), Some("req-1"));

        let long = "x".repeat(65);
        for bad in ["bad id!", long.as_str()] {
            let mut client = anon().with_header("X-Correlation-ID", bad);
            let reply = get(&mut client, "/health").await;
            let fresh = reply.header("x-correlation-id").expect("header set");
            assert_ne!(fresh, bad);
            assert!(is_uuid_v4_text(fresh), "fresh id is a uuid: {fresh}");
        }

        let mut missing = anon().with_header("X-Correlation-ID", "conf-404");
        let reply = get(&mut missing, "/api/no-such-route").await;
        assert_eq!(reply.status, 404);
        assert_eq!(reply.header("x-correlation-id"), Some("conf-404"));
        let body = reply.json().expect("json");
        assert_eq!(body["reference_id"], "conf-404");
    })
    .await;
}

#[tokio::test]
async fn cap_mw_002_x_client_is_not_echoed() {
    run(
        &["CAP-MW-002"],
        "cap_mw_002_x_client_is_not_echoed",
        async {
            for value in ["brainbuddy-ios/1.2.3", "something-else"] {
                let mut client = anon().with_header("X-Client", value);
                let reply = get(&mut client, "/health").await;
                assert_eq!(reply.status, 200);
                assert!(reply.header("x-client").is_none());
            }
        },
    )
    .await;
}

#[tokio::test]
async fn cap_mw_003_request_log_line_never_carries_seeded_text() {
    run(
        &["CAP-MW-003"],
        "cap_mw_003_request_log_line_never_carries_seeded_text",
        async {
            let mut log = LogCollector::default();
            let seed = log.seed();
            let reply = anon()
                .send(
                    Method::POST,
                    "/api/auth/login",
                    Some(&json!({ "email": "nobody@example.com", "password": seed })),
                )
                .await
                .expect("login answered");
            assert_eq!(reply.status, 401);
            log.check_env_file()
                .expect("seeded text must not reach the server log");
            if let Some(path) = std::env::var_os("BB_CONFORMANCE_SERVER_LOG") {
                let text = std::fs::read_to_string(path).expect("server log readable");
                assert!(
                    text.lines().any(|l| {
                        l.contains("api_request method=POST path=/api/auth/login status=401")
                    }),
                    "request log line for the login"
                );
            }
        },
    )
    .await;
}

#[tokio::test]
async fn cap_mw_004_access_log_redacts_push_token() {
    run(
        &["CAP-MW-004"],
        "cap_mw_004_access_log_redacts_push_token",
        async {
            let mut log = LogCollector::default();
            let token = log.seed();
            let (status, _) = raw_post(
                &format!("/api/a2a/push/run-conf/{token}"),
                "application/json",
                b"{}".to_vec(),
            )
            .await;
            assert_ne!(status, 500);
            log.check_env_file()
                .expect("push token must not reach the access log");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_mw_005_privacy_headers_on_auth_paths() {
    run(
        &["CAP-MW-005"],
        "cap_mw_005_privacy_headers_on_auth_paths",
        async {
            let reply = get(&mut anon(), "/api/auth/me").await;
            assert_eq!(reply.status, 401);
            assert_eq!(reply.header("cache-control"), Some("no-store"));
            assert_eq!(reply.header("referrer-policy"), Some("no-referrer"));

            let reply = get(&mut anon(), "/api/account").await;
            assert_eq!(reply.header("cache-control"), Some("no-store"));
            assert_eq!(reply.header("referrer-policy"), Some("no-referrer"));

            let reply = get(&mut anon(), "/api/trees").await;
            assert_ne!(reply.header("cache-control"), Some("no-store"));
        },
    )
    .await;
}

#[tokio::test]
async fn cap_mw_006_no_cors_or_security_headers() {
    run(
        &["CAP-MW-006"],
        "cap_mw_006_no_cors_or_security_headers",
        async {
            let mut preflight = anon().with_header("Origin", "https://evil.example");
            let reply = preflight
                .send(Method::OPTIONS, "/api/health", None)
                .await
                .expect("OPTIONS answered");
            assert!(reply.header("access-control-allow-origin").is_none());

            let mut cross = anon().with_header("Origin", "https://evil.example");
            let reply = get(&mut cross, "/health").await;
            assert!(reply.header("access-control-allow-origin").is_none());
            for name in [
                "strict-transport-security",
                "content-security-policy",
                "x-frame-options",
            ] {
                assert!(reply.header(name).is_none(), "{name} absent");
            }
        },
    )
    .await;
}

#[tokio::test]
async fn cap_mw_007_error_envelope() {
    run(&["CAP-MW-007"], "cap_mw_007_error_envelope", async {
        let mut anonymous = anon().with_header("X-Correlation-ID", "conf-401");
        let reply = get(&mut anonymous, "/api/auth/me").await;
        assert_eq!(reply.status, 401);
        let body = reply.json().expect("json");
        assert_eq!(body["message"], "Authentication required.");
        assert!(body.get("detail").is_some());
        assert_eq!(body["reference_id"], "conf-401");

        let mut client = owner().await;
        let reply = get(
            &mut client,
            "/api/trees/00000000-0000-4000-8000-000000000000",
        )
        .await;
        assert_eq!(reply.status, 404);
        let body = reply.json().expect("json");
        assert!(body["message"].is_string());
        assert!(body.get("detail").is_some());
        assert!(body["reference_id"].is_string());

        let reply = client
            .send(
                Method::POST,
                "/api/review/decisions/00000000-0000-4000-8000-000000000000/undo",
                Some(&json!({ "expected_task_revision": 1 })),
            )
            .await
            .expect("answered");
        assert_eq!(reply.status, 400);
        let body = reply.json().expect("json");
        assert_eq!(body["message"], "Idempotency-Key header is required.");
        assert!(body["detail"].is_null());
    })
    .await;
}

#[tokio::test]
async fn cap_mw_008_request_validation() {
    run(&["CAP-MW-008"], "cap_mw_008_request_validation", async {
        let reply = anon()
            .send(Method::POST, "/api/auth/login", Some(&json!({})))
            .await
            .expect("answered");
        assert_eq!(reply.status, 422);
        let body = reply.json().expect("json");
        assert_eq!(body["message"], "Request validation failed.");
        let detail = body["detail"].as_array().expect("detail list");
        assert!(!detail.is_empty());
        assert!(detail.iter().all(|e| e.get("input").is_none()));

        let seed = LogCollector::default().seed();
        let reply = anon()
            .send(
                Method::POST,
                "/api/auth/login",
                Some(&json!({ "email": seed, "password": seed })),
            )
            .await
            .expect("answered");
        assert_eq!(reply.status, 422);
        assert!(!reply.body.contains(&seed), "rejected input is not echoed");
    })
    .await;
}

#[tokio::test]
async fn cap_mw_015_body_caps() {
    run(&["CAP-MW-015"], "cap_mw_015_body_caps", async {
        let (status, text) = raw_post(
            "/api/a2a/push/run-conf/tok-conf",
            "application/json",
            vec![b' '; 64_001],
        )
        .await;
        assert_eq!(status, 413);
        let body: Value = serde_json::from_str(&text).expect("json");
        assert_eq!(body["message"], "Notification payload is too large.");

        let (status, _) = raw_post(
            "/api/a2a/push/run-conf/tok-conf",
            "application/json",
            vec![b' '; 64_000],
        )
        .await;
        assert_ne!(status, 413, "a body at the cap is not refused for size");
    })
    .await;
}

#[tokio::test]
async fn cap_mw_016_idempotency_key() {
    run(&["CAP-MW-016"], "cap_mw_016_idempotency_key", async {
        let mut client = owner().await;
        let undo = "/api/review/decisions/00000000-0000-4000-8000-000000000000/undo";
        let reply = client
            .send(
                Method::POST,
                undo,
                Some(&json!({ "expected_task_revision": 1 })),
            )
            .await
            .expect("answered");
        assert_eq!(reply.status, 400);
        assert_eq!(
            reply.json().expect("json")["message"],
            "Idempotency-Key header is required."
        );

        let mut keyed = owner().await.with_header("Idempotency-Key", "conf-key-1");
        let reply = keyed
            .send(
                Method::POST,
                undo,
                Some(&json!({ "expected_task_revision": 1 })),
            )
            .await
            .expect("answered");
        assert_ne!(
            reply
                .json()
                .ok()
                .and_then(|v| v["message"].as_str().map(str::to_string))
                .as_deref(),
            Some("Idempotency-Key header is required.")
        );
    })
    .await;
}
