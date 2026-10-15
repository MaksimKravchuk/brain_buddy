//! Adapter tests against a scripted loopback HTTP server (no real provider).

mod deepgram;
mod openai;

pub(crate) mod mock_http {
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};

    pub struct Server {
        pub url: String,
        pub requests: Arc<Mutex<Vec<Vec<u8>>>>,
    }

    pub fn serve(replies: Vec<(u16, &'static str)>) -> Server {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let url = format!("http://{}", listener.local_addr().expect("addr"));
        let requests = Arc::new(Mutex::new(Vec::new()));
        let seen = requests.clone();
        std::thread::spawn(move || {
            for (status, body) in replies {
                let Ok((mut sock, _)) = listener.accept() else {
                    return;
                };
                let mut buf = Vec::new();
                let mut chunk = [0u8; 8192];
                loop {
                    let n = sock.read(&mut chunk).unwrap_or(0);
                    buf.extend_from_slice(&chunk[..n]);
                    if n == 0 || complete(&buf) {
                        break;
                    }
                }
                seen.lock().expect("lock").push(buf);
                let resp = format!(
                    "HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = sock.write_all(resp.as_bytes());
            }
        });
        Server { url, requests }
    }

    fn complete(buf: &[u8]) -> bool {
        let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") else {
            return false;
        };
        let head = String::from_utf8_lossy(&buf[..end]).to_lowercase();
        let len = head
            .lines()
            .find_map(|l| l.strip_prefix("content-length:"))
            .and_then(|v| v.trim().parse::<usize>().ok())
            .unwrap_or(0);
        buf.len() >= end + 4 + len
    }

    pub fn text(raw: &[u8]) -> String {
        String::from_utf8_lossy(raw).into_owned()
    }
}

pub(crate) fn wav(n: usize) -> Vec<u8> {
    let mut a = b"RIFF\0\0\0\0WAVE".to_vec();
    a.resize(n.max(12), 0);
    a
}

use super::*;

#[test]
fn sha256_matches_known_vectors_027_fr_012() {
    assert_eq!(
        sha256_hex(b"abc"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert_eq!(
        sha256_hex(b""),
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
}

#[test]
fn sniffs_containers_and_refuses_unknown_027_fr_012() {
    assert_eq!(audio_metadata(&wav(20)).unwrap().1, "audio/wav");
    assert_eq!(audio_metadata(b"\x1aE\xdf\xa3xx").unwrap().1, "audio/webm");
    assert_eq!(
        audio_metadata(b"\0\0\0\x18ftypmp42").unwrap().1,
        "audio/mp4"
    );
    assert_eq!(audio_metadata(&[0xFF, 0xF1]).unwrap().1, "audio/aac");
    assert_eq!(
        audio_metadata(b"nope").unwrap_err().code,
        "STT_AUDIO_FORMAT_UNSUPPORTED"
    );
}

#[test]
fn cost_cap_is_scaled_by_retry_budget_027_fr_011() {
    let s = SttSettings::new("k".into(), "m", "u");
    // 1 MB * 0.01 * 3 attempts = 0.03
    assert!((s.admit(&vec![1; 1_000_000]).unwrap() - 0.03).abs() < 1e-12);
    // 20 MB * 0.01 * 3 = 0.60 > 0.50
    let e = s.admit(&vec![1; 20_000_000]).unwrap_err();
    assert_eq!((e.code, e.retryable), ("STT_COST_LIMIT_EXCEEDED", false));
    assert_eq!(s.admit(&[]).unwrap_err().code, "STT_AUDIO_MISSING");
}

fn env<'a>(pairs: &'a [(&'a str, &'a str)]) -> impl Fn(&str) -> Option<String> + 'a {
    move |n| {
        pairs
            .iter()
            .find(|(k, _)| *k == n)
            .map(|(_, v)| v.to_string())
    }
}

#[test]
fn missing_key_degrades_role_to_disabled_027_fr_012() {
    let role = |p: &[(&str, &str)], test| SttRole::from_env(env(p), test).unwrap();
    assert!(matches!(role(&[], false), SttRole::Disabled));
    assert!(matches!(
        role(
            &[("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "deepgram")],
            false
        ),
        SttRole::Disabled
    ));
    assert!(matches!(
        role(&[("OPENAI_API_KEY", "k")], false),
        SttRole::OpenAi(_)
    ));
    let dg = [
        ("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "deepgram"),
        ("DEEPGRAM_API_KEY", "k"),
        ("BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_RETRIES", "5"),
    ];
    assert!(matches!(role(&dg, false), SttRole::Deepgram(_)));
    assert!(matches!(role(&[], true), SttRole::Deterministic));
    let prod = [("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "deterministic")];
    assert!(SttRole::from_env(env(&prod), false).is_err());
}
