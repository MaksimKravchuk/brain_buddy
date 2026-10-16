#!/usr/bin/env python3
"""Run the modern-auth browser journeys against any server by base URL.

The product server is the unmodified application started with
``BRAIN_BUDDY_ENV=test`` (or an already running server named by
``BRAIN_BUDDY_MODERN_E2E_BACKEND_URL``, which must carry the same
``BRAIN_BUDDY_AUTH_*`` settings printed by ``server_environment``). Identity and
SMTP boundaries are scripted only through ``/api/__test__/providers/{kind}`` and
``/api/__test__/mail``; accounts are seeded only through public routes plus the
test control invite mint. A small TLS front serves the built frontend and
forwards ``/api`` and ``/health`` to the server, because the auth cookies and
callbacks require an HTTPS origin.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import http.server
import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

FIXTURE_HOST = "brainbuddy-e2e.example.com"
PASSWORD = "E2E-modern-safe-password-123"
GOOGLE_CLIENT_ID = "modern-e2e.apps.googleusercontent.com"
APPLE_SERVICES_ID = "com.example.modern-e2e.web"
PASSWORD_ACCOUNTS = (
    "legacy-modern-e2e@gmail.com",
    "stale-modern-e2e@example.com",
    "other-modern-e2e@example.com",
)
RECOVERY_ACCOUNT = "recovery-modern-e2e@example.com"
_HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "te"}


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def server_environment(origin: str, data_dir: Path, token: str) -> dict[str, str]:
    """Settings the real modern-auth validator needs; no code path is patched."""
    apple_key = subprocess.run(
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    # Re-encode as PKCS#8, the format the Apple client secret signer loads.
    apple_key = subprocess.run(
        ["openssl", "pkcs8", "-topk8", "-nocrypt"],
        input=apple_key,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        "BRAIN_BUDDY_ENV": "test",
        "BRAIN_BUDDY_TEST_CONTROL_TOKEN": token,
        "BRAIN_BUDDY_DATA_DIR": str(data_dir),
        "BRAIN_BUDDY_AUTH_PUBLIC_ORIGIN": origin,
        "BRAIN_BUDDY_AUTH_API_ORIGIN": origin,
        "BRAIN_BUDDY_AUTH_CURRENT_KEY_ID": "e2e",
        "BRAIN_BUDDY_AUTH_KEYRING": json.dumps(
            {"e2e": base64.b64encode(os.urandom(32)).decode("ascii")}
        ),
        "BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_SECRET": "synthetic-google-client-secret",
        "BRAIN_BUDDY_AUTH_APPLE_PRIVATE_KEY": apple_key,
        "BRAIN_BUDDY_AUTH_APPLE_KEY_ID": "KEY1234567",
        "BRAIN_BUDDY_AUTH_APPLE_TEAM_ID": "TEAM123456",
        "BRAIN_BUDDY_AUTH_APPLE_SERVICES_ID": APPLE_SERVICES_ID,
        "BRAIN_BUDDY_AUTH_APPLE_NATIVE_APP_ID": "",
        "BRAIN_BUDDY_AUTH_SMTP_HOST": "smtp.example.com",
        "BRAIN_BUDDY_AUTH_SMTP_SENDER": "signin@example.com",
        "BRAIN_BUDDY_AUTH_SMTP_USERNAME": "synthetic",
        "BRAIN_BUDDY_AUTH_SMTP_PASSWORD": "synthetic",
        "BRAIN_BUDDY_AUTH_SMTP_PORT": "587",
        "BRAIN_BUDDY_AUTH_SMTP_TLS": "starttls",
        "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS": "",
        "BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST": "1",
    }


def make_front(
    dist: Path, backend: str, certificate: Path, key: Path, port: int
) -> http.server.ThreadingHTTPServer:
    """Serve the built frontend over TLS and forward API traffic unchanged."""
    host, backend_port = backend.rsplit("//", 1)[1].split(":")

    class Front(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: object) -> None:
            return

        def _forward(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() not in _HOP_BY_HOP
            }
            headers["X-Forwarded-Proto"] = "https"
            upstream = http.client.HTTPConnection(host, int(backend_port), timeout=60)
            try:
                upstream.request(self.command, self.path, body=body, headers=headers)
                reply = upstream.getresponse()
                payload = reply.read()
                self.send_response(reply.status)
                for name, value in reply.getheaders():
                    if name.lower() not in _HOP_BY_HOP | {"content-length"}:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            finally:
                upstream.close()

        def _static(self) -> None:
            relative = self.path.split("?", 1)[0].lstrip("/")
            target = (dist / relative).resolve()
            if not relative or not target.is_file() or dist not in target.parents:
                target = dist / "index.html"
            payload = target.read_bytes()
            kind = {
                ".js": "text/javascript",
                ".css": "text/css",
                ".html": "text/html",
                ".svg": "image/svg+xml",
                ".json": "application/json",
                ".woff2": "font/woff2",
            }.get(target.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _handle(self) -> None:
            if self.path.startswith(("/api/", "/health")) or self.path == "/api":
                self._forward()
            else:
                self._static()

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _handle

    front = http.server.ThreadingHTTPServer(("127.0.0.1", port), Front)
    front.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    front.socket = context.wrap_socket(front.socket, server_side=True)
    threading.Thread(target=front.serve_forever, daemon=True).start()
    return front


class Api:
    """JSON calls to the server; the public origin is sent as the browser would."""

    def __init__(self, base: str, origin: str, token: str) -> None:
        self.base, self.origin, self.token = base, origin, token
        self.cookie = ""

    def call(
        self, method: str, path: str, body: object | None = None, control: bool = False
    ) -> tuple[int, object]:
        headers = {"Content-Type": "application/json", "Origin": self.origin}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if control:
            headers["X-Test-Control-Token"] = self.token
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                for value in response.headers.get_all("Set-Cookie") or []:
                    self.cookie = value.split(";", 1)[0]
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            raw = error.read()
            return error.code, (json.loads(raw) if raw else None)

    def mailed_code(self, email: str, purpose: str) -> str:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            _, document = self.call("GET", "/api/__test__/mail", control=True)
            messages = [
                m
                for m in document["messages"]  # type: ignore[index]
                if m["recipient"] == email and m["purpose"] == purpose
            ]
            if messages:
                return str(messages[-1]["code"])
            time.sleep(0.2)
        raise RuntimeError(f"No {purpose} mail was captured for {email}.")


def token43() -> str:
    return secrets.token_urlsafe(32)[:43].ljust(43, "A")


def seed(base: str, origin: str, token: str) -> None:
    """Create the four password owners through public routes only."""
    admin = Api(base, origin, token)
    for email in (*PASSWORD_ACCOUNTS, RECOVERY_ACCOUNT):
        _, codes = admin.call("POST", "/api/__test__/invites", {"count": 1}, True)
        owner = Api(base, origin, token)
        status, me = owner.call(
            "POST",
            "/api/auth/signup",
            {
                "email": email,
                "password": PASSWORD,
                "invite_code": codes["codes"][0],  # type: ignore[index]
            },
        )
        if status != 201:
            raise RuntimeError(f"Seeding {email} failed with HTTP {status}.")
        if email == RECOVERY_ACCOUNT:
            verify_mailbox(owner, email, me["id"])  # type: ignore[index]
    # The mailbox send above has a 60 s per-address cooldown; wait it out so the
    # suite's own recovery send for this mailbox is not held back. The server
    # clock is deliberately not moved: Apple lifecycle timestamps compare the
    # server clock with the scripted assertion's issue time.
    time.sleep(61)


def verify_mailbox(owner: Api, email: str, account_id: str) -> None:
    """Verify the signed-up owner's address by the public email-proof route."""
    status, proof = owner.call(
        "POST",
        "/api/auth/confirm/password",
        {
            "current_password": PASSWORD,
            "action": "verify_email",
            "expected_account_id": account_id,
        },
    )
    if status != 200:
        raise RuntimeError(f"Seeding password proof failed with HTTP {status}.")
    verifier = token43()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    status, started = owner.call(
        "POST",
        "/api/auth/email/request",
        {
            "email": email,
            "purpose": "verify_email",
            "client_challenge": challenge.rstrip(b"=").decode(),
            "client": "web",
            "expected_account_id": account_id,
            "action": "verify_email",
            "recent_proof": proof["recent_proof"],  # type: ignore[index]
        },
    )
    if status != 202:
        raise RuntimeError(f"Seeding mailbox request failed: {status} {started}.")
    status, _ = owner.call(
        "POST",
        "/api/auth/email/verify",
        {
            "challenge_id": started["challenge_id"],  # type: ignore[index]
            "client_verifier": verifier,
            "code": owner.mailed_code(email, "verify_email"),
            "recent_proof": proof["recent_proof"],  # type: ignore[index]
        },
    )
    if status != 200:
        raise RuntimeError(f"Seeding mailbox verify failed with HTTP {status}.")


