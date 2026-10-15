#![cfg(feature = "live")]
//! Black-box conformance for the modern auth surface (spec 027, PR-45):
//! CAP-HTTP-010..024, CAP-MW-010 and CAP-MW-013.
//!
//! Every test is named `cap_<kind>_<nnn>_*` after the inventory row it
//! evidences and records its outcome under that CAP id in the run report.
//! Seeding goes only through the test control API: invites, SMTP capture
//! (`/mail`) and the scripted identity provider (`/providers/identity`).
//!
//! The server under test must have every modern method configured (Google,
//! Apple web and native, email) and the auth delivery worker running. The
//! Python server runs its delivery worker in the test environment only with
//! `BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST=1`. The native Apple audience
//! defaults to `com.example.conformance.ios`; override it with
//! `BB_CONFORMANCE_APPLE_NATIVE_AUDIENCE`.
//!
//! Tests named `cap_*_rust_*` encode the Rust-only `change` rows of
//! contracts/invite-handoff.md and run only when `BB_CONFORMANCE_SERVER=rust`
//! (the frozen Python server creates accounts without an invite).
//!
//! Synthetic addresses use `conformance-bb.dev`: the Python validators refuse
//! reserved names such as `.invalid`. Mail sends are budgeted per address
//! (5/h, one per 60 s) and per network (50/h), so a test sends rarely and
//! waits out the resend window with a real sleep rather than the shared clock.

use bb_conformance::{Client, Config, Reply, TestControl, case};
use reqwest::Method;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;

type R<T> = bb_conformance::Result<T>;

const SESSION: &str = "brainbuddy_session";
const BINDER: &str = "brainbuddy_auth_binder";
const PASSWORD: &str = "Conformance-pass-1!";
const ENVELOPE_MESSAGE: &str = "Authentication could not be completed.";
const FORM: &str = "application/x-www-form-urlencoded";

/// The scripted identity provider is one queue per server: tests that arm it
/// run their script-and-call section one at a time.
static IDENTITY: Mutex<()> = Mutex::const_new(());

// ---------------------------------------------------------------- crypto ---

fn sha256(data: &[u8]) -> [u8; 32] {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for (i, word) in chunk.chunks(4).enumerate() {
            w[i] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add((e & f) ^ (!e & g))
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let t2 = s0.wrapping_add((a & b) ^ (a & c) ^ (b & c));
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (slot, v) in h.iter_mut().zip([a, b, c, d, e, f, g, hh]) {
            *slot = slot.wrapping_add(v);
        }
    }
    let mut out = [0u8; 32];
    for (i, word) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}

fn b64url(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for chunk in bytes.chunks(3) {
        let n = chunk
            .iter()
            .enumerate()
            .fold(0u32, |acc, (i, b)| acc | (u32::from(*b) << (16 - 8 * i)));
        for i in 0..=chunk.len() {
            out.push(char::from(ALPHABET[((n >> (18 - 6 * i)) & 63) as usize]));
        }
    }
    out
}

/// A 43-character URL-safe random-looking token: valid as a challenge id, a
/// state, a client verifier or a recent proof shape.
fn token() -> String {
    static N: AtomicU64 = AtomicU64::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    let salt = RandomState::new().build_hasher().finish();
    let seed = format!(
        "{nanos}-{}-{salt}-{}",
        N.fetch_add(1, Ordering::Relaxed),
        std::process::id()
    );
    b64url(&sha256(seed.as_bytes()))
}

fn challenge(verifier: &str) -> String {
    b64url(&sha256(verifier.as_bytes()))
}

fn slug() -> String {
    token()
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .map(|c| c.to_ascii_lowercase())
        .take(16)
        .collect()
}

// ------------------------------------------------------------ transport ---

struct World {
    cfg: Config,
    ctl: TestControl,
}

impl World {
    fn new() -> R<Self> {
        let cfg = Config::from_env()?;
        let ctl = TestControl::new(&cfg)?;
        Ok(Self { cfg, ctl })
    }

    fn browser(&self) -> R<Browser> {
        Browser::new(&self.cfg)
    }
}

/// One cookie jar over the base-URL client: the session and the provider
/// binder cookie travel together, as in a browser.
struct Browser {
    base: String,
    epoch: Option<u32>,
    client: Client,
    http: reqwest::Client,
    jar: BTreeMap<String, String>,
}

impl Browser {
    fn new(cfg: &Config) -> R<Self> {
        Ok(Self {
            base: cfg.base_url.trim_end_matches('/').to_string(),
            epoch: cfg.epoch,
            client: Client::new(cfg)?,
            http: reqwest::Client::builder()
                .redirect(reqwest::redirect::Policy::none())
                .build()?,
            jar: BTreeMap::new(),
        })
    }

    fn cookie_header(&self) -> Option<String> {
        let pairs: Vec<String> = self.jar.iter().map(|(k, v)| format!("{k}={v}")).collect();
        (!pairs.is_empty()).then(|| pairs.join("; "))
    }

    fn absorb(&mut self, reply: &Reply) {
        for line in set_cookies(reply) {
            let pair = line.split(';').next().unwrap_or("");
            let Some((name, value)) = pair.split_once('=') else {
                continue;
            };
            let gone = value.is_empty()
                || value == "\"\""
                || line.to_ascii_lowercase().contains("max-age=0");
            if gone {
                self.jar.remove(name);
            } else {
                self.jar.insert(name.to_string(), value.to_string());
            }
        }
    }

    async fn send(&mut self, method: Method, path: &str, body: Option<&Value>) -> R<Reply> {
        let mut client = self.client.fresh();
        if let Some(cookie) = self.cookie_header() {
            client = client.with_header("Cookie", &cookie);
        }
        let reply = client.send(method, path, body).await?;
        self.absorb(&reply);
        Ok(reply)
    }

    async fn get(&mut self, path: &str) -> R<Reply> {
        self.send(Method::GET, path, None).await
    }

    async fn post(&mut self, path: &str, body: &Value) -> R<Reply> {
        self.send(Method::POST, path, Some(body)).await
    }

    /// A request with an explicit content type and byte body (form posts and
    /// deliberately malformed JSON requests).
    async fn raw(&mut self, path: &str, headers: &[(&str, &str)], body: Vec<u8>) -> R<Reply> {
        let mut req = self.http.post(format!("{}{path}", self.base)).body(body);
        if let Some(epoch) = self.epoch {
            req = req.header("X-Client-Epoch", epoch.to_string());
        }
        if let Some(cookie) = self.cookie_header() {
            req = req.header("Cookie", cookie);
        }
        for (name, value) in headers {
            req = req.header(*name, *value);
        }
        let resp = req.send().await?;
        let (status, headers) = (resp.status().as_u16(), resp.headers().clone());
        let reply = Reply {
            status,
            headers,
            body: resp.text().await?,
        };
        self.absorb(&reply);
        Ok(reply)
    }

    async fn form(&mut self, path: &str, body: &str) -> R<Reply> {
        self.raw(path, &[("Content-Type", FORM)], body.as_bytes().to_vec())
            .await
    }
}

fn set_cookies(reply: &Reply) -> Vec<String> {
    reply
        .headers
        .get_all("set-cookie")
        .iter()
        .filter_map(|v| v.to_str().ok().map(str::to_string))
        .collect()
}

fn cookie_line(reply: &Reply, name: &str) -> Option<String> {
    let prefix = format!("{name}=");
    set_cookies(reply)
        .into_iter()
        .find(|l| l.starts_with(&prefix))
}

fn detail_code(reply: &Reply) -> String {
    reply
        .json()
        .ok()
        .and_then(|j| j["detail"]["code"].as_str().map(str::to_string))
        .unwrap_or_default()
}

/// The coarse modern-auth envelope: status, `detail.code`, the fixed message
/// and a reference id that equals the correlation header.
fn expect_envelope(reply: &Reply, status: u16, code: &str) {
    assert_eq!(reply.status, status, "{}", reply.body);
    assert_eq!(detail_code(reply), code, "{}", reply.body);
    let body = reply.json().expect("json body");
    assert_eq!(body["message"], ENVELOPE_MESSAGE, "{}", reply.body);
    assert_eq!(
        body["reference_id"].as_str(),
        reply.header("x-correlation-id"),
        "reference_id must echo X-Correlation-ID"
    );
}

fn field<'a>(value: &'a Value, key: &str) -> R<&'a str> {
    Ok(value[key]
        .as_str()
        .ok_or_else(|| format!("missing string field {key} in {value}"))?)
}

