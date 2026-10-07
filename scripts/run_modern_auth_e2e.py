#!/usr/bin/env python3
"""Run real-app modern auth journeys with isolated synthetic transport and TLS."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["npm", "run", "build"], cwd=root / "frontend", check=True)
    with tempfile.TemporaryDirectory(prefix="modern-auth-e2e-") as directory:
        temporary = Path(directory)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        origin = f"https://brainbuddy-e2e.example.com:{port}"
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": os.pathsep.join(
                    (str(root / "backend"), str(root / "backend/tests"))
                ),
                "BRAIN_BUDDY_MODERN_E2E_ORIGIN": origin,
                "BRAIN_BUDDY_MODERN_E2E_DATA_DIR": str(temporary / "data"),
                "BRAIN_BUDDY_MODERN_E2E_CAPTURE_FILE": str(
                    temporary / "captured-mail.jsonl"
                ),
                "BRAIN_BUDDY_MODERN_E2E_PYTHON": sys.executable,
            }
        )
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
                "/CN=brainbuddy-e2e.example.com",
                "-addext",
                "subjectAltName=DNS:brainbuddy-e2e.example.com,IP:127.0.0.1",
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
        # Trust only this generated local fixture certificate; never change
        # production validation, provider TLS, or the process-wide trust store.
        local_tls = ssl.create_default_context(cafile=str(temporary / "cert.pem"))
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=local_tls),
        )
        with (output.parent / "modern-auth-server.log").open("w") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "modern_auth_e2e_app:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--ssl-keyfile",
                    str(temporary / "key.pem"),
                    "--ssl-certfile",
                    str(temporary / "cert.pem"),
                    "--no-access-log",
                ],
                cwd=root / "backend",
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 60
                while True:
                    if server.poll() is not None:
                        raise RuntimeError(
                            "The isolated auth fixture exited; inspect server.log."
                        )
                    try:
                        with opener.open(
                            f"https://127.0.0.1:{port}/health", timeout=1
                        ) as response:
                            if response.status == 200:
                                break
                    except (urllib.error.URLError, OSError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "The isolated auth fixture did not become ready."
                            )
                        time.sleep(0.2)
                arguments = [
                    "npx",
                    "playwright",
                    "test",
                    "--config",
                    "playwright.modern-auth.config.ts",
                ]
                if environment.get("BRAIN_BUDDY_MODERN_E2E_HEADED") == "1":
                    arguments.append("--headed")
                subprocess.run(
                    arguments, cwd=root / "frontend", env=environment, check=True
                )
            finally:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    main()
