#!/usr/bin/env python3
"""Set a TestFlight build's "What to Test" text through the App Store Connect API.

Used by .github/workflows/ios.yml right after the upload, so a branch build
shows its branch and commit in the TestFlight app. Standard library plus the
system `openssl` only: this runs while the Admin API key is on disk, and no
third-party package should see it.

The uploaded build takes a few minutes to appear in the API, so the script
polls for it before writing the localization.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = "https://api.appstoreconnect.apple.com/v1"
LOCALE = "en-US"
# Apple caps whatsNew at 4000 characters.
MAX_NOTES = 4000


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_to_raw_signature(der: bytes, size: int = 32) -> bytes:
    """Convert an ECDSA DER signature (what openssl prints) to JOSE's r || s."""
    if len(der) < 8 or der[0] != 0x30:
        raise ValueError("not a DER ECDSA signature")
    index = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    parts = []
    for _ in range(2):
        if der[index] != 0x02:
            raise ValueError("not a DER ECDSA signature")
        length = der[index + 1]
        value = der[index + 2 : index + 2 + length].lstrip(b"\x00")
        if len(value) > size:
            raise ValueError("signature component too long")
        parts.append(value.rjust(size, b"\x00"))
        index += 2 + length
    return parts[0] + parts[1]


def make_token(key_path: str, key_id: str, issuer_id: str, now: int) -> str:
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    claims = {
        "iss": issuer_id,
        "iat": now,
        "exp": now + 15 * 60,
        "aud": "appstoreconnect-v1",
    }
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    der = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", key_path],
        input=signing_input.encode("ascii"),
        capture_output=True,
        check=True,
    ).stdout
    return signing_input + "." + b64url(der_to_raw_signature(der))


class Client:
    def __init__(self, key_path: str, key_id: str, issuer_id: str) -> None:
        self.key_path = key_path
        self.key_id = key_id
        self.issuer_id = issuer_id

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        token = make_token(self.key_path, self.key_id, self.issuer_id, int(time.time()))
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            API + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:  # noqa: S310 - fixed https host
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:500]
            raise RuntimeError(f"{method} {path}: HTTP {error.code}: {detail}") from error
        return json.loads(raw) if raw else None


def build_notes(notes: str) -> str:
    return notes if len(notes) <= MAX_NOTES else notes[: MAX_NOTES - 1] + "…"


def find_build(client: Client, app_id: str, version: str, build: str) -> str | None:
    query = urllib.parse.urlencode(
        {
            "filter[app]": app_id,
            "filter[version]": build,
            "filter[preReleaseVersion.version]": version,
            "limit": "1",
        }
    )
    found = client.request("GET", f"/builds?{query}")["data"]
    return found[0]["id"] if found else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--issuer-id", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--wait-seconds", type=int, default=15 * 60)
    args = parser.parse_args(argv)

    client = Client(args.key, args.key_id, args.issuer_id)
    query = urllib.parse.urlencode({"filter[bundleId]": args.bundle_id, "limit": "1"})
    apps = client.request("GET", f"/apps?{query}")["data"]
    if not apps:
        print(f"::warning::No App Store Connect app for {args.bundle_id}")
        return 1
    app_id = apps[0]["id"]

    deadline = time.monotonic() + args.wait_seconds
    build_id = find_build(client, app_id, args.version, args.build)
    while build_id is None and time.monotonic() < deadline:
        time.sleep(20)
        build_id = find_build(client, app_id, args.version, args.build)
    if build_id is None:
        print(f"::warning::Build {args.version} ({args.build}) did not appear in time; no notes written")
        return 1

    notes = build_notes(args.notes)
    existing = client.request("GET", f"/builds/{build_id}/betaBuildLocalizations")["data"]
    match = next((item for item in existing if item["attributes"].get("locale") == LOCALE), None)
    if match:
        client.request(
            "PATCH",
            f"/betaBuildLocalizations/{match['id']}",
            {"data": {"type": "betaBuildLocalizations", "id": match["id"], "attributes": {"whatsNew": notes}}},
        )
    else:
        client.request(
            "POST",
            "/betaBuildLocalizations",
            {
                "data": {
                    "type": "betaBuildLocalizations",
                    "attributes": {"locale": LOCALE, "whatsNew": notes},
                    "relationships": {"build": {"data": {"type": "builds", "id": build_id}}},
                }
            },
        )
    print(f"What to Test for {args.version} ({args.build}): {notes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
