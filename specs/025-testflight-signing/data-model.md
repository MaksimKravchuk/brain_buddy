# Data model: N/A

No product persistence changes. The existing GitHub `testflight` environment
owns two additional encrypted secrets: `IOS_DEVELOPMENT_CERTIFICATE_BASE64` and
`IOS_DEVELOPMENT_CERTIFICATE_PASSWORD`. GitHub exposes them only to the upload job.
Decoded `.p12` has mode 0600 and is removed on every installer exit. The public
certificate and its protected redaction map remain temporarily for archive
certificate comparison and log sanitization, then are removed by job cleanup.
A failed installer attempts removal of its keychain; always-run cleanup treats
never-created/already-deleted keychains as success, and verifies all targets absent.

These are controller-side operational credentials, outside BrainBuddy user
account purge and excluded from account export. Retain only while the signing
identity is active; overwrite both on rotation, remove both on retirement, and
on suspected compromise revoke only that identity with owner authorization,
replace/remove both secrets, and audit affected workflow runs. Reverting code
or deleting secrets alone cannot invalidate an already disclosed private key.

Keep the downloaded public certificate outside the repository as the owner's
operator record, linked privately to the active environment secret and portal
identity. Recover its serial/fingerprint and expiry to precisely match the
affected certificate before any owner-authorized revocation. No private key,
signer identifier or personal filesystem path enters versioned evidence.
