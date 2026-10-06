# Research: BrainBuddy agent CLI

Evidence date: 2026-10-06. Baseline: afaa820ae8f5edcac99764c386ed748d6dca037c. Read-only research lenses examined server authentication and upstream Rust APIs. This is technical research, not implementation evidence.

## Client and dependencies

**Decision:** a standalone Rust package in cli/, blocking requests, a committed Cargo.lock and pinned tested toolchain. Prefer reqwest 0.12.28 with blocking/json/rustls-tls-native-roots, clap 4.6.7, serde 1.0.229, serde_json 1.0.151, keyring 3.6.3, directories 6.0.0, webbrowser 1.2.4, ctrlc 3.5.2 and zeroize 1.9.0. Exact compatible resolved versions are locked during implementation; the workspace has Rust 1.99.0 available. A lower MSRV is not promised without compiling that lockfile.

**Rationale:** one serial command does not need an application async runtime. Clap supplies parsing and scoped command introspection; serde_json supplies bounded projection without jq/JSONPath dependencies. Rustls avoids runtime OpenSSL. Reqwest 0.12 avoids the larger AWS-LC build dependency in 0.13. Native system trust remains enabled.

**Alternatives:** Python adds a runtime dependency; Node adds a runtime/package ecosystem; a Tokio service, plugin framework, TUI, MCP adapter and offline database add no accepted outcome. Rust binaries still require platform-specific builds and OS compatibility; Rust alone does not make one executable universal.

Verified upstream: https://docs.rs/reqwest/0.12.28/reqwest/blocking/struct.ClientBuilder.html and https://docs.rs/clap/4.6.7/clap/struct.Command.html. Explicitly disable redirects and retries; bound both request time and bytes read, including chunked responses.

## Shared authentication

**Decision:** BrainBuddy-owned device authorization following the user journey and polling rules of RFC 8628, while retaining existing opaque-session cookie transport. This is not an OAuth bearer-token server claim. Add the narrow contracts/device-auth.md endpoints and shared-login approval route. Never implement Google/Apple SDK login in bb.

**Rationale:** backend/app/api/auth.py already sets an opaque session cookie; backend/app/services/auth_service.py mints and hashes sessions; authenticated member endpoints already consume them. The CLI can receive its own distinct session via Set-Cookie. The web retains its existing session. Browser approval naturally uses the configured shared login methods and works when the CLI runs over SSH.

**Alternatives:** asking for passwords defeats the requested UX; copying browser cookies exposes a human session; localhost-only callbacks fail headless use; refresh tokens/JWTs introduce another credential lifecycle. No published shared-provider contract was found in fetched branches/PRs; unpushed parallel work may exist. Recheck it before candidate freeze and resolve code conflicts without duplicating Identity ownership.

Verified model: https://www.rfc-editor.org/rfc/rfc8628#section-3.5. Pending continues, slow_down adds five seconds permanently, expiry/denial stops. Timeout slows polling. No embedded client secret.

## Grant durability and revocation races

**Decision:** bounded JSON records beside existing sessions, serialized by an Identity authorization guard: process RLock plus reentrant, stable-file advisory flock. No per-account lock registry. Session mutation methods and CLI grant approval/exchange/purge use the same guard. Keep task/tree request handlers outside it.

**Rationale:** sessions are already JSON, no shared authorization lock exists, and maintenance purge can run in another process. backend/Dockerfile configures uvicorn without multiple workers; Fly mounts a local volume. A file lock covers cooperating processes on that same data root. It does not create cross-machine shared persistence or claim high availability. backend/app/repositories/crt_command.py demonstrates the flock pattern; Identity must own its own lock rather than importing Thinking repositories.

**Alternatives:** process-only memory loses grants on restart and races with maintenance. SQLite grants still need a cross-store lock to cover session files. Moving all Identity persistence to SQLite is a separate migration, unnecessary here.

Consume a grant durably before minting; a crash/lost response requires a new login, never another session from replay. Revalidate the source session and active account under the guard before and after issuance. Deletion markers always reject exchange; no implicit deletion cancellation. Hard purge removes account-linked grants.

## Protected credentials and prompt-free commands

**Decision:** platform credential adapter using macOS Keychain, Windows Credential Manager and Linux Secret Service. Native stores are explicitly enabled; keyring 3.6 without a native feature silently selects a mock backend and is forbidden. Explicit protected-file fallback is supported on Unix; Windows uses Credential Manager or external secret input until owner-only ACL support can be proven.

**Rationale:** keyring 3.6 Secret Service may automatically unlock a locked item and macOS reads may request Keychain interaction. Business-command reads must instead use native noninteractive access/lock checks and fail when inaccessible. Only explicit login may interact with native credential UI. Native persistence must be tested across separate processes.

**Alternatives:** generic get_password alone cannot prove no prompts. Kernel keyring alone is not persistent Secret Service storage. Silent plaintext fallback and Windows readonly flags do not satisfy owner-only protection. Broad keyring 4 cli features do not solve prompt suppression automatically.

Verified adapters: Linux dbus-secret-service4.1.0 with crypto-rust/vendored reuses keyring's backend. Downcast Entry::get_credential to SsCredential/public exact attributes; connect_with_max_prompt_timeout(EncryptionType::Dh,0) suppresses prompts, search_items returns locked/unlocked matches. Reject locked/ambiguous matches and read only unlocked Item::get_secret without unlock. macOS security-framework3.7.0 supplies SecKeychain::disable_user_interaction; retain RAII guard during Entry::get_secret. It is process-wide, so operations stay serial. Windows native Entry::get_secret calls CredReadW without UI. Source APIs: https://docs.rs/dbus-secret-service/4.1.0/dbus_secret_service/struct.SecretService.html, https://docs.rs/keyring/3.6.3/keyring/secret_service/struct.SsCredential.html and https://docs.rs/security-framework/3.7.0/security_framework/os/macos/keychain/struct.SecKeychain.html. Recheck resolved dependencies and native behavior; never fabricate store success.

## Distribution

**Decision:** five native archives, read-only CI builds, checksum manifest bound to the tested source SHA, Unix/PowerShell installers and explicit approved-actor publication after exact-SHA gates.

**Rationale:** Linux architectures use Ubuntu 22.04 build containers/runners for a stated glibc 2.35 baseline; macOS and Windows need their native linker/toolchain. Vendored Secret Service support avoids a runtime libdbus build dependency, but an unlocked session bus/store is still required. OS signing/notarization are excluded from first release, so document any OS launch prompts actually observed.

**Alternatives:** cross-building every target on one Linux runner does not provide native execution evidence. Installer compilation, administrator paths, PATH-file edits and contents-write CI tokens violate scope or existing delivery controls.
