use crate::{
    command::{AuthAction, Cli, LoginArgs, Request, Shape},
    config::{Config, Connection},
    credential::{self, Credential},
    error::{Error, Result},
    request,
};
use serde_json::{Value, json};
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
use time::{OffsetDateTime, format_description::well_known::Rfc3339};
use zeroize::Zeroizing;

fn operation(method: &str, path: &str, body: Option<Value>) -> Request {
    Request {
        method: method.into(),
        path: path.into(),
        query: vec![],
        body,
        key: None,
        shape: Shape::Other,
        list: false,
    }
}
fn canceled() -> Error {
    Error::new(
        "cancelled",
        "Login cancelled; the previous connection is preserved.",
        130,
    )
}
fn expired() -> Error {
    Error::new(
        "authorization_expired",
        "Authorization expired; start a fresh login.",
        11,
    )
}
fn account(value: &Value, secrets: &[&str]) -> Result<Value> {
    let id = value
        .get("id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty() && s.len() <= 500)
        .ok_or_else(Error::protocol)?;
    let mut result = json!({"id":id});
    for name in ["email", "display_name"] {
        if let Some(value) = value.get(name) {
            if !value.is_null() && !value.as_str().is_some_and(|v| v.len() <= 1024) {
                return Err(Error::protocol());
            }
            result[name] = value.clone();
        }
    }
    if secrets
        .iter()
        .any(|secret| result.to_string().contains(secret))
    {
        return Err(Error::protocol());
    }
    Ok(result)
}

pub fn run(cli: &Cli, action: &AuthAction) -> Result<Value> {
    if cli.json.is_some()
        || cli.key.is_some()
        || cli.revision.is_some()
        || cli.fields.is_some()
        || cli.full
        || cli.cursor.is_some()
        || !cli.query.is_empty()
        || cli.dry_run
    {
        return Err(Error::invalid(
            "Auth accepts only connection options and its own documented options.",
        ));
    }
    let mut config = Config::load(cli)?;
    let client = request::client()?;
    match action {
        AuthAction::Login(args) => login(&mut config, &client, args),
        AuthAction::Status => {
            let credential = credential::load(&config)?;
            let reply = request::send(
                &client,
                &config,
                &operation("GET", "/auth/me", None),
                Some(&credential),
            )?;
            Ok(
                json!({"data":{"server":config.server,"api_prefix":config.api_prefix,"account":account(&reply.value,&[&credential.token])?,"authenticated":true,"source":if credential.external {"environment"}else{config.connection.as_ref().map(|c|c.store.as_str()).unwrap_or("unknown")},"expires_at":if credential.external {None}else{config.connection.as_ref().map(|c|c.expires_at.as_str())}}}),
            )
        }
        AuthAction::Logout => logout(&mut config, &client),
    }
}

fn wait(cancel: &AtomicBool, deadline: Instant, seconds: u64) -> Result<()> {
    let until = (Instant::now() + Duration::from_secs(seconds)).min(deadline);
    while Instant::now() < until {
        if cancel.load(Ordering::SeqCst) {
            return Err(canceled());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    if cancel.load(Ordering::SeqCst) {
        return Err(canceled());
    }
    if Instant::now() >= deadline {
        return Err(expired());
    }
    Ok(())
}

fn issued_credential(reply: &request::Reply, config: &Config) -> Result<Credential> {
    if reply.value.get("credential_type").and_then(Value::as_str) != Some("session_cookie") {
        return Err(Error::protocol());
    }
    let name = reply
        .value
        .get("cookie_name")
        .and_then(Value::as_str)
        .ok_or_else(Error::protocol)?;
    credential::cookie_name(name).map_err(|_| Error::protocol())?;
    let expiry = reply
        .value
        .get("expires_at")
        .and_then(Value::as_str)
        .and_then(|v| OffsetDateTime::parse(v, &Rfc3339).ok())
        .filter(|v| *v > OffsetDateTime::now_utc())
        .ok_or_else(Error::protocol)?;
    let host = reqwest::Url::parse(&config.server).map_err(|_| Error::protocol())?;
    let mut found = None;
    for header in reply.headers.get_all(reqwest::header::SET_COOKIE) {
        let cookie = cookie::Cookie::parse(header.to_str().map_err(|_| Error::protocol())?)
            .map_err(|_| Error::protocol())?;
        if cookie.name() != name {
            continue;
        }
        if found.is_some()
            || cookie.http_only() != Some(true)
            || cookie.path() != Some("/")
            || cookie.same_site() != Some(cookie::SameSite::Lax)
            || (host.scheme() == "https" && cookie.secure() != Some(true))
            || cookie
                .domain()
                .is_some_and(|d| Some(d.trim_start_matches('.')) != host.host_str())
        {
            return Err(Error::protocol());
        }
        if let Some(max_age) = cookie.max_age()
            && (max_age.whole_seconds() <= 0
                || (expiry - OffsetDateTime::now_utc()).whole_seconds()
                    > max_age.whole_seconds() + 60)
        {
            return Err(Error::protocol());
        }
        if let Some(expires) = cookie.expires_datetime()
            && (expires <= OffsetDateTime::now_utc()
                || (expires - expiry).whole_seconds().abs() > 60)
        {
            return Err(Error::protocol());
        }
        if cookie.max_age().is_none() && cookie.expires_datetime().is_none() {
            return Err(Error::protocol());
        }
        credential::token_value(cookie.value()).map_err(|_| Error::protocol())?;
        found = Some(Credential {
            token: Zeroizing::new(cookie.value().to_owned()),
            cookie_name: name.into(),
            external: false,
        });
    }
    found.ok_or_else(Error::protocol)
}

fn cleanup(
    client: &reqwest::blocking::Client,
    config: &Config,
    credential: &Credential,
    store: &str,
    locator: &str,
    mut error: Error,
) -> Error {
    let local_cleared = credential::remove(config, store, locator).is_ok();
    let server_revoked = request::send(
        client,
        config,
        &operation("POST", "/auth/logout", None),
        Some(credential),
    )
    .is_ok();
    error.detail = Some(Box::new(
        json!({"new_session_local_cleared":local_cleared,"new_session_server_revoked":server_revoked,"cleanup_uncertain":!local_cleared || !server_revoked}),
    ));
    error
}

fn login(
    config: &mut Config,
    client: &reqwest::blocking::Client,
    args: &LoginArgs,
) -> Result<Value> {
    credential::preflight(config, &args.store)?;
    let locator = crate::storage::random_locator()?;
    let cancel = Arc::new(AtomicBool::new(false));
    let signal = cancel.clone();
    ctrlc::set_handler(move || signal.store(true, Ordering::SeqCst))
        .map_err(|_| Error::protocol())?;
    let start = request::send(
        client,
        config,
        &operation("POST", "/auth/device/start", Some(json!({}))),
        None,
    )?
    .value;
    let proof = Zeroizing::new(
        start
            .get("device_code")
            .and_then(Value::as_str)
            .filter(|s| {
                s.len() == 43
                    && s.bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
            })
            .ok_or_else(Error::protocol)?
            .to_owned(),
    );
    let code = start
        .get("user_code")
        .and_then(Value::as_str)
        .filter(|s| {
            s.len() == 9
                && s.as_bytes()[4] == b'-'
                && s.bytes()
                    .filter(|b| *b != b'-')
                    .all(|b| b"ABCDEFGHJKLMNPQRSTUVWXYZ23456789".contains(&b))
        })
        .ok_or_else(Error::protocol)?;
    let verification = start
        .get("verification_uri")
        .and_then(Value::as_str)
        .and_then(|v| reqwest::Url::parse(v).ok())
        .ok_or_else(Error::protocol)?;
    crate::config::canonical_server(&verification.origin().ascii_serialization())
        .map_err(|_| Error::protocol())?;
    if verification.path() != "/cli/authorize"
        || verification.query().is_some()
        || verification.fragment().is_some()
        || !verification.username().is_empty()
        || verification.password().is_some()
    {
        return Err(Error::protocol());
    }
    let complete = start
        .get("verification_uri_complete")
        .and_then(Value::as_str)
        .ok_or_else(Error::protocol)?;
    if complete != format!("{verification}#user_code={code}")
        || start.get("protocol_version").and_then(Value::as_u64) != Some(1)
    {
        return Err(Error::protocol());
    }
    let seconds = start
        .get("expires_in")
        .and_then(Value::as_u64)
        .filter(|v| *v > 0 && *v <= 600)
        .ok_or_else(Error::protocol)?;
    let mut interval = start
        .get("interval")
        .and_then(Value::as_u64)
        .filter(|v| *v >= 5 && *v <= 60)
        .ok_or_else(Error::protocol)?;
    let deadline = Instant::now() + Duration::from_secs(seconds);
    eprintln!("Open {verification} and enter {code}. Approve only your own CLI request.");
    if !args.no_browser && webbrowser::open(complete).is_err() {
        eprintln!("Browser could not open; use the URL and code above.");
    }
    let reply = loop {
        wait(&cancel, deadline, interval)?;
        match request::send(
            client,
            config,
            &operation(
                "POST",
                "/auth/device/token",
                Some(json!({"device_code":&*proof})),
            ),
            None,
        ) {
            Ok(reply) => break reply,
            Err(mut error) => {
                if error.mutation_confirmed == Some(true) {
                    error.detail = Some(Box::new(
                        json!({"cleanup_uncertain":true,"new_session_may_exist":true}),
                    ));
                }
                if cancel.load(Ordering::SeqCst) {
                    let mut cancelled = canceled();
                    cancelled.detail = error.detail;
                    return Err(cancelled);
                }
                match error.code {
                    "authorization_pending" => {}
                    "slow_down" => {
                        interval = (interval + 5).min(600);
                        interval = interval.max(error.retry_after_seconds.unwrap_or(0).min(600));
                    }
                    "rate_limited" => {
                        interval =
                            interval.max(error.retry_after_seconds.unwrap_or(interval).min(600))
                    }
                    "transport_error" => interval = (interval * 2).min(60),
                    _ => return Err(error),
                }
            }
        }
    };
    let credential = issued_credential(&reply, config).map_err(|mut error| {
        error.detail = Some(Box::new(
            json!({"cleanup_uncertain":true,"new_session_may_exist":true}),
        ));
        error
    })?;
    let previous = config.connection.clone();
    let save = (|| {
        let identity = account(
            reply.value.get("account").ok_or_else(Error::protocol)?,
            &[&credential.token, &proof],
        )?;
        let id = identity["id"].as_str().ok_or_else(Error::protocol)?;
        if previous.as_ref().is_some_and(|c| c.account_id != id) && !args.replace {
            return Err(Error::new(
                "replacement_required",
                "Another account is connected to this server; use --replace explicitly.",
                6,
            ));
        }
        if cancel.load(Ordering::SeqCst) {
            return Err(canceled());
        }
        if Instant::now() >= deadline {
            return Err(expired());
        }
        credential::write(config, &args.store, &locator, &credential.token)?;
        if *credential::read(config, &args.store, &locator)? != *credential.token {
            return Err(Error::store("Saved credential read-back failed."));
        }
        if cancel.load(Ordering::SeqCst) {
            return Err(canceled());
        }
        let connection = Connection {
            server: config.server.clone(),
            api_prefix: config.api_prefix.clone(),
            account_id: id.into(),
            store: args.store.clone(),
            locator: locator.clone(),
            cookie_name: credential.cookie_name.clone(),
            expires_at: reply.value["expires_at"]
                .as_str()
                .ok_or_else(Error::protocol)?
                .into(),
        };
        config.save(Some(connection))?;
        Ok(identity)
    })();
    let identity = match save {
        Ok(value) => value,
        Err(error) => {
            // Rename has committed the locator even if its directory fsync failed.
            // Preserve both credentials; deleting the new one would break saved state.
            if config
                .connection
                .as_ref()
                .is_some_and(|connection| connection.locator == locator)
            {
                let mut error = error;
                error.detail = Some(Box::new(
                    json!({"connection_saved":true,"durability_uncertain":true,"previous_credential_retained":previous.is_some(),"cleanup_uncertain":previous.is_some()}),
                ));
                return Err(error);
            }
            return Err(cleanup(
                client,
                config,
                &credential,
                &args.store,
                &locator,
                error,
            ));
        }
    };
    let mut previous_local_cleared = true;
    let mut previous_server_revoked = true;
    if let Some(previous) = previous {
        match credential::read(config, &previous.store, &previous.locator) {
            Ok(token) => {
                let old = Credential {
                    token,
                    cookie_name: previous.cookie_name.clone(),
                    external: false,
                };
                previous_server_revoked = request::send(
                    client,
                    config,
                    &operation("POST", "/auth/logout", None),
                    Some(&old),
                )
                .is_ok();
            }
            Err(_) => previous_server_revoked = false,
        }
        previous_local_cleared =
            credential::remove(config, &previous.store, &previous.locator).is_ok();
    }
    Ok(
        json!({"data":{"server":config.server,"api_prefix":config.api_prefix,"account":identity,"source":args.store,"expires_at":reply.value["expires_at"],"previous_local_cleared":previous_local_cleared,"previous_server_revoked":previous_server_revoked}}),
    )
}

fn logout(config: &mut Config, client: &reqwest::blocking::Client) -> Result<Value> {
    let (credential, remote) = match credential::load(config) {
        Ok(credential) => {
            let remote = request::send(
                client,
                config,
                &operation("POST", "/auth/logout", None),
                Some(&credential),
            );
            (Some(credential), remote)
        }
        // A prior logout may have removed the secret but failed to commit
        // metadata. Idempotent removal verifies the store before clearing it.
        Err(error)
            if config.connection.is_some() && std::env::var_os("BB_SESSION_TOKEN").is_none() =>
        {
            (None, Err(error))
        }
        Err(error) => return Err(error),
    };
    let external = credential.as_ref().is_some_and(|value| value.external);
    let mut local_cleared = false;
    if !external {
        let connection = config.connection.clone().ok_or_else(Error::auth)?;
        // Retain the locator until deletion succeeds so a repaired store can
        // be cleaned up by a later process.
        if let Err(mut error) = credential::remove(config, &connection.store, &connection.locator) {
            error.detail = Some(Box::new(
                json!({"local_cleared":false,"connection_metadata_cleared":false,"server_revoked":remote.is_ok(),"cleanup_uncertain":true}),
            ));
            return Err(error);
        }
        local_cleared = true;
        if let Err(mut error) = config.save(None) {
            error.detail = Some(Box::new(
                json!({"local_cleared":true,"connection_metadata_cleared":config.connection.is_none(),"server_revoked":remote.is_ok(),"cleanup_uncertain":true,"durability_uncertain":config.connection.is_none()}),
            ));
            return Err(error);
        }
    }
    let data = json!({"local_cleared":local_cleared,"connection_metadata_cleared":!external && config.connection.is_none(),"server_revoked":remote.is_ok(),"cleanup_uncertain":remote.is_err(),"source":if external {"environment"}else{"saved"}});
    match remote {
        Ok(_) => Ok(json!({"data":data})),
        Err(mut error) => {
            error.detail = Some(Box::new(data));
            Err(error)
        }
    }
}
