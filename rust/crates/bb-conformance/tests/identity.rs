#![cfg(feature = "live")]
//! Black-box identity conformance (027 PR-43, T044): password signup, login,
//! logout and me, the session cookie, the login limiter and session validity.
//!
//! Evidence ids come from `contracts/capability-dispositions.json`: CAP-HTTP-040..043,
//! CAP-MW-012, CAP-MW-014 (login limiter) and CAP-MW-019. Seeds go only through the
//! test control API. Green against the frozen Python server first.
//!
//! The login limiter is process-wide per client IP, so every test that logs in runs
//! inside `login_suite`, in order, and the limiter burst runs last. Start the server
//! fresh (or wait out the 10-minute window) before a run.

use bb_conformance::{Client, Config, Reply, TestControl, case};
use reqwest::Method;
use serde_json::json;
use std::sync::atomic::{AtomicU64, Ordering};

const PASSWORD: &str = "Conformance-pass-1!";
const NEW_PASSWORD: &str = "Conformance-pass-2!";
const COOKIE_PREFIX: &str = "brainbuddy_session=";
const KNOWN_FLAGS: [&str; 8] = [
    "delivery_canary",
    "voice_brain_dump",
    "external_agent_relay",
    "task_title_autocomplete",
    "crt_canvas",
    "task_mcp",
    "weekly_review",
    "rust_core_sync",
];

static N: AtomicU64 = AtomicU64::new(0);

fn env() -> Config {
    Config::from_env().expect("conformance config")
}

fn unique_email() -> String {
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    // `.invalid` is a reserved name that the Python EmailStr validator rejects.
    format!(
        "ident-{t:x}-{}@example.com",
        N.fetch_add(1, Ordering::Relaxed)
    )
}

async fn invite(control: &TestControl) -> String {
    let v = control.invites(1).await.expect("invite");
    v["codes"][0].as_str().expect("invite code").to_string()
}

/// The full `Set-Cookie` line for the session cookie, if the reply carries one.
fn session_header(reply: &Reply) -> Option<String> {
    reply
        .headers
        .get_all("set-cookie")
        .iter()
        .filter_map(|v| v.to_str().ok())
        .find(|v| v.starts_with(COOKIE_PREFIX))
        .map(str::to_string)
}

/// The `name=value` pair of a session `Set-Cookie` line.
fn session_pair(line: &str) -> String {
    line.split(';').next().unwrap_or_default().to_string()
}

/// A signed-in synthetic owner: the cookie pair and a client that holds it.
struct Session {
    email: String,
    cookie: String,
    client: Client,
}

async fn new_session(cfg: &Config, control: &TestControl) -> Session {
    let email = unique_email();
    let code = invite(control).await;
    let mut client = Client::new(cfg).expect("client");
    let reply = client
        .post(
            "/api/auth/signup",
            &json!({ "email": email, "password": PASSWORD, "invite_code": code }),
        )
        .await
        .expect("signup");
    assert_eq!(reply.status, 201, "signup status");
    let line = session_header(&reply).expect("signup sets the session cookie");
    Session {
        email,
        cookie: session_pair(&line),
        client,
    }
}

async fn login(cfg: &Config, email: &str, password: &str) -> Reply {
    let mut client = Client::new(cfg).expect("client");
    client
        .post(
            "/api/auth/login",
            &json!({ "email": email, "password": password }),
        )
        .await
        .expect("login")
}

/// A client that sends only the given cookie pair, as a browser holding it would.
fn with_cookie(cfg: &Config, cookie: &str) -> Client {
    Client::new(cfg)
        .expect("client")
        .with_header("Cookie", cookie)
}

// --- CAP-HTTP-040: signup -------------------------------------------------

#[tokio::test]
async fn cap_http_040_signup_creates_session_and_rejects_bad_invite_and_duplicate() {
    case(&["CAP-HTTP-040"], "cap_http_040_signup", async move {
        let cfg = env();
        let control = TestControl::new(&cfg).expect("control");
        let s = new_session(&cfg, &control).await;

        let mut client = Client::new(&cfg).expect("client");
        let ok = client
            .post(
                "/api/auth/signup",
                &json!({
                    "email": unique_email(),
                    "password": PASSWORD,
                    "invite_code": invite(&control).await,
                }),
            )
            .await
            .expect("signup");
        assert_eq!(ok.status, 201, "fresh signup");
        assert!(
            session_header(&ok).is_some(),
            "fresh signup sets the cookie"
        );

        let bad = Client::new(&cfg)
            .expect("client")
            .post(
                "/api/auth/signup",
                &json!({
                    "email": unique_email(),
                    "password": PASSWORD,
                    "invite_code": "not-a-real-invite",
                }),
            )
            .await
            .expect("bad invite");
        assert_eq!(bad.status, 400, "bad invite");

        let dup = Client::new(&cfg)
            .expect("client")
            .post(
                "/api/auth/signup",
                &json!({
                    "email": s.email,
                    "password": PASSWORD,
                    "invite_code": invite(&control).await,
                }),
            )
            .await
            .expect("duplicate");
        assert_eq!(dup.status, 409, "duplicate email");
    })
    .await;
}