def wait_ready(url: str, process: subprocess.Popen[bytes] | None) -> None:
    deadline = time.monotonic() + 90
    while True:
        if process is not None and process.poll() is not None:
            raise RuntimeError("The server exited; inspect modern-auth-server.log.")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            if time.monotonic() >= deadline:
                raise RuntimeError("The server did not become ready.") from None
            time.sleep(0.2)


def dump_diagnostics(
    backend: str, token: str, log_path: str, results: Path | None = None
) -> None:
    """Print what a failed run needs to be diagnosed from the job log alone.

    CI artifacts are not always reachable, so the failing page's ARIA snapshot
    (Playwright's ``error-context.md``) and every non-2xx request line are
    printed here rather than only the tail, which covers just the last tests.
    """
    if results is not None:
        for context in sorted(results.glob("*/error-context.md")):
            print(f"--- {context.parent.name}/error-context.md ---", flush=True)
            print(context.read_text(errors="replace")[:6000], flush=True)
    print("--- modern-auth server log (tail) ---", flush=True)
    try:
        lines = Path(log_path).read_text(errors="replace").splitlines()
        requests = [line for line in lines if "api_request" in line]
        rejected = [line for line in requests if " status=2" not in line]
        print("--- non-2xx requests ---\n" + "\n".join(rejected[-300:]), flush=True)
        # Request lines are enough to order the auth journey; keep the rest short.
        relevant = [line for line in requests if "/auth/" in line]
        print("\n".join(relevant[-250:] + ["..."] + lines[-60:]), flush=True)
    except OSError as error:
        print(f"unreadable: {error}", flush=True)
    for kind in ("identity", "smtp"):
        request = urllib.request.Request(
            f"{backend}/api/__test__/providers/{kind}/calls",
            headers={"X-Test-Control-Token": token},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                print(
                    f"--- {kind} call ledger ---\n{response.read().decode()}",
                    flush=True,
                )
        except (urllib.error.URLError, OSError) as error:
            print(f"--- {kind} call ledger unavailable: {error}", flush=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["npm", "run", "build"], cwd=root / "frontend", check=True)
    front_port = int(os.environ.get("BRAIN_BUDDY_MODERN_E2E_PORT") or free_port())
    origin = f"https://{FIXTURE_HOST}:{front_port}"
    token = os.environ.get("BRAIN_BUDDY_TEST_CONTROL_TOKEN") or secrets.token_hex(16)
    external = os.environ.get("BRAIN_BUDDY_MODERN_E2E_BACKEND_URL")
    with tempfile.TemporaryDirectory(prefix="modern-auth-e2e-") as directory:
        temporary = Path(directory)
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(temporary / "key.pem"),
                "-out",
                str(temporary / "cert.pem"),
                "-days",
                "1",
                "-subj",
                f"/CN={FIXTURE_HOST}",
                "-addext",
                f"subjectAltName=DNS:{FIXTURE_HOST},IP:127.0.0.1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        output = root / "frontend/test-results/playwright-modern-auth"
        output.mkdir(parents=True, exist_ok=True)
        allure = root / "frontend/allure-results/playwright"
        allure.mkdir(parents=True, exist_ok=True)
        marker = allure / ".run-started-at"
        if not marker.exists():
            marker.touch()
        process: subprocess.Popen[bytes] | None = None
        front: http.server.ThreadingHTTPServer | None = None
        with (output.parent / "modern-auth-server.log").open("w") as log:
            try:
                if external:
                    backend = external.rstrip("/")
                else:
                    backend_port = int(
                        os.environ.get("BRAIN_BUDDY_MODERN_E2E_BACKEND_PORT")
                        or free_port()
                    )
                    backend = f"http://127.0.0.1:{backend_port}"
                    environment = os.environ.copy()
                    environment.update(
                        server_environment(origin, temporary / "data", token)
                    )
                    environment["PYTHONDONTWRITEBYTECODE"] = "1"
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(backend_port),
                            "--no-access-log",
                        ],
                        cwd=root / "backend",
                        env=environment,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                wait_ready(backend, process)
                front = make_front(
                    root / "frontend/dist",
                    backend,
                    temporary / "cert.pem",
                    temporary / "key.pem",
                    front_port,
                )
                seed(backend, origin, token)
                arguments = [
                    "npx",
                    "playwright",
                    "test",
                    "--config",
                    "playwright.modern-auth.config.ts",
                ]
                environment = os.environ.copy()
                environment.update(
                    {
                        "BRAIN_BUDDY_MODERN_E2E_ORIGIN": origin,
                        "BRAIN_BUDDY_MODERN_E2E_CONTROL_URL": backend,
                        "BRAIN_BUDDY_TEST_CONTROL_TOKEN": token,
                    }
                )
                if process is not None:
                    # frontend/tests/e2e/gtdHelpers.ts (account.spec.ts) still
                    # mints invites with the Python CLI until spec 027 PR-12
                    # moves it to the test control API.
                    environment["BRAIN_BUDDY_MODERN_E2E_DATA_DIR"] = str(
                        temporary / "data"
                    )
                    environment["BRAIN_BUDDY_MODERN_E2E_PYTHON"] = sys.executable
                if environment.get("BRAIN_BUDDY_MODERN_E2E_HEADED") == "1":
                    arguments.append("--headed")
                try:
                    subprocess.run(
                        arguments, cwd=root / "frontend", env=environment, check=True
                    )
                except subprocess.CalledProcessError:
                    dump_diagnostics(backend, token, log.name, output)
                    raise
            finally:
                if front is not None:
                    front.shutdown()
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
