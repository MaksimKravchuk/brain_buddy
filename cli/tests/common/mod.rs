#![allow(dead_code)] // Shared fixture members vary between integration-test binaries.
use serde_json::Value;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::process::{Command, Output, Stdio};
use std::thread;
use std::time::{Duration, Instant};

pub fn binary() -> std::path::PathBuf {
    std::env::var_os("BB_TEST_CLI_BINARY")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from(env!("CARGO_BIN_EXE_bb")))
}

pub struct Captured {
    pub headers: String,
    pub body: Value,
}

pub fn sequence(
    args: &[&str],
    config: &std::path::Path,
    replies: Vec<(u16, String, Value)>,
) -> (Output, Vec<Captured>) {
    let (mut outputs, captured) = sessions(&[args], config, replies);
    (outputs.remove(0), captured)
}

pub fn sessions(
    actions: &[&[&str]],
    config: &std::path::Path,
    replies: Vec<(u16, String, Value)>,
) -> (Vec<Output>, Vec<Captured>) {
    sessions_with_hook(actions, config, replies, |_| {})
}

pub fn sessions_with_hook(
    actions: &[&[&str]],
    config: &std::path::Path,
    replies: Vec<(u16, String, Value)>,
    mut hook: impl FnMut(usize) + Send + 'static,
) -> (Vec<Output>, Vec<Captured>) {
    sessions_with_hook_and_pid(actions, config, replies, move |index, _pid| hook(index))
}

pub fn sessions_with_hook_and_pid(
    actions: &[&[&str]],
    config: &std::path::Path,
    replies: Vec<(u16, String, Value)>,
    mut hook: impl FnMut(usize, u32) + Send + 'static,
) -> (Vec<Output>, Vec<Captured>) {
    use std::sync::{
        Arc,
        atomic::{AtomicU32, Ordering},
    };
    let pid = Arc::new(AtomicU32::new(0));
    let process_id = pid.clone();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let server = format!("http://{}", listener.local_addr().unwrap());
    listener.set_nonblocking(true).unwrap();
    let fixture_origin = server.clone();
    let worker = thread::spawn(move || {
        let mut captured = vec![];
        for (status, extra_headers, value) in replies {
            let deadline = Instant::now() + Duration::from_secs(12);
            let mut socket = loop {
                match listener.accept() {
                    Ok((s, _)) => break s,
                    Err(e)
                        if e.kind() == std::io::ErrorKind::WouldBlock
                            && Instant::now() < deadline =>
                    {
                        thread::sleep(Duration::from_millis(5))
                    }
                    Err(_) => return captured,
                }
            };
            socket.set_nonblocking(false).unwrap();
            socket
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut bytes = Vec::new();
            let mut buffer = [0; 4096];
            let end = loop {
                let n = socket.read(&mut buffer).unwrap();
                if n == 0 {
                    return captured;
                }
                bytes.extend_from_slice(&buffer[..n]);
                if let Some(i) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    break i + 4;
                }
            };
            let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
            let length = headers
                .lines()
                .find_map(|line| {
                    line.to_lowercase()
                        .strip_prefix("content-length:")
                        .and_then(|v| v.trim().parse::<usize>().ok())
                })
                .unwrap_or(0);
            while bytes.len() - end < length {
                let n = socket.read(&mut buffer).unwrap();
                if n == 0 {
                    break;
                }
                bytes.extend_from_slice(&buffer[..n]);
            }
            captured.push(Captured {
                headers,
                body: serde_json::from_slice(&bytes[end..]).unwrap_or(Value::Null),
            });
            hook(captured.len() - 1, process_id.load(Ordering::SeqCst));
            let body = value.to_string().replace("FIXTURE_ORIGIN", &fixture_origin);
            let response = format!(
                "HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n{extra_headers}\r\n{body}",
                body.len()
            );
            let _ = socket.write_all(response.as_bytes());
        }
        captured
    });
    let result = actions
        .iter()
        .map(|args| {
            let child = Command::new(binary())
                .args(*args)
                .args(["--server", &server])
                .env("BB_CONFIG_DIR", config)
                .env_remove("BB_SESSION_TOKEN")
                .env_remove("BB_SERVER")
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .unwrap();
            pid.store(child.id(), Ordering::SeqCst);
            child.wait_with_output().unwrap()
        })
        .collect();
    (result, worker.join().unwrap())
}

pub fn exchange(
    args: &[&str],
    status: u16,
    extra_headers: &str,
    body: &[u8],
) -> (Output, Captured) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let server = format!("http://{}", listener.local_addr().unwrap());
    listener.set_nonblocking(true).unwrap();
    let response=format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n{extra_headers}\r\n",body.len()).into_bytes();
    let body = body.to_vec();
    let worker = thread::spawn(move || {
        let deadline = Instant::now() + Duration::from_secs(3);
        let mut socket = loop {
            match listener.accept() {
                Ok((s, _)) => break s,
                Err(e)
                    if e.kind() == std::io::ErrorKind::WouldBlock && Instant::now() < deadline =>
                {
                    thread::sleep(Duration::from_millis(5))
                }
                Err(_) => {
                    return Captured {
                        headers: String::new(),
                        body: Value::Null,
                    };
                }
            }
        };
        socket.set_nonblocking(false).unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut bytes = Vec::new();
        let mut buffer = [0; 4096];
        let end = loop {
            let n = socket.read(&mut buffer).unwrap();
            if n == 0 {
                return Captured {
                    headers: String::new(),
                    body: Value::Null,
                };
            }
            bytes.extend_from_slice(&buffer[..n]);
            if let Some(i) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                break i + 4;
            }
        };
        let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
        let length = headers
            .lines()
            .find_map(|line| {
                line.to_lowercase()
                    .strip_prefix("content-length:")
                    .and_then(|v| v.trim().parse::<usize>().ok())
            })
            .unwrap_or(0);
        while bytes.len() - end < length {
            let n = socket.read(&mut buffer).unwrap();
            if n == 0 {
                break;
            }
            bytes.extend_from_slice(&buffer[..n]);
        }
        let request = serde_json::from_slice(&bytes[end..]).unwrap_or(Value::Null);
        let _ = socket.write_all(&response);
        let _ = socket.write_all(&body);
        Captured {
            headers,
            body: request,
        }
    });
    let config = tempfile::tempdir().unwrap();
    let output = Command::new(binary())
        .args(args)
        .args(["--server", &server])
        .env("BB_SESSION_TOKEN", "synthetic-cli-token")
        .env("BB_CONFIG_DIR", config.path())
        .env_remove("BB_SESSION_COOKIE_NAME")
        .output()
        .unwrap();
    (output, worker.join().unwrap())
}
