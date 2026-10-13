//! Shared host side for the tests that run the real backend: the process, a
//! blocking HTTP/1.1 client holding the session cookie (the credential the crate
//! never sees), and the `Transport` port over it.
#![allow(dead_code)]

use bb_client::{Cancellation, HttpRequest, HttpResponse, Method, Transport, TransportFailure};
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant as Wall};

const DEFAULT_PYTHON: &str = "/tmp/bb-pr31-venv/bin/python";

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Verb {
    Get,
    Post,
    Patch,
    Delete,
}

impl From<Method> for Verb {
    fn from(method: Method) -> Self {
        match method {
            Method::Get => Self::Get,
            Method::Post => Self::Post,
        }
    }
}

pub struct Backend {
    child: Child,
    pub addr: SocketAddr,
    pub owner: String,
    pub cookie: String,
    pub data_dir: PathBuf,
    pub db_path: PathBuf,
    python: PathBuf,
    backend_dir: PathBuf,
}

impl Drop for Backend {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn python() -> Option<PathBuf> {
    let configured = std::env::var_os("BB_BACKEND_PYTHON").map(PathBuf::from);
    let python = configured.unwrap_or_else(|| PathBuf::from(DEFAULT_PYTHON));
    python.exists().then_some(python)
}

/// Starts the real backend, or says why it cannot (a failure only when CI sets
/// `BB_REQUIRE_BACKEND=1`).
pub fn start(name: &str) -> Option<Backend> {
    start_with(name, None)
}

/// [`start`] with `BB_E2E_PAGE_LIMITS="hard,target,transfer_page"` for the server.
pub fn start_with(name: &str, page_limits: Option<&str>) -> Option<Backend> {
    let Some(python) = python() else {
        let required = std::env::var("BB_REQUIRE_BACKEND").is_ok_and(|value| value == "1");
        assert!(
            !required,
            "BB_REQUIRE_BACKEND=1 but no backend interpreter: set BB_BACKEND_PYTHON"
        );
        eprintln!(
            "SKIPPED {name}: no backend interpreter at {DEFAULT_PYTHON} and BB_BACKEND_PYTHON is \
             unset; the real backend was not exercised"
        );
        return None;
    };
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    let backend_dir = manifest.join("../../../backend").canonicalize().unwrap();
    let script = manifest.join("tests/support/sse_backend.py");
    let scratch = std::env::temp_dir().join(format!("bb-e2e-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch).unwrap();
    let port = TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port();
    let mut child = Command::new(&python)
        .arg(&script)
        .arg(scratch.join("data"))
        .arg(port.to_string())
        .current_dir(&backend_dir)
        .env("PYTHONPATH", &backend_dir)
        .envs(page_limits.map(|limits| ("BB_E2E_PAGE_LIMITS", limits)))
        .stdout(Stdio::piped())
        .stderr(std::fs::File::create(scratch.join("backend.log")).unwrap())
        .spawn()
        .expect("start the backend");
    let stdout = child.stdout.take().unwrap();
    let (sender, receiver) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if line.starts_with('{') {
                let _ = sender.send(line);
            }
        }
    });
    let info: Value = serde_json::from_str(
        &receiver
            .recv_timeout(Duration::from_secs(120))
            .unwrap_or_else(|_| {
                panic!(
                    "the backend never announced itself; see {}",
                    scratch.join("backend.log").display()
                )
            }),
    )
    .unwrap();
    let addr: SocketAddr = format!("127.0.0.1:{port}").parse().unwrap();
    let backend = Backend {
        child,
        addr,
        owner: info["owner"].as_str().unwrap().to_string(),
        cookie: info["cookie"].as_str().unwrap().to_string(),
        data_dir: PathBuf::from(info["data_dir"].as_str().unwrap()),
        db_path: PathBuf::from(info["db_path"].as_str().unwrap()),
        python,
        backend_dir,
    };
    let deadline = Wall::now() + Duration::from_secs(120);
    while Wall::now() < deadline {
        let health = request(addr, "", Verb::Get, "/health", None, Duration::from_secs(2));
        if health.is_ok_and(|response| response.status == 200) {
            return Some(backend);
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    panic!("the backend never became healthy");
}

impl Backend {
    /// The web / REST side: JSON in, `(status, JSON)` out, as the signed-in owner.
    pub fn rest(&self, method: Verb, path: &str, body: Option<&Value>) -> (u16, Value) {
        self.web().rest(method, path, body)
    }

    /// A cloneable, thread-safe REST client (for a hook that runs mid-request).
    pub fn web(&self) -> Web {
        Web {
            addr: self.addr,
            cookie: self.cookie.clone(),
        }
    }

    /// Runs Python in the backend's environment (the one sanctioned way to reach
    /// server internals a test needs: shrinking a limit, restoring a generation).
    pub fn python(&self, code: &str) -> String {
        let done = Command::new(&self.python)
            .args(["-c", code])
            .current_dir(&self.backend_dir)
            .env("PYTHONPATH", &self.backend_dir)
            .env("BRAIN_BUDDY_DATA_DIR", &self.data_dir)
            .env("BRAIN_BUDDY_ENV", "test")
            .output()
            .expect("run python");
        assert!(
            done.status.success(),
            "python failed: {}",
            String::from_utf8_lossy(&done.stderr)
        );
        String::from_utf8_lossy(&done.stdout).trim().to_string()
    }

    pub fn transport(&self) -> HttpTransport {
        HttpTransport {
            addr: self.addr,
            cookie: self.cookie.clone(),
        }
    }
}

#[derive(Clone)]
pub struct Web {
    addr: SocketAddr,
    cookie: String,
}

impl Web {
    pub fn rest(&self, method: Verb, path: &str, body: Option<&Value>) -> (u16, Value) {
        static KEYS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
        let key = KEYS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let bytes = body.map(|value| value.to_string().into_bytes());
        // Writes carry a fresh idempotency key, as the web client does.
        let cookie = format!(
            "{}\r\nIdempotency-Key: e2e-{}-{key}",
            self.cookie,
            std::process::id()
        );
        let response = request(
            self.addr,
            &cookie,
            method,
            path,
            bytes,
            Duration::from_secs(60),
        )
        .expect("a REST answer");
        let value = serde_json::from_slice(&response.body).unwrap_or(Value::Null);
        (response.status, value)
    }
}

/// The OS adapter's `Transport`: it adds the cookie and performs the call.
pub struct HttpTransport {
    addr: SocketAddr,
    cookie: String,
}

impl Transport for HttpTransport {
    fn send(
        &self,
        http: &HttpRequest,
        cancel: &Cancellation<'_>,
    ) -> Result<HttpResponse, TransportFailure> {
        if cancel.is_cancelled() {
            return Err(TransportFailure::Cancelled);
        }
        request(
            self.addr,
            &self.cookie,
            http.method.into(),
            &http.path,
            http.body.clone(),
            http.timeout,
        )
    }
}

fn request(
    addr: SocketAddr,
    cookie: &str,
    method: Verb,
    path: &str,
    body: Option<Vec<u8>>,
    timeout: Duration,
) -> Result<HttpResponse, TransportFailure> {
    let mut socket =
        TcpStream::connect_timeout(&addr, timeout).map_err(|_| TransportFailure::Connection)?;
    socket.set_read_timeout(Some(timeout)).unwrap();
    let verb = match method {
        Verb::Get => "GET",
        Verb::Post => "POST",
        Verb::Patch => "PATCH",
        Verb::Delete => "DELETE",
    };
    let mut head = format!(
        "{verb} {path} HTTP/1.1\r\nHost: {addr}\r\nCookie: {cookie}\r\nAccept: application/json\r\n\
         Connection: close\r\n"
    );
    if let Some(body) = &body {
        head.push_str(&format!(
            "Content-Type: application/json\r\nContent-Length: {}\r\n",
            body.len()
        ));
    }
    head.push_str("\r\n");
    socket
        .write_all(head.as_bytes())
        .and_then(|()| match &body {
            Some(body) => socket.write_all(body),
            None => Ok(()),
        })
        .map_err(|_| TransportFailure::Connection)?;
    let mut raw = Vec::new();
    socket.read_to_end(&mut raw).map_err(|error| {
        if matches!(
            error.kind(),
            std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
        ) {
            TransportFailure::Timeout
        } else {
            TransportFailure::Connection
        }
    })?;
    let split = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or(TransportFailure::Connection)?;
    let head = String::from_utf8_lossy(&raw[..split]).to_string();
    let mut lines = head.lines();
    let status: u16 = lines
        .next()
        .and_then(|line| line.split(' ').nth(1))
        .and_then(|code| code.parse().ok())
        .ok_or(TransportFailure::Connection)?;
    let mut chunked = false;
    let mut retry_after = None;
    for line in lines {
        let lower = line.to_ascii_lowercase();
        chunked |= lower.starts_with("transfer-encoding:") && lower.contains("chunked");
        if let Some(value) = lower.strip_prefix("retry-after:") {
            retry_after = value.trim().parse().ok().map(Duration::from_secs);
        }
    }
    let rest = &raw[split + 4..];
    let body = if chunked {
        dechunk(rest)
    } else {
        rest.to_vec()
    };
    Ok(HttpResponse {
        status,
        retry_after,
        body,
    })
}

fn dechunk(mut raw: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    while let Some(at) = raw.windows(2).position(|window| window == b"\r\n") {
        let size =
            usize::from_str_radix(String::from_utf8_lossy(&raw[..at]).trim(), 16).unwrap_or(0);
        if size == 0 {
            break;
        }
        out.extend_from_slice(&raw[at + 2..at + 2 + size]);
        raw = &raw[at + 2 + size + 2..];
    }
    out
}