// --- CAP-MW-012: session cookie attributes ------------------------------

#[tokio::test]
async fn cap_mw_012_session_cookie_attributes() {
    case(&["CAP-MW-012"], "cap_mw_012_session_cookie", async move {
        let cfg = env();
        let control = TestControl::new(&cfg).expect("control");
        let email = unique_email();
        let code = invite(&control).await;
        let reply = Client::new(&cfg)
            .expect("client")
            .post(
                "/api/auth/signup",
                &json!({ "email": email, "password": PASSWORD, "invite_code": code }),
            )
            .await
            .expect("signup");
        assert_eq!(reply.status, 201, "signup status");
        let line = session_header(&reply).expect("signup sets the session cookie");
        let attrs: Vec<String> = line
            .split(';')
            .map(|a| a.trim().to_ascii_lowercase())
            .collect();
        assert!(line.starts_with(COOKIE_PREFIX), "cookie name");
        assert!(!session_pair(&line).contains(&email), "token is opaque");
        assert!(attrs.iter().any(|a| a == "httponly"), "HttpOnly");
        assert!(attrs.iter().any(|a| a == "samesite=lax"), "SameSite=Lax");
        assert!(attrs.iter().any(|a| a == "path=/"), "Path=/");
        assert!(
            attrs.iter().any(|a| a == "max-age=2592000"),
            "30-day Max-Age"
        );
        assert!(
            !attrs.iter().any(|a| a == "secure"),
            "Secure is only set in production"
        );
    })
    .await;
}

// --- CAP-HTTP-042: logout --------------------------------------------------

#[tokio::test]
async fn cap_http_042_logout_clears_cookie_and_kills_the_session() {
    case(&["CAP-HTTP-042"], "cap_http_042_logout", async move {
        let cfg = env();
        let control = TestControl::new(&cfg).expect("control");
        let mut s = new_session(&cfg, &control).await;

        let out = s
            .client
            .send(Method::POST, "/api/auth/logout", None)
            .await
            .expect("logout");
        assert_eq!(out.status, 204, "logout status");
        let cleared = session_header(&out).expect("logout clears the cookie");
        assert!(
            cleared.to_ascii_lowercase().contains("max-age=0"),
            "cookie cleared"
        );

        let me = with_cookie(&cfg, &s.cookie)
            .send(Method::GET, "/api/auth/me", None)
            .await
            .expect("me after logout");
        assert_eq!(me.status, 401, "old session row is gone");

        let anon = Client::new(&cfg)
            .expect("client")
            .send(Method::POST, "/api/auth/logout", None)
            .await
            .expect("logout without cookie");
        assert_eq!(anon.status, 204, "cookie is optional");
    })
    .await;
}

// --- CAP-HTTP-043: me ------------------------------------------------------

#[tokio::test]
async fn cap_http_043_me_returns_only_the_caller_with_effective_flags() {
    case(&["CAP-HTTP-043"], "cap_http_043_me", async move {
        let cfg = env();
        let control = TestControl::new(&cfg).expect("control");
        let mut a = new_session(&cfg, &control).await;
        let mut b = new_session(&cfg, &control).await;

        let anon = Client::new(&cfg)
            .expect("client")
            .send(Method::GET, "/api/auth/me", None)
            .await
            .expect("anonymous me");
        assert_eq!(anon.status, 401, "me needs a session");

        let (a_email, b_email) = (a.email.clone(), b.email.clone());
        for (own, other) in [(&mut a, &b_email), (&mut b, &a_email)] {
            let reply = own
                .client
                .send(Method::GET, "/api/auth/me", None)
                .await
                .expect("me");
            assert_eq!(reply.status, 200, "me status");
            let body = reply.json().expect("me json");
            assert_eq!(body["email"], own.email.as_str(), "self only");
            assert_ne!(body["email"], other.as_str(), "foreign owner hidden");
            assert_eq!(body["deletion_cancelled"], false);
            let flags = body["feature_flags"].as_object().expect("feature_flags");
            let mut keys: Vec<&str> = flags.keys().map(String::as_str).collect();
            keys.sort_unstable();
            let mut want = KNOWN_FLAGS.to_vec();
            want.sort_unstable();
            assert_eq!(keys, want, "feature_flags covers every known flag");
        }
    })
    .await;
}

