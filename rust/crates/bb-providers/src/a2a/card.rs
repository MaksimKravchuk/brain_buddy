//! Agent discovery: `GET <addr>/.well-known/agent-card.json`, credential-free.
//! Lenient about shape, strict about meaning: the interface host is validated
//! separately because a card is not a permission slip.

use serde_json::Value;

use super::egress::{
    EgressError, EgressPolicy, Rejection, Resolver, pinned_get, validate_destination,
};

pub const CARD_PATH: &str = "/.well-known/agent-card.json";

pub const A2A_UNREACHABLE: &str = "a2a_unreachable";
pub const A2A_NOT_AN_AGENT: &str = "a2a_not_an_agent";
pub const A2A_NO_SUPPORTED_INTERFACE: &str = "a2a_no_supported_interface";
pub const A2A_PROTOCOL_VERSION_UNSUPPORTED: &str = "a2a_protocol_version_unsupported";

/// A usable card, or a closed failure code.
#[derive(Debug, PartialEq, Eq)]
pub enum CardDiscovery {
    Found {
        name: String,
        interface_url: String,
        protocol_version: String,
    },
    Failed(&'static str),
}

/// Owners paste both an origin and a full card URL; accept either.
pub fn card_url_for(address: &str) -> String {
    let a = address.trim();
    if a.trim_end_matches('/').ends_with(CARD_PATH) {
        a.to_string()
    } else {
        format!("{}{CARD_PATH}", a.trim_end_matches('/'))
    }
}

/// `1.0` or `1.0.<digits>` only.
fn supported_version(v: &str) -> bool {
    v == "1.0"
        || v.strip_prefix("1.0.")
            .is_some_and(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()))
}

fn text<'a>(v: &'a Value, key: &str) -> Option<&'a str> {
    v.get(key).and_then(Value::as_str)
}

async fn interpret(card: &Value, policy: &EgressPolicy, resolver: &Resolver) -> CardDiscovery {
    let Some(name) = text(card, "name").filter(|n| !n.is_empty()) else {
        return CardDiscovery::Failed(A2A_NOT_AN_AGENT);
    };
    let mut interfaces: Vec<&Value> = card
        .get("supportedInterfaces")
        .and_then(Value::as_array)
        .map(|a| a.iter().collect())
        .unwrap_or_default();
    if interfaces.is_empty() && text(card, "url").is_some() {
        interfaces.push(card); // legacy: one transport at the top level
    }
    if interfaces.is_empty() {
        return CardDiscovery::Failed(A2A_NOT_AN_AGENT);
    }
    let (mut jsonrpc, mut wrong_version, mut refused) = (false, false, false);
    for i in interfaces {
        let binding = text(i, "protocolBinding").or_else(|| text(i, "preferredTransport"));
        let (Some(url), true) = (
            text(i, "url").filter(|u| !u.is_empty()),
            binding.is_some_and(|b| b.trim().eq_ignore_ascii_case("JSONRPC")),
        ) else {
            continue;
        };
        jsonrpc = true;
        let version = text(i, "protocolVersion").or_else(|| text(card, "protocolVersion"));
        let Some(version) = version.filter(|v| supported_version(v)) else {
            wrong_version = true;
            continue;
        };
        if validate_destination(url, policy, resolver).await.is_err() {
            refused = true;
            continue;
        }
        return CardDiscovery::Found {
            name: name.chars().take(200).collect(),
            interface_url: url.to_string(),
            protocol_version: version.to_string(),
        };
    }
    // A refused host outranks a version mismatch (Python parity).
    CardDiscovery::Failed(if !jsonrpc || refused || !wrong_version {
        A2A_NO_SUPPORTED_INTERFACE
    } else {
        A2A_PROTOCOL_VERSION_UNSUPPORTED
    })
}

