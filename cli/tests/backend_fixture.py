"""Disposable real backend for the Rust journey; stdout is private fixture IPC."""
import json
import os
import socket
import threading
import time

import httpx
import uvicorn

from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow

app = create_app()
app.state.container.invite_repo.create(
    Invite(code="synthetic-cli-fixture-invite", created_at=utcnow())
)
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
sock.listen(128)
origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True).start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.05)
with httpx.Client(base_url=origin, timeout=10) as client:
    response = client.post(
        "/api/auth/signup",
        json={"email": "cli-fixture@example.com", "password": "synthetic-fixture-password-024", "invite_code": "synthetic-cli-fixture-invite"},
    )
    response.raise_for_status()
    token = client.cookies.get("brainbuddy_session")
    assert token
print(json.dumps({"server": origin, "token": token}), flush=True)
while True:
    time.sleep(1)
