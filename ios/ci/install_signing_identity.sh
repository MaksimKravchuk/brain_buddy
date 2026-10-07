#!/usr/bin/env bash
# Import the existing development identity; no certificate-account writes.
set -euo pipefail
umask 077

: "${RUNNER_TEMP:?Missing RUNNER_TEMP}"
: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"
: "${BUILD_CERTIFICATE_BASE64:?Missing development certificate secret}"
: "${P12_PASSWORD:?Missing development certificate password secret}"
: "${APPLE_TEAM_ID:?Missing APPLE_TEAM_ID}"
[[ "${APPLE_TEAM_ID}" =~ ^[A-Z0-9]{10}$ ]] || exit 1

keychain="${RUNNER_TEMP}/brainbuddy-development.keychain-db"
certificate="${RUNNER_TEMP}/brainbuddy-development.p12"
public_certificate="${RUNNER_TEMP}/brainbuddy-development.pem"
installed=false
cleanup() {
  rm -f "${certificate}" "${public_certificate}"
  if [ "${installed}" != true ] && [ -f "${keychain}" ]; then
    security delete-keychain "${keychain}" >/dev/null
  fi
}
trap cleanup EXIT

python3 - "${certificate}" <<'PY'
import base64
import os
import sys
from pathlib import Path

Path(sys.argv[1]).write_bytes(
    base64.b64decode(os.environ["BUILD_CERTIFICATE_BASE64"].strip(), validate=True)
)
PY
keychain_password="$(openssl rand -base64 32)"
security create-keychain -p "${keychain_password}" "${keychain}"
security set-keychain-settings -lut 21600 "${keychain}"
security unlock-keychain -p "${keychain_password}" "${keychain}"
security import "${certificate}" -P "${P12_PASSWORD}" \
  -t cert -f pkcs12 -k "${keychain}" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
  -k "${keychain_password}" "${keychain}" >/dev/null

# find-identity reports valid identities with private keys, not chain certificates.
identity="$(security find-identity -v -p codesigning "${keychain}" \
  | awk '/^[[:space:]]*[0-9]+\)/ && /"Apple Development:/ { print $2 }')"
if ! [[ "${identity}" =~ ^[0-9A-Fa-f]{40}$ ]]; then
  echo "::error::The PKCS#12 must contain exactly one valid Apple Development identity with its private key."
  exit 1
fi

# Validate the certificate's signed OU, not just a displayed certificate name.
openssl pkcs12 -in "${certificate}" -clcerts -nokeys \
  -passin env:P12_PASSWORD -out "${public_certificate}" >/dev/null 2>&1
subject="$(openssl x509 -in "${public_certificate}" -noout -subject -nameopt RFC2253,sep_multiline)"
fingerprint="$(openssl x509 -in "${public_certificate}" -noout -fingerprint -sha1 \
  | cut -d= -f2 | tr -d ':' | tr '[:lower:]' '[:upper:]')"
identity="$(printf '%s' "${identity}" | tr '[:lower:]' '[:upper:]')"
if ! printf '%s\n' "${subject}" | grep -Eq "^[[:space:]]*OU=${APPLE_TEAM_ID}$" \
  || [ "${fingerprint}" != "${identity}" ]; then
  echo "::error::The development identity must belong to APPLE_TEAM_ID and match the imported private-key identity."
  exit 1
fi

security list-keychains -d user -s "${keychain}" login.keychain-db
printf 'identity=%s\n' "${identity}" >> "${GITHUB_OUTPUT}"
installed=true