/// Fetches and interprets an agent card. No credential is ever sent.
pub async fn fetch_card(
    address: &str,
    policy: &EgressPolicy,
    resolver: &Resolver,
) -> CardDiscovery {
    let dest = match validate_destination(&card_url_for(address), policy, resolver).await {
        Ok(d) => d,
        Err(r) => return CardDiscovery::Failed(r.code()),
    };
    match pinned_get(&dest, policy).await {
        Ok(resp) if resp.status == 200 => match serde_json::from_slice::<Value>(&resp.body) {
            Ok(card) if card.is_object() => interpret(&card, policy, resolver).await,
            _ => CardDiscovery::Failed(A2A_NOT_AN_AGENT),
        },
        Ok(_) | Err(EgressError::Rejected(Rejection::Invalid)) => {
            CardDiscovery::Failed(A2A_NOT_AN_AGENT)
        }
        Err(EgressError::Rejected(r)) => CardDiscovery::Failed(r.code()),
        Err(EgressError::Deadline | EgressError::Transport) => {
            CardDiscovery::Failed(A2A_UNREACHABLE)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::time::Duration;

    use super::*;

    /// Mock peer: answers every connection with `reply`; returns its port.
    fn peer(reply: String) -> u16 {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        std::thread::spawn(move || {
            for mut s in l.incoming().flatten() {
                let mut buf = [0u8; 2048];
                let _ = s.read(&mut buf);
                let _ = s.write_all(reply.as_bytes());
            }
        });
        port
    }

    fn ok(body: &str) -> String {
        format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    fn policy(max: usize) -> EgressPolicy {
        EgressPolicy {
            timeout: Duration::from_secs(2),
            max_response_bytes: max,
            allow_private: true,
        }
    }

    fn card(url: &str) -> String {
        format!(
            r#"{{"name":"Peer","supportedInterfaces":[{{"url":"{url}","protocolBinding":"JSONRPC","protocolVersion":"1.0"}}]}}"#
        )
    }

    #[test]
    fn t027_fr_014_card_url_accepts_origin_or_full_card_url() {
        assert_eq!(
            card_url_for("https://a.example/"),
            "https://a.example/.well-known/agent-card.json"
        );
        let full = "https://a.example/.well-known/agent-card.json";
        assert_eq!(card_url_for(full), full);
    }

    #[tokio::test]
    async fn t027_fr_014_card_fetch_succeeds_against_a_mock_peer() {
        let port = peer(ok(&card("http://127.0.0.1:9/rpc")));
        let got = fetch_card(
            &format!("http://127.0.0.1:{port}"),
            &policy(64_000),
            &Resolver::System,
        )
        .await;
        assert_eq!(
            got,
            CardDiscovery::Found {
                name: "Peer".into(),
                interface_url: "http://127.0.0.1:9/rpc".into(),
                protocol_version: "1.0".into()
            }
        );
    }

    #[tokio::test]
    async fn t027_fr_014_redirects_and_oversize_bodies_are_refused() {
        let redirect = peer("HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".into());
        let got = fetch_card(
            &format!("http://127.0.0.1:{redirect}"),
            &policy(64_000),
            &Resolver::System,
        )
        .await;
        assert_eq!(
            got,
            CardDiscovery::Failed("destination_redirect_not_allowed")
        );
        let big = peer(ok(&card("http://127.0.0.1:9/rpc")));
        let got = fetch_card(
            &format!("http://127.0.0.1:{big}"),
            &policy(10),
            &Resolver::System,
        )
        .await;
        assert_eq!(got, CardDiscovery::Failed(A2A_NOT_AN_AGENT));
    }

    #[tokio::test]
    async fn t027_fr_014_private_destinations_need_the_opt_in_and_interfaces_are_rechecked() {
        let port = peer(ok(&card("http://10.0.0.9/rpc")));
        let mut p = policy(64_000);
        p.allow_private = false;
        let got = fetch_card(&format!("http://127.0.0.1:{port}"), &p, &Resolver::System).await;
        assert_eq!(
            got,
            CardDiscovery::Failed("destination_network_not_allowed")
        );
        let metadata = peer(ok(&card("http://169.254.169.254/rpc")));
        let got = fetch_card(
            &format!("http://127.0.0.1:{metadata}"),
            &policy(64_000),
            &Resolver::System,
        )
        .await;
        assert_eq!(got, CardDiscovery::Failed(A2A_NO_SUPPORTED_INTERFACE));
        let old = peer(ok(
            r#"{"name":"P","url":"http://127.0.0.1:9/","preferredTransport":"JSONRPC","protocolVersion":"0.3"}"#,
        ));
        let got = fetch_card(
            &format!("http://127.0.0.1:{old}"),
            &policy(64_000),
            &Resolver::System,
        )
        .await;
        assert_eq!(got, CardDiscovery::Failed(A2A_PROTOCOL_VERSION_UNSUPPORTED));
    }
}
