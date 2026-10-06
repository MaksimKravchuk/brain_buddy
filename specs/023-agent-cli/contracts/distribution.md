# Distribution contract

## Native artifacts

Version tag bb-v0.1.0, future bb-vVERSION.

| Target | Archive | Runtime |
|---|---|---|
| x86_64-unknown-linux-gnu | bb-VERSION-x86_64-unknown-linux-gnu.tar.gz | glibc≥2.35 |
| aarch64-unknown-linux-gnu | bb-VERSION-aarch64-unknown-linux-gnu.tar.gz | glibc≥2.35 |
| x86_64-apple-darwin | bb-VERSION-x86_64-apple-darwin.tar.gz | macOS15+; native link/run and released-install evidence at15 required for this architecture |
| aarch64-apple-darwin | bb-VERSION-aarch64-apple-darwin.tar.gz | macOS15+; native link/run and released-install evidence at15 required for this architecture |
| x86_64-pc-windows-msvc | bb-VERSION-x86_64-pc-windows-msvc.zip | Windows10/11 x64 |

Archives contain only bb/bb.exe, no absolute/nested/unsafe paths. Five native build/test jobs plus aggregation required in Full CI; skip/failure blocks. contents:read only, no landing/production environment/write token. Pin toolchain/actions/lockfile. Execute version/help/discovery and native credential/installer checks, not compilation alone.

SHA256SUMS has exactly one line per five archive filenames. SOURCE.json binds version/sourceSHA/toolchain/native evidence. Reject missing/extra/mismatched outputs. Release also includes reviewed install.sh/install.ps1. Independent review/QA and required CI cover same exact sourceSHA; authorized main/Fly release and approved actor publication precede actual released installer smoke. No production secrets in metadata.

## One-command installation

Proposed links, usable only after release:

Unix: curl -fsSL https://github.com/MaksimKravchuk/brain_buddy/releases/download/bb-v0.1.0/install.sh | sh -s -- --version 0.1.0

PowerShell: & ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing 'https://github.com/MaksimKravchuk/brain_buddy/releases/download/bb-v0.1.0/install.ps1').Content)) -Version '0.1.0'

Unix --version VERSION/--dir DIRECTORY; PowerShell -Version/-InstallDir. Defaults user-owned $HOME/.local/bin and LocalAppData/BrainBuddy/bin. No admin/compiler/silent profile or PATH edits. Explicit version never changes silently. If latest convenience exposed, resolve one bb-v tag once and pin downloads; repository-wide unrelated latest is not a CLI version.

Detect native OS/architecture; unsupported WindowsARM/refuse ambiguous mapping. HTTPS only; GitHub asset redirects allowed without application/session credentials. Download manifest/archive from same release, exact-one filename match, SHA256 via native tools. Reject duplicate/malformed manifest entries and unsafe archive paths. Extract only expected binary; stage on destination filesystem, verify staged --version, atomically replace. Any failure/interruption preserves old binary and cleans temporary files. Refuse unsafe destination symlinks; Windows in-use replacement fails while preserving old executable. Print destination/version and exact PATH step if needed. Fixture transport must not add a published HTTPS/checksum bypass.

Checksum verifies corruption; HTTPS/GitHub installer execution trusts release authority. No signature/notarization provenance claim.

## Publication boundary

Candidate jobs upload build artifacts only. Explicit helper verifies exact-source CI/review/QA/artifact identity and recorded owner-approved release metadata, publishes as approved actor outside workflows, never alters main/rulesets/deploys Fly. Credentials never enter logs/source/candidate jobs.

ADR-0008 ASK landing needs recorded exact-SHA decision/audited intervention; normal main-triggered deploy verifies same SHA. Configure trusted frontend verification origin; prove OFF rollback/intended cohort exposure/device journey/cleanup. Publish fixed binaries/installers and run actual Linux/macOS15-both-architectures/Windows downloads/version smoke. Missing native/release/production evidence means unfinished feature.
