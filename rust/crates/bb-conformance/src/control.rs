//! Typed test control client (contracts/test-control.md) and owner factory.

use crate::{Client, Config, Result};
use reqwest::Method;
use serde_json::{Value, json};

/// A signed-in synthetic owner; `client` carries the session cookie.
pub struct Owner {
    pub email: String,
    pub client: Client,
}

/// Seeds data and controls time and providers; the only seeding path.
pub struct TestControl {
    client: Client,
    token: String,
}

/// One typed method per contract operation; each returns the JSON reply
/// (`null` when the reply has no body).
macro_rules! ops {
    ($($(#[$m:meta])* $name:ident($($arg:ident: $ty:ty),*) $verb:ident $path:expr, $body:expr;)*) => {
        $($(#[$m])* pub async fn $name(&self, $($arg: $ty),*) -> Result<Value> {
            self.call(Method::$verb, &format!($path), $body).await
        })*
    };
}

impl TestControl {
    pub fn new(cfg: &Config) -> Result<Self> {
        let (client, token) = (Client::new(cfg)?, cfg.control_token.clone());
        Ok(Self { client, token })
    }

    async fn call(&self, method: Method, path: &str, body: Option<Value>) -> Result<Value> {
        let token = &self.token;
        let mut c = self
            .client
            .fresh()
            .with_header("X-Test-Control-Token", token);
        let reply = c
            .send(method, &format!("/api/__test__{path}"), body.as_ref())
            .await?;
        if reply.status >= 400 {
            return Err(format!("test control {path} answered {}", reply.status).into());
        }
        Ok(reply.json().unwrap_or(Value::Null))
    }

    ops! {
        invites(count: u32) POST "/invites", Some(json!({ "count": count }));
        admin(email: &str, password: &str) POST "/admin", Some(json!({ "email": email, "password": password }));
        flag(key: &str, mode: &str, owners: &[&str]) PUT "/flags/{key}", Some(json!({ "mode": mode, "owners": owners }));
        advance_clock(seconds: u64) POST "/clock", Some(json!({ "advance_seconds": seconds }));
        reset_clock() DELETE "/clock", None;
        sweep(name: &str) POST "/sweeps/{name}", Some(json!({}));
        aged_task(owner_email: &str, days: u32) POST "/review/aged-task", Some(json!({ "owner_email": owner_email, "days": days }));
        owner_tasks(email: &str) GET "/owners/{email}/tasks", None;
        script_provider(kind: &str, script: Value, hold: bool) PUT "/providers/{kind}", Some(json!({ "mode": "mock", "script": script, "hold": hold }));
        provider_calls(kind: &str) GET "/providers/{kind}/calls", None;
        release(kind: &str, count: u32) POST "/providers/{kind}/release", Some(json!({ "count": count }));
        mail() GET "/mail", None;
        reconcile() POST "/reconcile", Some(json!({}));
    }

    /// Invite, signup, session cookie: a new synthetic owner.
    pub async fn new_owner(&self, client: &Client) -> Result<Owner> {
        let invites = self.invites(1).await?;
        let code = invites["codes"][0]
            .as_str()
            .ok_or("no invite code minted")?;
        let email = format!("owner-{}@conformance.example.com", unique());
        let mut client = client.fresh();
        let body = json!({
            "email": email, "password": "Conformance-pass-1!", "invite_code": code
        });
        let reply = client.post("/api/auth/signup", &body).await?;
        if reply.status >= 400 {
            return Err(format!("synthetic signup answered {}", reply.status).into());
        }
        Ok(Owner { email, client })
    }
}

/// Process-unique token for synthetic identities and seeded text.
pub(crate) fn unique() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static N: AtomicU64 = AtomicU64::new(0);
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    format!("{t:x}{:x}", N.fetch_add(1, Ordering::Relaxed))
}
