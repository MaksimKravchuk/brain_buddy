//! Destination-class safety for outbound agent connections. A destination is
//! refused unless every resolved address is public (or governed private with
//! the explicit opt-in, never in production); the request then connects only
//! to those pinned addresses. Redirects are never followed.

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::time::Duration;

use reqwest::{Client, Url, redirect};

/// Extra wall-clock beyond the read timeout; closes drip-feeding peers.
pub const DEADLINE_MARGIN: Duration = Duration::from_secs(5);

/// Closed, log-safe rejection codes (same strings as the Python module).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Rejection {
    Invalid,
    SchemeNotAllowed,
    NetworkNotAllowed,
    Unresolvable,
    RedirectNotAllowed,
}

impl Rejection {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "destination_invalid",
            Self::SchemeNotAllowed => "destination_scheme_not_allowed",
            Self::NetworkNotAllowed => "destination_network_not_allowed",
            Self::Unresolvable => "destination_unresolvable",
            Self::RedirectNotAllowed => "destination_redirect_not_allowed",
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum EgressError {
    Rejected(Rejection),
    /// Contacted, but no complete answer in time.
    Deadline,
    Transport,
}

impl From<Rejection> for EgressError {
    fn from(r: Rejection) -> Self {
        Self::Rejected(r)
    }
}

#[derive(Clone, Debug)]
pub struct EgressPolicy {
    pub timeout: Duration,
    pub max_response_bytes: usize,
    pub allow_private: bool,
}

impl EgressPolicy {
    /// Reads BRAIN_BUDDY_AGENT_CONNECTOR_{TIMEOUT_SECONDS,MAX_RESPONSE_BYTES} and
    /// BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS (`1` only, ignored in production).
    pub fn from_env(production: bool, get: impl Fn(&str) -> Option<String>) -> Self {
        let num = |k: &str| get(k).and_then(|v| v.trim().parse::<f64>().ok());
        let secs = num("BRAIN_BUDDY_AGENT_CONNECTOR_TIMEOUT_SECONDS").filter(|s| *s > 0.0);
        Self {
            timeout: Duration::from_secs_f64(secs.unwrap_or(10.0)),
            max_response_bytes: num("BRAIN_BUDDY_AGENT_CONNECTOR_MAX_RESPONSE_BYTES")
                .map_or(64_000, |b| b.max(0.0) as usize),
            allow_private: !production
                && get("BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS")
                    .is_some_and(|v| v.trim() == "1"),
        }
    }
}

/// Name resolution: the system (hickory) or a fixed answer for tests.
#[derive(Clone, Debug)]
pub enum Resolver {
    System,
    Fixed(Vec<IpAddr>),
}

impl Resolver {
    async fn resolve(&self, host: &str) -> Result<Vec<IpAddr>, Rejection> {
        let found = match self {
            Self::Fixed(a) => a.clone(),
            Self::System => {
                let r = hickory_resolver::TokioResolver::builder_tokio()
                    .and_then(|b| b.build())
                    .map_err(|_| Rejection::Unresolvable)?;
                let l = r
                    .lookup_ip(host)
                    .await
                    .map_err(|_| Rejection::Unresolvable)?;
                l.iter().collect()
            }
        };
        if found.is_empty() {
            Err(Rejection::Unresolvable)
        } else {
            Ok(found)
        }
    }
}

#[derive(Clone, Debug)]
pub struct Destination {
    pub url: Url,
    pub host: String,
    pub port: u16,
    pub addresses: Vec<IpAddr>,
}

#[derive(Debug)]
pub struct Response {
    pub status: u16,
    pub body: Vec<u8>,
}

fn unmap(ip: IpAddr) -> IpAddr {
    match ip {
        IpAddr::V6(v6) => v6.to_ipv4_mapped().map_or(ip, IpAddr::V4),
        v4 => v4,
    }
}

fn v6_unique_local(a: &Ipv6Addr) -> bool {
    a.segments()[0] & 0xfe00 == 0xfc00
}

pub fn is_public(ip: IpAddr) -> bool {
    match unmap(ip) {
        IpAddr::V4(a) => {
            let o = a.octets();
            !(a.is_private()
                || a.is_loopback()
                || a.is_link_local()
                || a.is_multicast()
                || a.is_unspecified()
                || a.is_broadcast()
                || a.is_documentation()
                || o[0] == 0
                || o[0] >= 240
                || (o[0] == 100 && (64..128).contains(&o[1]))
                || (o[0] == 192 && o[1] == 0 && o[2] == 0)
                || (o[0] == 198 && (o[1] & 0xfe) == 18))
        }
        IpAddr::V6(a) => {
            let s = a.segments();
            !(a.is_loopback()
                || a.is_unspecified()
                || a.is_multicast()
                || s[0] & 0xffc0 == 0xfe80
                || v6_unique_local(&a)
                || (s[0] == 0x2001 && s[1] == 0x0db8)
                || (s[0] == 0x0100 && s[1..4] == [0, 0, 0]))
        }
    }
}

/// Addresses policy may opt into: private and loopback, never link-local.
pub fn is_governed_private(ip: IpAddr) -> bool {
    match unmap(ip) {
        IpAddr::V4(a) => (a.is_private() || a.is_loopback()) && !a.is_link_local(),
        IpAddr::V6(a) => a.is_loopback() || v6_unique_local(&a),
    }
}

fn split(raw: &str) -> Result<(Url, String, u16), Rejection> {
    if raw.bytes().any(|b| !(0x21..=0x7e).contains(&b)) || raw.contains(['\\', '#', '?']) {
        return Err(Rejection::Invalid);
    }
    let url = Url::parse(raw).map_err(|_| Rejection::Invalid)?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(Rejection::SchemeNotAllowed);
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(Rejection::Invalid);
    }
    let host = url.host_str().ok_or(Rejection::Invalid)?.to_string();
    // Shorthand numeric hosts (127.1, decimal ints) parse as IPv4 but are not DNS names.
    let authority = raw
        .split_once("//")
        .map_or("", |(_, r)| r.split('/').next().unwrap_or(""));
    let text = authority.rsplit('@').next().unwrap_or("");
    if host.parse::<Ipv4Addr>().is_ok() && !text.starts_with(&host) {
        return Err(Rejection::Invalid);
    }
    if authority.ends_with(':') {
        return Err(Rejection::Invalid);
    }
    let port = url.port_or_known_default().ok_or(Rejection::Invalid)?;
    Ok((url, host.trim_matches(['[', ']']).to_string(), port))
}

