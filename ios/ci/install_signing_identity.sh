#!/usr/bin/env bash
# Reuse exactly one development identity; never ask Xcode to create it.
set +x
set -euo pipefail
umask 077

: "${RUNNER_TEMP:?}" "${APPLE_TEAM_ID:?}"
: "${IOS_DEVELOPMENT_CERTIFICATE_BASE64:?}" "${IOS_DEVELOPMENT_CERTIFICATE_PASSWORD:?}"
directory="${RUNNER_TEMP}/brainbuddy-signing"
mkdir -p "${directory}"
chmod 700 "${directory}"
bundle="${directory}/development.p12"
certificate="${directory}/development.pem"
keychain="${directory}/signing.keychain-db"
redactions="${directory}/redactions.txt"

finish() {
  status=$?
  rm -f "${bundle}" || status=1
  if [ "${status}" -ne 0 ] && [ -f "${keychain}" ]; then
    security delete-keychain "${keychain}" >/dev/null 2>&1 \
      || echo '::error::Failed to remove the temporary signing keychain.' >&2
  fi
  exit "${status}"
}
trap finish EXIT
fail() { echo "::error::$1" >&2; exit 1; }

[ ! -e "${keychain}" ] || fail 'A temporary signing keychain already exists.'
printf '%s' "${IOS_DEVELOPMENT_CERTIFICATE_BASE64}" | base64 --decode > "${bundle}"
# Count keys inside the protected bundle without retaining/printing plaintext keys.
keys="$(openssl pkcs12 -in "${bundle}" -passin env:IOS_DEVELOPMENT_CERTIFICATE_PASSWORD \
  -nocerts -nodes 2>/dev/null | awk '/^-----BEGIN .*PRIVATE KEY-----$/ {n++} END {print n+0}')"
[ "${keys}" = 1 ] || fail 'Signing bundle must contain exactly one private identity.'
openssl pkcs12 -in "${bundle}" -passin env:IOS_DEVELOPMENT_CERTIFICATE_PASSWORD \
  -clcerts -nokeys -out "${certificate}" 2>/dev/null
leaves="$(awk '/^-----BEGIN CERTIFICATE-----$/ {n++} END {print n+0}' "${certificate}")"
[ "${leaves}" = 1 ] || fail 'Signing bundle must contain exactly one leaf certificate.'
subject="$(openssl x509 -in "${certificate}" -subject -noout -nameopt sep_multiline,sname)"
team="$(printf '%s\n' "${subject}" | sed -n 's/^ *OU=//p')"
[ "${team}" = "${APPLE_TEAM_ID}" ] || fail 'Development certificate belongs to another team.'
fingerprint="$(openssl x509 -in "${certificate}" -fingerprint -sha1 -noout | cut -d= -f2 | tr -d ':')"
printf '%s\n' "${subject}" | sed -En 's/^ *(CN|OU|O|UID)=//p' > "${redactions}"
printf '%s\n' "${fingerprint}" >> "${redactions}"
while IFS= read -r value; do
  [ -z "${value}" ] || printf '::add-mask::%s\n' "${value}"
done < "${redactions}"

password="$(openssl rand -hex 32)"
printf '::add-mask::%s\n' "${password}"
security create-keychain -p "${password}" "${keychain}"
security set-keychain-settings -lut 21600 "${keychain}"
security unlock-keychain -p "${password}" "${keychain}"
security import "${bundle}" -P "${IOS_DEVELOPMENT_CERTIFICATE_PASSWORD}" \
  -k "${keychain}" -T /usr/bin/codesign -T /usr/bin/security >/dev/null
security set-key-partition-list -S apple-tool:,apple: -s -k "${password}" "${keychain}" >/dev/null
identities="$(security find-identity -v -p codesigning "${keychain}")"
printf '%s\n' "${identities}" | grep -F "${fingerprint}" \
  | grep -q '"Apple Development:' \
  || fail 'No valid trusted Apple Development identity matches the configured certificate.'
# Bash 3.2 on macOS: preserve the existing quoted search-list entries.
existing="$(security list-keychains -d user)"
search_list=()
while IFS= read -r entry; do
  entry="${entry#*\"}"; entry="${entry%\"*}"
  [ -z "${entry}" ] || search_list+=("${entry}")
done <<< "${existing}"
security list-keychains -d user -s "${keychain}" "${search_list[@]}"
echo 'Signing identity installed; one configured development certificate is valid.'