fn is_token(value: &str) -> bool {
    value.len() == 43
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

// -------------------------------------------------------------- fixtures ---

struct Account {
    b: Browser,
    email: String,
    id: String,
    password: String,
}

/// A password owner created through an invite from the test control API.
async fn account(w: &World) -> R<Account> {
    let invites = w.ctl.invites(1).await?;
    let code = invites["codes"][0]
        .as_str()
        .ok_or("no invite code")?
        .to_string();
    let email = format!("c{}@conformance-bb.dev", slug());
    let mut b = w.browser()?;
    let body = json!({"email": email, "password": PASSWORD, "invite_code": code});
    let reply = b.post("/api/auth/signup", &body).await?;
    assert!(reply.status < 300, "signup answered {}", reply.body);
    let methods = b.get("/api/account/auth-methods").await?;
    assert_eq!(methods.status, 200, "{}", methods.body);
    let id = field(&methods.json()?, "account_id")?.to_string();
    Ok(Account {
        b,
        email,
        id,
        password: PASSWORD.into(),
    })
}

/// A recent-proof secret for `action`, from the owner's current password.
async fn proof(a: &mut Account, action: &str) -> R<String> {
    let body = json!({
        "current_password": a.password, "action": action, "expected_account_id": a.id
    });
    let reply = a.b.post("/api/auth/confirm/password", &body).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    Ok(field(&reply.json()?, "recent_proof")?.to_string())
}

async fn arm_smtp(w: &World) -> R<()> {
    w.ctl.script_provider("smtp", json!([]), false).await?;
    Ok(())
}

/// The code of the newest message to `to`, once more than `seen` have arrived.
async fn mail_code(w: &World, to: &str, seen: usize) -> R<String> {
    for _ in 0..120 {
        let mail = w.ctl.mail().await?;
        let mine: Vec<&Value> = mail["messages"]
            .as_array()
            .map(|all| all.iter().filter(|m| m["recipient"] == to).collect())
            .unwrap_or_default();
        if mine.len() > seen {
            return Ok(field(mine[mine.len() - 1], "code")?.to_string());
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    Err(format!("no mail arrived for {to}").into())
}

async fn email_request(b: &mut Browser, body: &Value) -> R<Reply> {
    b.post("/api/auth/email/request", body).await
}

fn login_request(email: &str, purpose: &str, verifier: &str) -> Value {
    json!({
        "email": email, "purpose": purpose,
        "client_challenge": challenge(verifier), "client": "web"
    })
}

/// An owner whose address is verified through the protected `verify_email`
/// action (the only server-neutral way to a code-login-capable account).
/// One mail has been sent to the address when this returns.
async fn verified_account(w: &World) -> R<Account> {
    arm_smtp(w).await?;
    let mut a = account(w).await?;
    let secret = proof(&mut a, "verify_email").await?;
    let verifier = token();
    let mut body = login_request(&a.email, "verify_email", &verifier);
    body["expected_account_id"] = json!(a.id);
    body["action"] = json!("verify_email");
    body["recent_proof"] = json!(secret);
    let reply = email_request(&mut a.b, &body).await?;
    assert_eq!(reply.status, 202, "{}", reply.body);
    let challenge_id = field(&reply.json()?, "challenge_id")?.to_string();
    let code = mail_code(w, &a.email, 0).await?;
    let verify = json!({
        "challenge_id": challenge_id, "client_verifier": verifier, "code": code
    });
    let reply = a.b.post("/api/auth/email/verify", &verify).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    assert_eq!(reply.json()?["status"], "verified_email");
    Ok(a)
}

async fn wait_out_resend_window() {
    tokio::time::sleep(Duration::from_secs(62)).await;
}

async fn password_login(w: &World, email: &str, password: &str) -> R<(Browser, Reply)> {
    let mut b = w.browser()?;
    let reply = b
        .post(
            "/api/auth/login",
            &json!({"email": email, "password": password}),
        )
        .await?;
    Ok((b, reply))
}

struct Started {
    attempt_id: String,
    state: String,
    url: Option<String>,
    verifier: String,
    reply: Reply,
}

async fn start(
    b: &mut Browser,
    provider: &str,
    client: &str,
    purpose: &str,
    extra: Value,
) -> R<Started> {
    let verifier = token();
    let mut body = json!({
        "purpose": purpose, "client": client, "client_challenge": challenge(&verifier)
    });
    if let Some(extra) = extra.as_object() {
        for (key, value) in extra {
            body[key] = value.clone();
        }
    }
    let path = format!("/api/auth/providers/{provider}/start");
    let reply = b.post(&path, &body).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    Ok(Started {
        attempt_id: field(&j, "attempt_id")?.to_string(),
        state: field(&j, "state")?.to_string(),
        url: j["authorization_url"].as_str().map(str::to_string),
        verifier,
        reply,
    })
}

fn query_param(url: &str, name: &str) -> Option<String> {
    let query = url.split_once('?')?.1;
    query
        .split('&')
        .find_map(|pair| pair.strip_prefix(&format!("{name}=")).map(str::to_string))
}

fn identity_script(audience: &str, subject: &str, email: &str) -> Value {
    json!([{ "identity": {
        "subject": subject, "email": email,
        "email_authoritative": true, "audience": audience
    }}])
}

/// Starts a web provider attempt, arms the identity script for the audience
/// the server put in the authorization URL, and drives the callback.
async fn provider_round(
    w: &World,
    b: &mut Browser,
    provider: &str,
    purpose: &str,
    extra: Value,
    identity: (&str, &str),
) -> R<(Started, Reply)> {
    let _guard = IDENTITY.lock().await;
    let started = start(b, provider, "web", purpose, extra).await?;
    let url = started
        .url
        .clone()
        .ok_or("web start has no authorization_url")?;
    let audience = query_param(&url, "client_id").ok_or("no client_id in url")?;
    let script = identity_script(&audience, identity.0, identity.1);
    w.ctl.script_provider("identity", script, false).await?;
    let callback = if provider == "google" {
        let path = format!(
            "/api/auth/providers/google/callback?code=synthetic-code&state={}",
            started.state
        );
        b.get(&path).await?
    } else {
        let body = format!("code=synthetic-code&state={}", started.state);
        b.form("/api/auth/providers/apple/callback", &body).await?
    };
    Ok((started, callback))
}

fn fragment(reply: &Reply) -> BTreeMap<String, String> {
    reply
        .header("location")
        .and_then(|l| l.split_once('#'))
        .map(|(_, f)| {
            f.split('&')
                .filter_map(|p| p.split_once('='))
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

async fn complete(b: &mut Browser, started: &Started, callback: &Reply) -> R<Reply> {
    assert_eq!(callback.status, 303, "{}", callback.body);
    let grant = fragment(callback)
        .get("grant")
        .cloned()
        .ok_or("callback redirect carries no grant")?;
    let body = json!({
        "attempt_id": started.attempt_id, "state": started.state,
        "handoff_code": grant, "client_verifier": started.verifier
    });
    b.post("/api/auth/providers/complete", &body).await
}

fn identity_for(email: &str) -> (String, String) {
    (format!("sub-{}", slug()), email.to_string())
}

/// Links a Google identity to the owner (protected `link:google` action).
async fn link_google(w: &World, a: &mut Account, subject: &str, email: &str) -> R<()> {
    let secret = proof(a, "link:google").await?;
    let extra = json!({
        "expected_account_id": a.id, "action": "link:google", "recent_proof": secret
    });
    let (started, callback) =
        provider_round(w, &mut a.b, "google", "link", extra, (subject, email)).await?;
    let reply = complete(&mut a.b, &started, &callback).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    assert_eq!(reply.json()?["status"], "linked");
    Ok(())
}

async fn account_origin(b: &mut Browser) -> R<String> {
    let reply = b.get("/api/auth/methods?client=web").await?;
    Ok(field(&reply.json()?, "web_account_origin")?.to_string())
}

fn skip_unless_rust() -> bool {
    let rust = std::env::var("BB_CONFORMANCE_SERVER").is_ok_and(|s| s == "rust");
    if !rust {
        eprintln!("skipped: Rust-only change row (BB_CONFORMANCE_SERVER != rust)");
    }
    !rust
}

macro_rules! cap_test {
    ($name:ident, [$($cap:literal),+], $title:literal, $body:path) => {
        #[tokio::test]
        async fn $name() {
            case(&[$($cap),+], $title, async {
                let w = World::new().expect("conformance environment");
                $body(&w).await.expect("conformance step failed");
            })
            .await;
        }
    };
}

macro_rules! rust_only_test {
    ($name:ident, [$($cap:literal),+], $title:literal, $body:path) => {
        #[tokio::test]
        async fn $name() {
            if skip_unless_rust() {
                return;
            }
            case(&[$($cap),+], $title, async {
                let w = World::new().expect("conformance environment");
                $body(&w).await.expect("conformance step failed");
            })
            .await;
        }
    };
}

// ------------------------------------------------------ CAP-HTTP-010 ---

async fn methods_report_availability(w: &World) -> R<()> {
    let mut b = w.browser()?;
    for path in [
        "/api/auth/methods?client=web",
        "/api/auth/methods?client=ios",
        "/api/auth/methods",
    ] {
        let reply = b.get(path).await?;
        assert_eq!(reply.status, 200, "{path}: {}", reply.body);
        let j = reply.json()?;
        assert_eq!(j["password"], true);
        for method in ["google", "apple", "email"] {
            assert_eq!(j[method], true, "{path}: {method} must be configured");
        }
        assert!(field(&j, "web_account_origin")?.starts_with("https://"));
    }
    let reply = b.get("/api/auth/methods?client=android").await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_010_methods_report_availability,
    ["CAP-HTTP-010"],
    "CAP-HTTP-010 methods reports configured methods per client and rejects unknown clients",
    methods_report_availability
);

// ------------------------------------------------------ CAP-HTTP-011 ---

async fn request_queues_code_mail(w: &World) -> R<()> {
    arm_smtp(w).await?;
    let mut b = w.browser()?;
    let email = format!("c{}@conformance-bb.dev", slug());
    let verifier = token();
    let reply = email_request(&mut b, &login_request(&email, "login", &verifier)).await?;
    assert_eq!(reply.status, 202, "{}", reply.body);
    let j = reply.json()?;
    assert!(is_token(field(&j, "challenge_id")?));
    assert!(field(&j, "expires_at")?.contains('T'));
    assert!(field(&j, "resend_at")?.contains('T'));
    assert_eq!(
        j["message"],
        "If this address can be used, you will receive a code."
    );
    let code = mail_code(w, &email, 0).await?;
    assert!(code.len() == 6 && code.chars().all(|c| c.is_ascii_digit()));
    Ok(())
}

cap_test!(
    cap_http_011_request_answers_202_and_mails_a_code,
    ["CAP-HTTP-011"],
    "CAP-HTTP-011 email request answers 202 with a challenge and queues a six digit code",
    request_queues_code_mail
);

async fn request_does_not_enumerate(w: &World) -> R<()> {
    let existing = account(w).await?;
    let mut b = w.browser()?;
    let known = email_request(&mut b, &login_request(&existing.email, "login", &token())).await?;
    let unknown_email = format!("c{}@conformance-bb.dev", slug());
    let unknown = email_request(&mut b, &login_request(&unknown_email, "login", &token())).await?;
    assert_eq!((known.status, unknown.status), (202, 202));
    let (known, unknown) = (known.json()?, unknown.json()?);
    let keys = |v: &Value| -> Vec<String> {
        v.as_object()
            .map(|m| m.keys().cloned().collect())
            .unwrap_or_default()
    };
    assert_eq!(keys(&known), keys(&unknown));
    assert_eq!(known["message"], unknown["message"]);
    Ok(())
}

cap_test!(
    cap_http_011_request_answers_alike_for_known_and_unknown_addresses,
    ["CAP-HTTP-011"],
    "CAP-HTTP-011 email request does not reveal whether an address has an account",
    request_does_not_enumerate
);

async fn request_rejects_unprovable_input(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let email = format!("c{}@conformance-bb.dev", slug());
    let mut protected = login_request(&email, "verify_email", &token());
    protected["expected_account_id"] = json!("someone");
    protected["action"] = json!("verify_email");
    protected["recent_proof"] = json!(token());
    let reply = email_request(&mut b, &protected).await?;
    expect_envelope(&reply, 401, "invalid_proof");
    let mailbox = login_request(&email, "provider_mailbox", &token());
    let reply = email_request(&mut b, &mailbox).await?;
    expect_envelope(&reply, 400, "invalid_proof");
    let mut bad = login_request(&email, "login", &token());
    bad["email"] = json!("not-an-email");
    let reply = email_request(&mut b, &bad).await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_011_request_rejects_protected_purpose_without_session,
    ["CAP-HTTP-011"],
    "CAP-HTTP-011 email request refuses protected purposes without a session and bad input",
    request_rejects_unprovable_input
);

// ------------------------------------------------------ CAP-HTTP-012 ---

async fn resend_is_throttled_then_delivers(w: &World) -> R<()> {
    arm_smtp(w).await?;
    let mut b = w.browser()?;
    let email = format!("c{}@conformance-bb.dev", slug());
    let verifier = token();
    let reply = email_request(&mut b, &login_request(&email, "login", &verifier)).await?;
    assert_eq!(reply.status, 202, "{}", reply.body);
    let challenge_id = field(&reply.json()?, "challenge_id")?.to_string();
    mail_code(w, &email, 0).await?;

    let wrong = json!({"challenge_id": challenge_id, "client_verifier": token()});
    let reply = b.post("/api/auth/email/resend", &wrong).await?;
    expect_envelope(&reply, 404, "owner_mismatch");
    let unknown = json!({"challenge_id": token(), "client_verifier": verifier});
    let reply = b.post("/api/auth/email/resend", &unknown).await?;
    expect_envelope(&reply, 404, "owner_mismatch");

    let body = json!({"challenge_id": challenge_id, "client_verifier": verifier});
    let reply = b.post("/api/auth/email/resend", &body).await?;
    expect_envelope(&reply, 429, "rate_limited");

    wait_out_resend_window().await;
    let reply = b.post("/api/auth/email/resend", &body).await?;
    assert_eq!(reply.status, 202, "{}", reply.body);
    assert_eq!(field(&reply.json()?, "challenge_id")?, challenge_id);
    mail_code(w, &email, 1).await?;
    Ok(())
}

cap_test!(
    cap_http_012_resend_is_throttled_then_mails_a_new_code,
    ["CAP-HTTP-012"],
    "CAP-HTTP-012 email resend answers 429 inside the window, 202 after it, 404 for foreign challenges",
    resend_is_throttled_then_delivers
);

// ------------------------------------------------------ CAP-HTTP-013 ---

async fn verify_action_confirms_address(w: &World) -> R<()> {
    let mut a = verified_account(w).await?;
    let methods = a.b.get("/api/account/auth-methods").await?;
    assert_eq!(methods.json()?["email_verified"], true);
    Ok(())
}

cap_test!(
    cap_http_013_verify_email_action_confirms_the_address,
    ["CAP-HTTP-013"],
    "CAP-HTTP-013 email verify completes the verify_email action for the signed-in owner",
    verify_action_confirms_address
);

async fn login_code_signs_in(w: &World) -> R<()> {
    let a = verified_account(w).await?;
    wait_out_resend_window().await;
    let mut b = w.browser()?;
    let verifier = token();
    let reply = email_request(&mut b, &login_request(&a.email, "login", &verifier)).await?;
    assert_eq!(reply.status, 202, "{}", reply.body);
    let challenge_id = field(&reply.json()?, "challenge_id")?.to_string();
    let code = mail_code(w, &a.email, 1).await?;
    let verify = json!({
        "challenge_id": challenge_id, "client_verifier": verifier, "code": code
    });
    let reply = b.post("/api/auth/email/verify", &verify).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    assert_eq!(j["status"], "signed_in");
    assert_eq!(j["user"]["id"], a.id.as_str());
    assert_eq!(j["user"]["email"], a.email.as_str());
    let cookie = cookie_line(&reply, SESSION).ok_or("no session cookie")?;
    assert!(cookie.to_ascii_lowercase().contains("httponly"));
    let methods = b.get("/api/account/auth-methods").await?;
    assert_eq!(methods.status, 200, "{}", methods.body);
    assert_eq!(methods.json()?["account_id"], a.id.as_str());
    let replay = b.post("/api/auth/email/verify", &verify).await?;
    expect_envelope(&replay, 400, "invalid_proof");
    Ok(())
}

cap_test!(
    cap_http_013_login_code_signs_in_a_verified_owner,
    ["CAP-HTTP-013"],
    "CAP-HTTP-013 email verify signs in a verified owner, sets the session cookie, single use",
    login_code_signs_in
);

async fn verify_rejects_bad_code_and_challenge(w: &World) -> R<()> {
    arm_smtp(w).await?;
    let mut b = w.browser()?;
    let email = format!("c{}@conformance-bb.dev", slug());
    let verifier = token();
    let reply = email_request(&mut b, &login_request(&email, "login", &verifier)).await?;
    let challenge_id = field(&reply.json()?, "challenge_id")?.to_string();
    let code = mail_code(w, &email, 0).await?;
    let wrong = if code == "000000" { "111111" } else { "000000" };
    let body = json!({"challenge_id": challenge_id, "client_verifier": verifier, "code": wrong});
    let reply = b.post("/api/auth/email/verify", &body).await?;
    expect_envelope(&reply, 400, "invalid_proof");
    assert!(cookie_line(&reply, SESSION).is_none());
    let unknown = json!({"challenge_id": token(), "client_verifier": verifier, "code": "123456"});
    let reply = b.post("/api/auth/email/verify", &unknown).await?;
    expect_envelope(&reply, 404, "owner_mismatch");
    let shape = json!({"challenge_id": challenge_id, "client_verifier": verifier, "code": "12"});
    let reply = b.post("/api/auth/email/verify", &shape).await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_013_verify_rejects_wrong_code_and_unknown_challenge,
    ["CAP-HTTP-013"],
    "CAP-HTTP-013 email verify refuses a wrong code, an unknown challenge and a malformed code",
    verify_rejects_bad_code_and_challenge
);

async fn invite_required_for_new_email(w: &World) -> R<()> {
    arm_smtp(w).await?;
    let mut b = w.browser()?;
    let email = format!("c{}@conformance-bb.dev", slug());
    let verifier = token();
    let reply = email_request(&mut b, &login_request(&email, "login", &verifier)).await?;
    let challenge_id = field(&reply.json()?, "challenge_id")?.to_string();
    let code = mail_code(w, &email, 0).await?;
    let verify = json!({
        "challenge_id": challenge_id, "client_verifier": verifier, "code": code
    });
    let reply = b.post("/api/auth/email/verify", &verify).await?;
    expect_invite_required(&reply);
    Ok(())
}

/// The contracts/invite-handoff.md completion response for a new identity.
fn expect_invite_required(reply: &Reply) -> String {
    assert_eq!(reply.status, 403, "{}", reply.body);
    assert!(
        cookie_line(reply, SESSION).is_none(),
        "no session may exist"
    );
    let j = reply.json().expect("json body");
    assert_eq!(
        j["message"],
        "An invite code is required to create an account."
    );
    assert_eq!(j["detail"]["code"], "INVITE_REQUIRED");
    assert_eq!(j["detail"]["expires_in"], 600);
    let pending = j["detail"]["pending"].as_str().expect("pending token");
    assert!(!pending.is_empty());
    pending.to_string()
}

rust_only_test!(
    cap_http_013_rust_new_identity_requires_an_invite,
    ["CAP-HTTP-013"],
    "CAP-HTTP-013 (Rust-only change, 027-FR-007) email verify for a new identity answers INVITE_REQUIRED",
    invite_required_for_new_email
);

// ------------------------------------------------------ CAP-HTTP-014 ---

async fn recovery_replaces_password(w: &World) -> R<()> {
    let a = verified_account(w).await?;
    wait_out_resend_window().await;
    let mut b = w.browser()?;
    let verifier = token();
    let reply = email_request(&mut b, &login_request(&a.email, "recover", &verifier)).await?;
    assert_eq!(reply.status, 202, "{}", reply.body);
    let challenge_id = field(&reply.json()?, "challenge_id")?.to_string();
    let code = mail_code(w, &a.email, 1).await?;
    let verify = json!({
        "challenge_id": challenge_id, "client_verifier": verifier, "code": code
    });
    let reply = b.post("/api/auth/email/verify", &verify).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    assert_eq!(j["status"], "reset_ready");
    let grant = field(&j, "reset_grant")?.to_string();
    assert!(is_token(&grant));

    let weak = json!({"reset_grant": grant, "client_verifier": verifier, "new_password": "a"});
    let reply = b.post("/api/auth/recovery/reset", &weak).await?;
    expect_envelope(&reply, 400, "invalid_proof");

    let fresh = "Conformance-pass-3!";
    let reset = json!({"reset_grant": grant, "client_verifier": verifier, "new_password": fresh});
    let reply = b.post("/api/auth/recovery/reset", &reset).await?;
    assert_eq!(reply.status, 204, "{}", reply.body);
    assert!(reply.body.is_empty());
    let reply = b.post("/api/auth/recovery/reset", &reset).await?;
    expect_envelope(&reply, 404, "owner_mismatch"); // a spent grant is gone

    let (_, old) = password_login(w, &a.email, &a.password).await?;
    assert_eq!(old.status, 401, "{}", old.body);
    let (_, new) = password_login(w, &a.email, fresh).await?;
    assert_eq!(new.status, 200, "{}", new.body);
    let mut old_session = a.b;
    let reply = old_session.get("/api/account/auth-methods").await?;
    assert_eq!(reply.status, 401, "reset signs out every session");
    Ok(())
}

cap_test!(
    cap_http_014_recovery_reset_replaces_the_password_and_ends_sessions,
    ["CAP-HTTP-014"],
    "CAP-HTTP-014 recovery reset answers 204, replaces the password and ends other sessions",
    recovery_replaces_password
);

async fn reset_rejects_unknown_grant(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let body = json!({
        "reset_grant": token(), "client_verifier": token(), "new_password": "Conformance-pass-4!"
    });
    let reply = b.post("/api/auth/recovery/reset", &body).await?;
    expect_envelope(&reply, 404, "owner_mismatch");
    let reply = b
        .post("/api/auth/recovery/reset", &json!({"reset_grant": "x"}))
        .await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_014_reset_rejects_an_unknown_grant,
    ["CAP-HTTP-014"],
    "CAP-HTTP-014 recovery reset answers 404 for an unknown grant and 422 for a malformed body",
    reset_rejects_unknown_grant
);

// ------------------------------------------------------ CAP-HTTP-015 ---

async fn confirm_issues_recent_proof(w: &World) -> R<()> {
    let mut a = account(w).await?;
    let mut other = account(w).await?;
    let ok = json!({
        "current_password": a.password, "action": "export", "expected_account_id": a.id
    });
    let reply = a.b.post("/api/auth/confirm/password", &ok).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    assert_eq!(j["status"], "reauthenticated");
    assert!(is_token(field(&j, "recent_proof")?));
    assert!(field(&j, "expires_at")?.contains('T'));

    let wrong = json!({
        "current_password": "not-the-password", "action": "export", "expected_account_id": a.id
    });
    let reply = a.b.post("/api/auth/confirm/password", &wrong).await?;
    expect_envelope(&reply, 403, "reauth_required");

    // Two-owner probe (027-FR-008): a foreign account id looks like a missing one.
    let foreign = json!({
        "current_password": other.password, "action": "export", "expected_account_id": a.id
    });
    let as_other = other.b.post("/api/auth/confirm/password", &foreign).await?;
    let missing = json!({
        "current_password": other.password, "action": "export", "expected_account_id": "no-such-account"
    });
    let as_missing = other.b.post("/api/auth/confirm/password", &missing).await?;
    expect_envelope(&as_other, 404, "owner_mismatch");
    expect_envelope(&as_missing, 404, "owner_mismatch");

    let mut anonymous = w.browser()?;
    let reply = anonymous.post("/api/auth/confirm/password", &ok).await?;
    expect_envelope(&reply, 401, "invalid_proof");
    let reply =
        a.b.post("/api/auth/confirm/password", &json!({"action": "export"}))
            .await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_015_confirm_password_issues_a_recent_proof_for_the_caller_only,
    ["CAP-HTTP-015"],
    "CAP-HTTP-015 password confirmation issues a proof and hides foreign accounts (027-FR-008)",
    confirm_issues_recent_proof
);

// ------------------------------------------------------ CAP-HTTP-016 ---

async fn start_returns_url_and_binder(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let google = start(&mut b, "google", "web", "login", json!({})).await?;
    assert!(is_token(&google.attempt_id));
    assert!(is_token(&google.state));
    let nonce = field(&google.reply.json()?, "nonce")?.to_string();
    assert!(is_token(&nonce));
    let url = google.url.clone().ok_or("no google url")?;
    assert!(url.starts_with("https://accounts.google.com/"), "{url}");
    assert_eq!(query_param(&url, "state"), Some(google.state.clone()));
    assert!(cookie_line(&google.reply, BINDER).is_some());

    let apple = start(&mut b, "apple", "web", "login", json!({})).await?;
    let url = apple.url.clone().ok_or("no apple url")?;
    assert!(url.starts_with("https://appleid.apple.com/"), "{url}");
    assert!(cookie_line(&apple.reply, BINDER).is_some());

    let native = start(&mut b, "apple", "ios", "login", json!({})).await?;
    assert!(
        native.url.is_none(),
        "native Apple has no authorization url"
    );
    assert!(
        cookie_line(&native.reply, BINDER).is_none(),
        "no binder for ios"
    );
    Ok(())
}

cap_test!(
    cap_http_016_start_returns_the_authorization_url_and_binder_cookie,
    ["CAP-HTTP-016"],
    "CAP-HTTP-016 provider start returns attempt, state, nonce, url and a web binder cookie",
    start_returns_url_and_binder
);

async fn start_rejects_bad_requests(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let verifier = token();
    let body =
        json!({"purpose": "login", "client": "web", "client_challenge": challenge(&verifier)});
    let reply = b.post("/api/auth/providers/github/start", &body).await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    let link = json!({
        "purpose": "link", "client": "web", "client_challenge": challenge(&verifier),
        "action": "link:google", "expected_account_id": "someone", "recent_proof": token()
    });
    let reply = b.post("/api/auth/providers/google/start", &link).await?;
    expect_envelope(&reply, 401, "invalid_proof");
    let no_account =
        json!({"purpose": "link", "client": "web", "client_challenge": challenge(&verifier)});
    let reply = b
        .post("/api/auth/providers/google/start", &no_account)
        .await?;
    expect_envelope(&reply, 400, "invalid_proof");
    let reply = b
        .post(
            "/api/auth/providers/google/start",
            &json!({"purpose": "login"}),
        )
        .await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_016_start_rejects_unknown_providers_and_unauthenticated_links,
    ["CAP-HTTP-016"],
    "CAP-HTTP-016 provider start refuses unknown providers and session-less link attempts",
    start_rejects_bad_requests
);

// ------------------------------------------------------ CAP-HTTP-017 ---

async fn google_callback_redirects(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let origin = account_origin(&mut b).await?;
    let (started, callback) = provider_round(
        w,
        &mut b,
        "google",
        "login",
        json!({}),
        ("sub-017", "g017@conformance-bb.dev"),
    )
    .await?;
    assert_eq!(callback.status, 303, "{}", callback.body);
    let location = callback.header("location").ok_or("no location")?;
    assert!(
        location.starts_with(&format!("{origin}/auth/complete#")),
        "{location}"
    );
    let parts = fragment(&callback);
    assert_eq!(parts.get("attempt"), Some(&started.attempt_id));
    assert_eq!(parts.get("state"), Some(&started.state));
    assert!(parts.get("grant").is_some_and(|g| is_token(g)));
    Ok(())
}

cap_test!(
    cap_http_017_google_callback_redirects_with_a_handoff_grant,
    ["CAP-HTTP-017"],
    "CAP-HTTP-017 Google callback answers 303 to the web origin with attempt, state and grant",
    google_callback_redirects
);

async fn google_callback_cancel(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let started = start(&mut b, "google", "web", "login", json!({})).await?;
    let path = format!(
        "/api/auth/providers/google/callback?error=access_denied&state={}",
        started.state
    );
    let reply = b.get(&path).await?;
    assert_eq!(reply.status, 303, "{}", reply.body);
    let parts = fragment(&reply);
    assert_eq!(parts.get("error").map(String::as_str), Some("cancelled"));
    assert_eq!(parts.get("attempt"), Some(&started.attempt_id));
    assert!(!parts.contains_key("grant"));
    Ok(())
}

cap_test!(
    cap_http_017_google_callback_reports_a_cancelled_sign_in,
    ["CAP-HTTP-017"],
    "CAP-HTTP-017 Google callback with a provider error redirects with error=cancelled",
    google_callback_cancel
);

async fn google_callback_rejects_input(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let reply = b.get("/api/auth/providers/google/callback").await?;
    expect_envelope(&reply, 400, "invalid_proof");
    let both = format!(
        "/api/auth/providers/google/callback?code=a&error=b&state={}",
        token()
    );
    expect_envelope(&b.get(&both).await?, 400, "invalid_proof");
    let short = "/api/auth/providers/google/callback?code=a&state=short";
    expect_envelope(&b.get(short).await?, 400, "invalid_proof");
    let unknown = format!(
        "/api/auth/providers/google/callback?code=a&state={}",
        token()
    );
    expect_envelope(&b.get(&unknown).await?, 404, "owner_mismatch");

    let started = start(&mut b, "google", "web", "login", json!({})).await?;
    let mut elsewhere = w.browser()?;
    let path = format!(
        "/api/auth/providers/google/callback?code=a&state={}",
        started.state
    );
    let reply = elsewhere.get(&path).await?;
    expect_envelope(&reply, 403, "invalid_proof");
    Ok(())
}

cap_test!(
    cap_http_017_google_callback_rejects_malformed_unknown_and_unbound_requests,
    ["CAP-HTTP-017"],
    "CAP-HTTP-017 Google callback refuses bad shape, unknown state and a missing binder",
    google_callback_rejects_input
);

// ------------------------------------------------------ CAP-HTTP-018 ---

async fn apple_callback_redirects(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let (started, callback) = provider_round(
        w,
        &mut b,
        "apple",
        "login",
        json!({}),
        ("sub-018", "a018@conformance-bb.dev"),
    )
    .await?;
    assert_eq!(callback.status, 303, "{}", callback.body);
    let parts = fragment(&callback);
    assert_eq!(parts.get("attempt"), Some(&started.attempt_id));
    assert_eq!(parts.get("state"), Some(&started.state));
    assert!(parts.get("grant").is_some_and(|g| is_token(g)));
    let cleared = cookie_line(&callback, BINDER).ok_or("binder not cleared")?;
    assert!(
        cleared.to_ascii_lowercase().contains("max-age=0"),
        "{cleared}"
    );
    Ok(())
}

cap_test!(
    cap_http_018_apple_form_post_callback_redirects_with_a_handoff_grant,
    ["CAP-HTTP-018"],
    "CAP-HTTP-018 Apple form_post callback answers 303 with the handoff and clears the binder",
    apple_callback_redirects
);

async fn apple_callback_rejects_malformed_forms(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let state = token();
    let path = "/api/auth/providers/apple/callback";
    let json_type = b
        .raw(
            path,
            &[("Content-Type", "application/json")],
            format!(r#"{{"code":"a","state":"{state}"}}"#).into_bytes(),
        )
        .await?;
    expect_envelope(&json_type, 400, "invalid_proof");
    let huge = format!("code={}&state={state}", "a".repeat(40_000));
    expect_envelope(&b.form(path, &huge).await?, 400, "invalid_proof");
    let many = format!("code=a&state={state}&a=1&b=2&c=3&d=4");
    expect_envelope(&b.form(path, &many).await?, 400, "invalid_proof");
    let twice = format!("code=a&code=b&state={state}");
    expect_envelope(&b.form(path, &twice).await?, 400, "invalid_proof");
    let neither = format!("state={state}");
    expect_envelope(&b.form(path, &neither).await?, 400, "invalid_proof");
    let unknown = format!("code=a&state={state}");
    expect_envelope(&b.form(path, &unknown).await?, 404, "owner_mismatch");
    Ok(())
}

cap_test!(
    cap_http_018_apple_callback_rejects_malformed_form_posts,
    ["CAP-HTTP-018"],
    "CAP-HTTP-018 Apple callback bounds the form: content type, size, field count, duplicates",
    apple_callback_rejects_malformed_forms
);

// ------------------------------------------------------ CAP-HTTP-019 ---

async fn complete_links_and_signs_in(w: &World) -> R<()> {
    let mut a = account(w).await?;
    let (subject, email) = identity_for(&format!("g{}@conformance-bb.dev", slug()));
    link_google(w, &mut a, &subject, &email).await?;
    let methods = a.b.get("/api/account/auth-methods").await?;
    let listed = methods.json()?;
    let google = listed["methods"]
        .as_array()
        .and_then(|m| m.iter().find(|x| x["method"] == "google"))
        .ok_or("google method not listed after link")?
        .clone();
    assert_eq!(google["state"], "active");

    let mut fresh = w.browser()?;
    let (started, callback) = provider_round(
        w,
        &mut fresh,
        "google",
        "login",
        json!({}),
        (&subject, &email),
    )
    .await?;
    let reply = complete(&mut fresh, &started, &callback).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    assert_eq!(j["status"], "signed_in");
    assert_eq!(j["user"]["id"], a.id.as_str());
    assert!(
        cookie_line(&reply, SESSION).is_some(),
        "completion sets the session"
    );
    Ok(())
}

cap_test!(
    cap_http_019_complete_links_a_provider_and_signs_in_the_bound_owner,
    ["CAP-HTTP-019"],
    "CAP-HTTP-019 provider completion links for a signed-in owner and signs in a bound identity",
    complete_links_and_signs_in
);

async fn complete_requires_existing_account(w: &World) -> R<()> {
    let a = account(w).await?;
    let mut b = w.browser()?;
    let (started, callback) = provider_round(
        w,
        &mut b,
        "google",
        "login",
        json!({}),
        (&format!("sub-{}", slug()), &a.email),
    )
    .await?;
    let reply = complete(&mut b, &started, &callback).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    assert_eq!(j["status"], "existing_account_required");
    assert!(cookie_line(&reply, SESSION).is_none());
    let replay = complete(&mut b, &started, &callback).await?;
    expect_envelope(&replay, 400, "invalid_proof");
    Ok(())
}

cap_test!(
    cap_http_019_complete_for_an_unbound_identity_requires_the_existing_account,
    ["CAP-HTTP-019"],
    "CAP-HTTP-019 provider completion for an unbound identity of an existing email is single use",
    complete_requires_existing_account
);

async fn complete_rejects_bad_handoffs(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let (started, callback) = provider_round(
        w,
        &mut b,
        "google",
        "login",
        json!({}),
        (
            &format!("sub-{}", slug()),
            &format!("g{}@conformance-bb.dev", slug()),
        ),
    )
    .await?;
    let grant = fragment(&callback)
        .get("grant")
        .cloned()
        .ok_or("no grant")?;
    let path = "/api/auth/providers/complete";
    let body = |verifier: &str, grant: &str| {
        json!({
            "attempt_id": started.attempt_id, "state": started.state,
            "handoff_code": grant, "client_verifier": verifier
        })
    };
    let reply = b.post(path, &body(&token(), &grant)).await?;
    expect_envelope(&reply, 404, "owner_mismatch");
    let reply = b.post(path, &body(&started.verifier, &token())).await?;
    expect_envelope(&reply, 400, "invalid_proof");
    let reply = b.post(path, &json!({"attempt_id": "x"})).await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_019_complete_rejects_a_wrong_verifier_or_handoff,
    ["CAP-HTTP-019"],
    "CAP-HTTP-019 provider completion refuses a wrong verifier, a wrong handoff and a bad body",
    complete_rejects_bad_handoffs
);

async fn invite_required_for_new_google_identity(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let identity = identity_for(&format!("g{}@conformance-bb.dev", slug()));
    let (started, callback) = provider_round(
        w,
        &mut b,
        "google",
        "login",
        json!({}),
        (&identity.0, &identity.1),
    )
    .await?;
    let reply = complete(&mut b, &started, &callback).await?;
    expect_invite_required(&reply);
    Ok(())
}

rust_only_test!(
    cap_http_019_rust_new_identity_requires_an_invite,
    ["CAP-HTTP-019"],
    "CAP-HTTP-019 (Rust-only change, 027-FR-007) Google completion for a new identity answers INVITE_REQUIRED",
    invite_required_for_new_google_identity
);

/// A pending signup handed back for a brand-new Google identity.
async fn pending_signup(w: &World, b: &mut Browser) -> R<(String, String)> {
    let email = format!("g{}@conformance-bb.dev", slug());
    let (started, callback) = provider_round(
        w,
        b,
        "google",
        "login",
        json!({}),
        (&format!("sub-{}", slug()), &email),
    )
    .await?;
    let reply = complete(b, &started, &callback).await?;
    Ok((expect_invite_required(&reply), email))
}

async fn signup_complete_creates_the_account(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let (pending, email) = pending_signup(w, &mut b).await?;
    let invite = w.ctl.invites(1).await?;
    let code = invite["codes"][0].as_str().ok_or("no invite")?.to_string();
    let body = json!({"pending": pending, "invite_code": code});
    let reply = b.post("/api/auth/signup/complete", &body).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    assert_eq!(j["status"], "signed_in");
    assert_eq!(j["user"]["email"], email.as_str());
    assert!(cookie_line(&reply, SESSION).is_some());

    let again = b.post("/api/auth/signup/complete", &body).await?;
    assert_eq!(again.status, 410, "{}", again.body);
    assert_eq!(detail_code(&again), "SIGNUP_EXPIRED");

    let (second, _) = pending_signup(w, &mut b).await?;
    let used = json!({"pending": second, "invite_code": code});
    let reply = b.post("/api/auth/signup/complete", &used).await?;
    assert_eq!(reply.status, 400, "{}", reply.body);
    assert_eq!(detail_code(&reply), "INVITE_INVALID");
    Ok(())
}

rust_only_test!(
    cap_http_019_rust_signup_complete_consumes_pending_and_invite,
    ["CAP-HTTP-019"],
    "CAP-HTTP-019 (Rust-only change, 027-FR-007) signup/complete creates the account once per pending and invite",
    signup_complete_creates_the_account
);

async fn signup_complete_invalid_invite_keeps_pending(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let (pending, _) = pending_signup(w, &mut b).await?;
    let bad = json!({"pending": pending, "invite_code": token()});
    let reply = b.post("/api/auth/signup/complete", &bad).await?;
    assert_eq!(reply.status, 400, "{}", reply.body);
    assert_eq!(detail_code(&reply), "INVITE_INVALID");
    let invite = w.ctl.invites(1).await?;
    let code = invite["codes"][0].as_str().ok_or("no invite")?;
    let good = json!({"pending": pending, "invite_code": code});
    let reply = b.post("/api/auth/signup/complete", &good).await?;
    assert_eq!(
        reply.status, 200,
        "an invalid invite leaves the pending usable: {}",
        reply.body
    );
    Ok(())
}

rust_only_test!(
    cap_http_019_rust_signup_complete_invalid_invite_leaves_pending_usable,
    ["CAP-HTTP-019"],
    "CAP-HTTP-019 (Rust-only change, 027-FR-007) signup/complete answers INVITE_INVALID and keeps the pending token",
    signup_complete_invalid_invite_keeps_pending
);

async fn signup_complete_rejects_unbound_pending(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let invite = w.ctl.invites(1).await?;
    let code = invite["codes"][0].as_str().ok_or("no invite")?.to_string();
    let unknown = json!({"pending": token(), "invite_code": code});
    let reply = b.post("/api/auth/signup/complete", &unknown).await?;
    assert_eq!(reply.status, 410, "{}", reply.body);
    assert_eq!(detail_code(&reply), "SIGNUP_EXPIRED");

    let (pending, _) = pending_signup(w, &mut b).await?;
    let mut other = w.browser()?;
    let foreign = json!({"pending": pending, "invite_code": code});
    let reply = other.post("/api/auth/signup/complete", &foreign).await?;
    assert_eq!(
        reply.status, 410,
        "a pending token is bound to its browser: {}",
        reply.body
    );
    assert_eq!(detail_code(&reply), "SIGNUP_EXPIRED");
    Ok(())
}

rust_only_test!(
    cap_http_019_rust_signup_complete_rejects_unknown_or_foreign_pending,
    ["CAP-HTTP-019"],
    "CAP-HTTP-019 (Rust-only change, 027-FR-007) signup/complete answers SIGNUP_EXPIRED for unknown or foreign pending",
    signup_complete_rejects_unbound_pending
);

// ------------------------------------------------------ CAP-HTTP-020 ---

fn native_audience() -> String {
    std::env::var("BB_CONFORMANCE_APPLE_NATIVE_AUDIENCE")
        .unwrap_or_else(|_| "com.example.conformance.ios".into())
}

fn native_body(started: &Started, verifier: &str, state: &str) -> Value {
    json!({
        "attempt_id": started.attempt_id, "state": state,
        "authorization_code": "synthetic-code", "identity_token": "synthetic-token",
        "client_verifier": verifier
    })
}

async fn native_existing_email(w: &World) -> R<()> {
    let a = account(w).await?;
    let mut b = w.browser()?;
    let _guard = IDENTITY.lock().await;
    let started = start(&mut b, "apple", "ios", "login", json!({})).await?;
    let script = identity_script(&native_audience(), &format!("sub-{}", slug()), &a.email);
    w.ctl.script_provider("identity", script, false).await?;
    let body = native_body(&started, &started.verifier, &started.state);
    let reply = b
        .post("/api/auth/providers/apple/native/complete", &body)
        .await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    assert_eq!(reply.json()?["status"], "existing_account_required");
    assert!(cookie_line(&reply, SESSION).is_none());
    Ok(())
}

cap_test!(
    cap_http_020_native_apple_completion_for_an_existing_email_requires_the_account,
    ["CAP-HTTP-020"],
    "CAP-HTTP-020 native Apple completion exchanges the token and never signs in an unbound identity",
    native_existing_email
);

async fn native_rejects_bad_requests(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let path = "/api/auth/providers/apple/native/complete";
    let started = start(&mut b, "apple", "ios", "login", json!({})).await?;
    let reply = b
        .post(path, &native_body(&started, &token(), &started.state))
        .await?;
    expect_envelope(&reply, 404, "owner_mismatch");
    let reply = b
        .post(path, &native_body(&started, &started.verifier, &token()))
        .await?;
    expect_envelope(&reply, 400, "invalid_proof");
    let web = start(&mut b, "apple", "web", "login", json!({})).await?;
    let reply = b
        .post(path, &native_body(&web, &web.verifier, &web.state))
        .await?;
    expect_envelope(&reply, 400, "invalid_proof");
    let reply = b
        .post(path, &json!({"attempt_id": started.attempt_id}))
        .await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_020_native_apple_completion_rejects_mismatched_attempts,
    ["CAP-HTTP-020"],
    "CAP-HTTP-020 native Apple completion refuses a wrong verifier, state, channel and body",
    native_rejects_bad_requests
);

async fn invite_required_for_new_native_identity(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let _guard = IDENTITY.lock().await;
    let started = start(&mut b, "apple", "ios", "login", json!({})).await?;
    let email = format!("a{}@conformance-bb.dev", slug());
    let script = identity_script(&native_audience(), &format!("sub-{}", slug()), &email);
    w.ctl.script_provider("identity", script, false).await?;
    let body = native_body(&started, &started.verifier, &started.state);
    let reply = b
        .post("/api/auth/providers/apple/native/complete", &body)
        .await?;
    expect_invite_required(&reply);
    Ok(())
}

rust_only_test!(
    cap_http_020_rust_new_identity_requires_an_invite,
    ["CAP-HTTP-020"],
    "CAP-HTTP-020 (Rust-only change, 027-FR-007) native Apple completion for a new identity answers INVITE_REQUIRED",
    invite_required_for_new_native_identity
);

// ------------------------------------------------------ CAP-HTTP-021 ---

async fn notification_acknowledged(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let _guard = IDENTITY.lock().await;
    w.ctl
        .script_provider("identity", json!([{}, {}]), false)
        .await?;
    let body = json!({"payload": "synthetic-signed-payload"});
    let first = b
        .post("/api/auth/providers/apple/notifications", &body)
        .await?;
    assert_eq!(first.status, 204, "{}", first.body);
    assert!(first.body.is_empty());
    let replay = b
        .post("/api/auth/providers/apple/notifications", &body)
        .await?;
    assert_eq!(
        replay.status, 204,
        "a replayed event is acknowledged: {}",
        replay.body
    );
    Ok(())
}

cap_test!(
    cap_http_021_apple_notification_is_acknowledged_without_a_session,
    ["CAP-HTTP-021"],
    "CAP-HTTP-021 Apple server notification answers 204 without a session and tolerates replays",
    notification_acknowledged
);

async fn notification_rejected(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let _guard = IDENTITY.lock().await;
    w.ctl
        .script_provider("identity", json!([{"error": "invalid_proof"}]), false)
        .await?;
    let reply = b
        .post(
            "/api/auth/providers/apple/notifications",
            &json!({"payload": "unverifiable"}),
        )
        .await?;
    assert_eq!(reply.status, 400, "{}", reply.body);
    assert_eq!(detail_code(&reply), "invalid_proof");
    assert!(
        reply.json()?["message"]
            .as_str()
            .is_some_and(|m| !m.is_empty())
    );
    let reply = b
        .post(
            "/api/auth/providers/apple/notifications",
            &json!({"payload": ""}),
        )
        .await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_021_apple_notification_that_cannot_be_verified_is_rejected,
    ["CAP-HTTP-021"],
    "CAP-HTTP-021 Apple server notification refuses an unverifiable payload and an empty body",
    notification_rejected
);

// ------------------------------------------------------ CAP-HTTP-022 ---

async fn auth_methods_are_owner_scoped(w: &World) -> R<()> {
    let mut a = account(w).await?;
    let mut other = account(w).await?;
    let reply = a.b.get("/api/account/auth-methods").await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    assert_eq!(j["account_id"], a.id.as_str());
    assert_eq!(j["email"], a.email.as_str());
    assert_eq!(j["email_verified"], false);
    assert_eq!(j["email_delivery"], "disabled", "unverified address");
    assert_eq!(j["has_password"], true);
    let methods = j["methods"].as_array().ok_or("no methods")?;
    let named = |name: &str| methods.iter().find(|m| m["method"] == name).cloned();
    let password = named("password").ok_or("no password entry")?;
    assert_eq!(
        (password["state"].as_str(), password["usable"].as_bool()),
        (Some("active"), Some(true))
    );
    let email = named("email").ok_or("no email entry")?;
    assert_eq!(
        email["usable"], false,
        "an unverified address is not a usable method"
    );

    // Two-owner probe (027-FR-008): each cookie sees only its own account.
    let theirs = other.b.get("/api/account/auth-methods").await?.json()?;
    assert_eq!(theirs["account_id"], other.id.as_str());
    assert_ne!(theirs["account_id"], j["account_id"]);
    assert_ne!(theirs["email"], j["email"]);

    let mut anonymous = w.browser()?;
    let reply = anonymous.get("/api/account/auth-methods").await?;
    expect_envelope(&reply, 401, "invalid_proof");
    Ok(())
}

cap_test!(
    cap_http_022_auth_methods_lists_only_the_callers_methods,
    ["CAP-HTTP-022"],
    "CAP-HTTP-022 account auth-methods lists the caller's methods and nothing of another owner (027-FR-008)",
    auth_methods_are_owner_scoped
);

// ------------------------------------------------------ CAP-HTTP-023 ---

fn unlink_path() -> &'static str {
    "/api/account/auth-methods/google/unlink"
}

async fn unlink_removes_binding(w: &World) -> R<()> {
    let mut a = account(w).await?;
    let mut other = account(w).await?;
    let (subject, email) = identity_for(&format!("g{}@conformance-bb.dev", slug()));
    link_google(w, &mut a, &subject, &email).await?;

    // Two-owner probe (027-FR-008): a foreign account id looks like a missing one.
    let secret = proof(&mut a, "unlink:google").await?;
    let foreign = json!({"recent_proof": secret, "expected_account_id": a.id});
    let as_other = other.b.post(unlink_path(), &foreign).await?;
    let missing = json!({"recent_proof": secret, "expected_account_id": "no-such-account"});
    let as_missing = other.b.post(unlink_path(), &missing).await?;
    expect_envelope(&as_other, 404, "owner_mismatch");
    expect_envelope(&as_missing, 404, "owner_mismatch");

    let wrong_action = proof(&mut a, "password").await?;
    let body = json!({"recent_proof": wrong_action, "expected_account_id": a.id});
    expect_envelope(
        &a.b.post(unlink_path(), &body).await?,
        403,
        "reauth_required",
    );

    let body = json!({"recent_proof": secret, "expected_account_id": a.id});
    let reply = a.b.post(unlink_path(), &body).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let j = reply.json()?;
    assert_eq!(j["signed_out"], false);
    assert_eq!(j["methods"]["account_id"], a.id.as_str());
    let listed = a.b.get("/api/account/auth-methods").await?.json()?;
    assert!(
        listed["methods"]
            .as_array()
            .is_some_and(|m| m.iter().all(|x| x["method"] != "google")),
        "the unlinked binding is gone"
    );

    let again = proof(&mut a, "unlink:google").await?;
    let body = json!({"recent_proof": again, "expected_account_id": a.id});
    expect_envelope(
        &a.b.post(unlink_path(), &body).await?,
        404,
        "owner_mismatch",
    );
    let bad =
        a.b.post("/api/account/auth-methods/github/unlink", &body)
            .await?;
    assert_eq!(bad.status, 422, "{}", bad.body);
    Ok(())
}

cap_test!(
    cap_http_023_unlink_removes_the_binding_and_hides_foreign_accounts,
    ["CAP-HTTP-023"],
    "CAP-HTTP-023 unlink removes the binding, needs the matching proof and hides foreign accounts (027-FR-008)",
    unlink_removes_binding
);

async fn unlink_signs_out_own_session(w: &World) -> R<()> {
    let mut a = account(w).await?;
    let (subject, email) = identity_for(&format!("g{}@conformance-bb.dev", slug()));
    link_google(w, &mut a, &subject, &email).await?;
    let mut google = w.browser()?;
    let (started, callback) = provider_round(
        w,
        &mut google,
        "google",
        "login",
        json!({}),
        (&subject, &email),
    )
    .await?;
    let reply = complete(&mut google, &started, &callback).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);

    let body = json!({
        "current_password": a.password, "action": "unlink:google", "expected_account_id": a.id
    });
    let reply = google.post("/api/auth/confirm/password", &body).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    let secret = field(&reply.json()?, "recent_proof")?.to_string();
    let unlink = json!({"recent_proof": secret, "expected_account_id": a.id});
    let reply = google.post(unlink_path(), &unlink).await?;
    assert_eq!(reply.status, 200, "{}", reply.body);
    assert_eq!(reply.json()?["signed_out"], true);
    let cleared = cookie_line(&reply, SESSION).ok_or("session cookie not cleared")?;
    assert!(
        cleared.to_ascii_lowercase().contains("max-age=0"),
        "{cleared}"
    );
    Ok(())
}

cap_test!(
    cap_http_023_unlinking_the_signing_in_method_clears_the_session_cookie,
    ["CAP-HTTP-023"],
    "CAP-HTTP-023 unlink reports signed_out and clears the cookie when the caller signed in with that method",
    unlink_signs_out_own_session
);

// ------------------------------------------------------ CAP-HTTP-024 ---

const NEW_PASSWORD: &str = "Conformance-pass-2!";

async fn set_password_replaces_credentials(w: &World) -> R<()> {
    let mut a = account(w).await?;
    let secret = proof(&mut a, "password").await?;
    let body = json!({
        "recent_proof": secret, "expected_account_id": a.id, "new_password": NEW_PASSWORD
    });
    let reply = a.b.post("/api/account/auth-password", &body).await?;
    assert_eq!(reply.status, 204, "{}", reply.body);
    assert!(reply.body.is_empty());
    let replay = a.b.post("/api/account/auth-password", &body).await?;
    expect_envelope(&replay, 404, "owner_mismatch"); // the spent proof is gone

    assert_eq!(
        password_login(w, &a.email, &a.password).await?.1.status,
        401
    );
    assert_eq!(
        password_login(w, &a.email, NEW_PASSWORD).await?.1.status,
        200
    );
    let current = a.b.get("/api/account/auth-methods").await?;
    assert_eq!(
        current.status, 200,
        "the calling session survives: {}",
        current.body
    );
    Ok(())
}

cap_test!(
    cap_http_024_set_password_answers_204_and_spends_the_proof,
    ["CAP-HTTP-024"],
    "CAP-HTTP-024 set password answers 204, replaces the credential and consumes the proof",
    set_password_replaces_credentials
);

async fn set_password_is_owner_scoped(w: &World) -> R<()> {
    let mut a = account(w).await?;
    let mut other = account(w).await?;
    let secret = proof(&mut a, "password").await?;
    let own_id = json!({
        "recent_proof": secret, "expected_account_id": other.id, "new_password": NEW_PASSWORD
    });
    // Two-owner probe (027-FR-008): A's proof is unknown to B, and A's id is not B's.
    expect_envelope(
        &other.b.post("/api/account/auth-password", &own_id).await?,
        404,
        "owner_mismatch",
    );
    let foreign_id = json!({
        "recent_proof": secret, "expected_account_id": a.id, "new_password": NEW_PASSWORD
    });
    expect_envelope(
        &other
            .b
            .post("/api/account/auth-password", &foreign_id)
            .await?,
        404,
        "owner_mismatch",
    );

    let weak = json!({"recent_proof": secret, "expected_account_id": a.id, "new_password": "a"});
    expect_envelope(
        &a.b.post("/api/account/auth-password", &weak).await?,
        400,
        "invalid_proof",
    );

    let mut anonymous = w.browser()?;
    expect_envelope(
        &anonymous
            .post("/api/account/auth-password", &foreign_id)
            .await?,
        401,
        "invalid_proof",
    );
    let reply =
        a.b.post("/api/account/auth-password", &json!({"new_password": "x"}))
            .await?;
    assert_eq!(reply.status, 422, "{}", reply.body);
    Ok(())
}

cap_test!(
    cap_http_024_set_password_is_scoped_to_the_proof_owner,
    ["CAP-HTTP-024"],
    "CAP-HTTP-024 set password refuses another owner's proof or id and a weak password (027-FR-008)",
    set_password_is_owner_scoped
);

// ------------------------------------------------------ CAP-MW-010 ---

async fn modern_auth_envelope(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let body = serde_json::to_vec(&json!({"email": "x@conformance-bb.dev"}))?;
    let json_type = ("Content-Type", "application/json");
    let reply = b
        .raw(
            "/api/auth/email/request",
            &[json_type, ("Origin", "https://evil.conformance-bb.dev")],
            body.clone(),
        )
        .await?;
    expect_envelope(&reply, 403, "invalid_proof");
    let reply = b
        .raw(
            "/api/auth/email/request",
            &[json_type, ("Sec-Fetch-Site", "cross-site")],
            body.clone(),
        )
        .await?;
    expect_envelope(&reply, 403, "invalid_proof");
    let reply = b
        .raw(
            "/api/auth/email/request",
            &[("Content-Type", "text/plain")],
            body,
        )
        .await?;
    expect_envelope(&reply, 400, "invalid_proof");
    let reply = b.get("/api/account/auth-methods").await?;
    expect_envelope(&reply, 401, "invalid_proof");
    assert!(reply.header("x-correlation-id").is_some());
    Ok(())
}

cap_test!(
    cap_mw_010_modern_auth_errors_use_the_coarse_envelope,
    ["CAP-MW-010"],
    "CAP-MW-010 modern auth errors carry the fixed message, detail.code and correlation id",
    modern_auth_envelope
);

async fn cli_auth_envelope(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let reply = b.post("/api/auth/device/token", &json!({})).await?;
    assert!(reply.status >= 400, "{}", reply.body);
    let cache = reply.header("cache-control").unwrap_or_default();
    assert!(cache.contains("no-store"), "cache-control: {cache}");
    let j = reply.json()?;
    let message = field(&j, "message")?;
    assert!(
        message == "CLI authorization could not complete."
            || message == "CLI authorization request is invalid.",
        "{message}"
    );
    assert!(!detail_code(&reply).is_empty());
    assert_eq!(j["reference_id"].as_str(), reply.header("x-correlation-id"));
    Ok(())
}

cap_test!(
    cap_mw_010_cli_auth_errors_are_not_cacheable,
    ["CAP-MW-010"],
    "CAP-MW-010 CLI authorization errors carry no-store, a fixed message and detail.code",
    cli_auth_envelope
);

// ------------------------------------------------------ CAP-MW-013 ---

async fn binder_cookie_attributes(w: &World) -> R<()> {
    let mut b = w.browser()?;
    let started = start(&mut b, "google", "web", "login", json!({})).await?;
    let line = cookie_line(&started.reply, BINDER).ok_or("no binder cookie")?;
    let lower = line.to_ascii_lowercase();
    for attribute in [
        "httponly",
        "secure",
        "samesite=none",
        "path=/api/auth/providers",
        "max-age=600",
    ] {
        assert!(
            lower.contains(attribute),
            "binder cookie lacks {attribute}: {line}"
        );
    }
    assert!(b.jar.contains_key(BINDER));

    let path = format!(
        "/api/auth/providers/google/callback?error=access_denied&state={}",
        started.state
    );
    let reply = b.get(&path).await?;
    assert_eq!(reply.status, 303, "{}", reply.body);
    let cleared = cookie_line(&reply, BINDER).ok_or("callback did not delete the binder")?;
    let lower = cleared.to_ascii_lowercase();
    assert!(lower.contains("max-age=0"), "{cleared}");
    assert!(lower.contains("path=/api/auth/providers"), "{cleared}");
    assert!(!b.jar.contains_key(BINDER));
    Ok(())
}

cap_test!(
    cap_mw_013_binder_cookie_is_scoped_short_lived_and_deleted_on_callback,
    ["CAP-MW-013"],
    "CAP-MW-013 binder cookie is HttpOnly, Secure, SameSite=None, path-scoped, 600 s, deleted on callback",
    binder_cookie_attributes
);