/// Checks scheme and network class and pins the addresses we may connect to.
pub async fn validate_destination(
    raw: &str,
    policy: &EgressPolicy,
    resolver: &Resolver,
) -> Result<Destination, Rejection> {
    let (url, host, port) = split(raw)?;
    let addresses = match host.parse::<IpAddr>() {
        Ok(ip) => vec![ip],
        Err(_) => resolver.resolve(&host).await?,
    };
    if !addresses
        .iter()
        .all(|a| is_public(*a) || (policy.allow_private && is_governed_private(*a)))
    {
        return Err(Rejection::NetworkNotAllowed);
    }
    let all_private = addresses.iter().all(|a| is_governed_private(*a));
    if url.scheme() != "https" && !(policy.allow_private && all_private) {
        return Err(Rejection::SchemeNotAllowed);
    }
    Ok(Destination {
        url,
        host,
        port,
        addresses,
    })
}

fn transport(e: reqwest::Error) -> EgressError {
    if e.is_timeout() {
        EgressError::Deadline
    } else {
        EgressError::Transport
    }
}

/// One GET to a validated destination over its pinned addresses: no redirects,
/// no proxy, body capped at `max_response_bytes`, absolute wall-clock deadline.
pub async fn pinned_get(
    dest: &Destination,
    policy: &EgressPolicy,
) -> Result<Response, EgressError> {
    let addrs: Vec<SocketAddr> = dest
        .addresses
        .iter()
        .map(|ip| SocketAddr::new(*ip, dest.port))
        .collect();
    let client = Client::builder()
        .redirect(redirect::Policy::none())
        .no_proxy()
        .timeout(policy.timeout)
        .resolve_to_addrs(&dest.host, &addrs)
        .build()
        .map_err(|_| EgressError::Transport)?;
    let run = async {
        let mut resp = client
            .get(dest.url.clone())
            .header("Accept", "application/json")
            .send()
            .await
            .map_err(transport)?;
        let status = resp.status();
        if status.is_redirection() {
            return Err(Rejection::RedirectNotAllowed.into());
        }
        let encoded = resp
            .headers()
            .get("content-encoding")
            .is_some_and(|v| !v.as_bytes().eq_ignore_ascii_case(b"identity"));
        let mut body = Vec::new();
        while let Some(chunk) = resp.chunk().await.map_err(transport)? {
            body.extend_from_slice(&chunk);
            if encoded || body.len() > policy.max_response_bytes {
                return Err(Rejection::Invalid.into());
            }
        }
        Ok(Response {
            status: status.as_u16(),
            body,
        })
    };
    tokio::time::timeout(policy.timeout + DEADLINE_MARGIN, run)
        .await
        .map_err(|_| EgressError::Deadline)?
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ip(s: &str) -> IpAddr {
        s.parse().unwrap()
    }

    fn policy(allow_private: bool) -> EgressPolicy {
        EgressPolicy {
            timeout: Duration::from_secs(2),
            max_response_bytes: 64_000,
            allow_private,
        }
    }

    #[tokio::test]
    async fn t027_fr_014_private_and_metadata_addresses_are_refused() {
        for a in [
            "10.0.0.1",
            "127.0.0.1",
            "169.254.169.254",
            "::1",
            "::ffff:10.0.0.1",
            "fd00::1",
        ] {
            let url = format!(
                "https://{}/x",
                if a.contains(':') {
                    format!("[{a}]")
                } else {
                    a.into()
                }
            );
            let r = validate_destination(&url, &policy(false), &Resolver::System).await;
            assert_eq!(r.unwrap_err(), Rejection::NetworkNotAllowed, "{a}");
        }
        let hostile = Resolver::Fixed(vec![ip("93.184.216.34"), ip("10.0.0.5")]);
        let r = validate_destination("https://agent.example/", &policy(false), &hostile).await;
        assert_eq!(r.unwrap_err(), Rejection::NetworkNotAllowed);
    }

    #[tokio::test]
    async fn t027_fr_014_private_opt_in_never_covers_link_local_or_public_http() {
        let p = policy(true);
        assert!(
            validate_destination("http://127.0.0.1:8080/", &p, &Resolver::System)
                .await
                .is_ok()
        );
        let md = validate_destination("http://169.254.169.254/", &p, &Resolver::System).await;
        assert_eq!(md.unwrap_err(), Rejection::NetworkNotAllowed);
        let public = Resolver::Fixed(vec![ip("93.184.216.34")]);
        let r = validate_destination("http://agent.example/", &p, &public).await;
        assert_eq!(r.unwrap_err(), Rejection::SchemeNotAllowed);
        let env = |k: &str| (k.ends_with("PRIVATE_DESTINATIONS")).then(|| "1".to_string());
        assert!(EgressPolicy::from_env(false, env).allow_private);
        assert!(!EgressPolicy::from_env(true, env).allow_private);
    }

    #[tokio::test]
    async fn t027_fr_014_malformed_destinations_are_invalid() {
        for u in [
            "https://u:p@h.example/",
            "https://h.example/?q=1",
            "https://h.example/#f",
            "https://127.1/",
            "https://h.example:/",
            "ftp://h.example/",
        ] {
            let r = validate_destination(u, &policy(false), &Resolver::System).await;
            assert!(
                matches!(r, Err(Rejection::Invalid | Rejection::SchemeNotAllowed)),
                "{u}"
            );
        }
    }
}