// --- CAP-MW-019: session validity (independent of the login limiter) ------

#[tokio::test]
async fn cap_mw_019_pending_deletion_rejects_and_drops_the_session() {
    case(&["CAP-MW-019"], "cap_mw_019_pending_deletion", async move {
        let cfg = env();
        let control = TestControl::new(&cfg).expect("control");
        let mut s = new_session(&cfg, &control).await;

        let del = s
            .client
            .post(
                "/api/account/delete",
                &json!({ "current_password": PASSWORD }),
            )
            .await
            .expect("request deletion");
        assert_eq!(del.status, 202, "deletion accepted");

        let me = with_cookie(&cfg, &s.cookie)
            .send(Method::GET, "/api/auth/me", None)
            .await
            .expect("me after deletion request");
        assert_eq!(me.status, 401, "pending deletion rejects the session");
    })
    .await;
}

// --- Login: CAP-HTTP-041, CAP-MW-019 (auth_version), CAP-MW-014 -------------

/// Every test that logs in runs here, in order: the limiter is process-wide.
#[tokio::test]
async fn login_suite_runs_in_order_because_the_limiter_is_process_wide() {
    case(&["CAP-HTTP-041"], "cap_http_041_login", async move {
        let cfg = env();
        let control = TestControl::new(&cfg).expect("control");
        let s = new_session(&cfg, &control).await;

        let ok = login(&cfg, &s.email, PASSWORD).await;
        assert_eq!(ok.status, 200, "login status");
        assert!(session_header(&ok).is_some(), "login sets the cookie");
        assert_eq!(ok.json().expect("login json")["deletion_cancelled"], false);

        let mut doomed = new_session(&cfg, &control).await;
        let del = doomed
            .client
            .post(
                "/api/account/delete",
                &json!({ "current_password": PASSWORD }),
            )
            .await
            .expect("request deletion");
        assert_eq!(del.status, 202, "deletion accepted");
        let back = login(&cfg, &doomed.email, PASSWORD).await;
        assert_eq!(back.status, 200, "login during grace");
        assert_eq!(
            back.json().expect("login json")["deletion_cancelled"],
            true,
            "login during the grace period cancels deletion"
        );
    })
    .await;

    case(&["CAP-MW-019"], "cap_mw_019_auth_version", async move {
        let cfg = env();
        let control = TestControl::new(&cfg).expect("control");
        let mut first = new_session(&cfg, &control).await;
        let second = login(&cfg, &first.email, PASSWORD).await;
        assert_eq!(second.status, 200, "second session");
        let second_cookie = session_pair(&session_header(&second).expect("cookie"));

        let changed = first
            .client
            .post(
                "/api/account/password",
                &json!({ "current_password": PASSWORD, "new_password": NEW_PASSWORD }),
            )
            .await
            .expect("change password");
        assert_eq!(changed.status, 204, "password changed");

        let stale = with_cookie(&cfg, &second_cookie)
            .send(Method::GET, "/api/auth/me", None)
            .await
            .expect("stale me");
        assert_eq!(
            stale.status, 401,
            "auth_version bump rejects other sessions"
        );

        let kept = first
            .client
            .send(Method::GET, "/api/auth/me", None)
            .await
            .expect("kept me");
        assert_eq!(kept.status, 200, "the changing session survives");
    })
    .await;

    case(&["CAP-MW-014"], "cap_mw_014_login_limiter", async move {
        let cfg = env();
        let control = TestControl::new(&cfg).expect("control");
        let s = new_session(&cfg, &control).await;

        for attempt in 1..=10 {
            let r = login(&cfg, &s.email, "wrong-password-1!").await;
            assert_eq!(r.status, 401, "failure {attempt} is answered normally");
        }
        let limited = login(&cfg, &s.email, PASSWORD).await;
        assert_eq!(
            limited.status, 429,
            "the 11th attempt is limited even with the right password"
        );
    })
    .await;
}
