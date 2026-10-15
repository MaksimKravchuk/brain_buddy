use crate::{Client, Config, LogCollector, Report, TestControl};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

/// A one-purpose fake server: answers the invite and signup calls and
/// records the raw requests it saw.
async fn fake_server() -> (String, tokio::task::JoinHandle<Vec<String>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let base = format!("http://{}", listener.local_addr().expect("addr"));
    let handle = tokio::spawn(async move {
        let mut seen = Vec::new();
        for _ in 0..2 {
            let (mut sock, _) = listener.accept().await.expect("accept");
            let mut buf = vec![0u8; 8192];
            let n = sock.read(&mut buf).await.expect("read");
            let req = String::from_utf8_lossy(&buf[..n]).to_string();
            let (body, cookie) = if req.contains("/invites") {
                (r#"{"codes":["synthetic-code"]}"#, "")
            } else {
                ("{}", "Set-Cookie: bb_session=abc; Path=/\r\n")
            };
            let resp = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n{cookie}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            sock.write_all(resp.as_bytes()).await.expect("write");
            seen.push(req);
        }
        seen
    });
    (base, handle)
}

fn config(base_url: String) -> Config {
    Config {
        base_url,
        server: "unit".into(),
        control_token: "tok".into(),
        epoch: Some(7),
    }
}

#[tokio::test]
async fn t005_owner_factory_uses_control_token_epoch_and_cookie() {
    let (base, server) = fake_server().await;
    let cfg = config(base);
    let client = Client::new(&cfg).expect("client");
    let owner = TestControl::new(&cfg)
        .expect("control")
        .new_owner(&client)
        .await
        .expect("owner");
    let seen = server.await.expect("server");
    assert!(seen[0].to_lowercase().contains("x-test-control-token: tok"));
    assert!(seen[0].starts_with("POST /api/__test__/invites"));
    assert!(seen[1].to_lowercase().contains("x-client-epoch: 7"));
    assert!(seen[1].contains("synthetic-code"));
    assert!(owner.email.ends_with("@conformance.invalid"));
}

#[test]
fn t005_report_is_keyed_by_cap_id_and_fails_if_any_test_fails() {
    let mut r = Report::new("unit");
    r.record(&["CAP-HTTP-001", "CAP-HTTP-002"], "a", true);
    r.record(&["CAP-HTTP-002"], "b", false);
    let v = r.to_json();
    assert_eq!(v["results"]["CAP-HTTP-001"]["status"], "passed");
    assert_eq!(v["results"]["CAP-HTTP-002"]["status"], "failed");
    assert_eq!(
        v["results"]["CAP-HTTP-002"]["tests"]
            .as_array()
            .map(Vec::len),
        Some(2)
    );
}

#[test]
fn t005_027_fr_016_collector_flags_seeded_text_without_echoing_it() {
    let mut c = LogCollector::default();
    let seed = c.seed();
    assert!(c.check("api_request path=/api/tasks status=200").is_ok());
    let log = format!("ok\nbad {seed}\n");
    let err = c.check(&log).expect_err("seed in log").to_string();
    assert!(err.contains("[2]") && !err.contains(&seed));
}
