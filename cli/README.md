# BrainBuddy CLI (`bb`)

`bb` uses the existing BrainBuddy JSON API and account sessions. It is intended for terminals and AI agents: compact JSON, bounded pages, explicit revisions and request keys, no prompts during business commands, and offline command discovery.

The source is in development. Release URLs below become usable after the reviewed `bb-v0.1.0` release is published; browser login also requires the shared Identity release and server `cli_auth` activation. Building this branch does not activate server login.

## Installation

Linux x64/ARM64 requires glibc 2.35 or later; macOS x64/ARM64 requires macOS15 or later. Windows supports x64 Windows10/11; ARM64 is excluded from this release. Native binaries need no compiler or administrator access. Checksums detect archive corruption; installers trust the HTTPS GitHub release authority. OS signing/notarization and automatic updates are outside this release.

```sh
curl -fsSL https://github.com/MaksimKravchuk/brain_buddy/releases/download/bb-v0.1.0/install.sh | sh -s -- --version 0.1.0
```

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing 'https://github.com/MaksimKravchuk/brain_buddy/releases/download/bb-v0.1.0/install.ps1').Content)) -Version '0.1.0'
```

Unix installs into `$HOME/.local/bin`; Windows uses `%LOCALAPPDATA%\BrainBuddy\bin`. Set `--dir DIRECTORY` or `-InstallDir DIRECTORY` to choose another directory you own. The installer stages downloads on the destination filesystem, checks the five-entry checksum manifest and archive membership, runs the selected version, then replaces the old executable. Integrity, unsupported-machine and download failures preserve the old binary. PATH files are never edited; the installer prints the required PATH step.

For development, install the pinned Rust1.99.0 toolchain, then run `cd cli && cargo build --locked --release`. The output is `target/release/bb` (`bb.exe` on Windows). Linux builds also require a C compiler/pkg-config for the vendored Secret Service adapter.

## Connect once

```sh
bb auth login --server https://YOUR-BRAINBUDDY-ORIGIN
# SSH / remote terminal:
bb auth login --server https://YOUR-BRAINBUDDY-ORIGIN --no-browser
bb auth status
bb auth logout
```

Login opens the server-provided `/cli/authorize` page and displays a short code. Sign in using BrainBuddy’s shared account entry, verify the account and code, and explicitly approve your own request. `--no-browser` prints the URL/code for another browser. Opening a page alone does not approve anything. The private polling proof stays in the CLI; the new CLI session is separate from the browser session. Denial/expiry leaves an existing connection unchanged. Connecting another account to the same origin requires `--replace`.

The default store is macOS Keychain, Windows Credential Manager or Linux Secret Service. Business commands never unlock it or open login; an inaccessible store exits10. Explicit login may request native-store interaction. On Unix without an available native store, explicitly use `bb auth login --store file`: its directory must be private0700 and the credential an owned regular0600 file, with symlinks refused. Windows file mode is unsupported. There is no automatic plaintext fallback.

`auth status` calls `/auth/me` and reports identity/source/expiry without a credential. `auth logout` revokes this session and clears its selected local entry. It reports local clearance and remote revocation separately; an offline revocation failure exits nonzero. Other browser sessions remain separate. If replacement cleanup reports failure, review the previous connection/session rather than assuming every old credential was erased.

If the token exchange loses its reply, login stops polling with `delivery_unknown:true`, `new_session_may_exist:true` and `cleanup_uncertain:true`. An unreadable successful reply reports `mutation_confirmed:true` instead. Cancellation during that exchange preserves this outcome. The previous saved connection stays unchanged; the CLI cannot revoke a new token it never received. Review account recovery/session revocation with the server operator before starting a fresh login.

For unattended jobs, supply `BB_SESSION_TOKEN` through your existing secret manager/environment, optionally `BB_SESSION_COOKIE_NAME` for a customized server. This credential is invocation-only; logout cannot erase a secret from an external manager. Never put a session value into command arguments, logs or a committed file.

## Agent quickstart

```sh
bb commands                       # offline command tree
bb commands task update           # only update options
bb schema POST /tasks             # one deployed operation + referenced schemas
bb task add --title 'Draft outline' --key capture-20261006-001
bb task list --q 'Draft outline' --limit 20
bb task get TASK_ID
bb task update TASK_ID --title 'Draft reviewed outline' --revision 1 --key edit-20261006-001
bb task transition TASK_ID complete --revision 2 --key complete-20261006-001
```

Use the revision returned by the actual preceding read/write; `1` and `2` above are illustrative. Keys must contain1–200 ASCII letters/digits or `. _ : -`. Preserve the same key/body for an intentional replay of the same operation. The CLI generates neither revisions nor keys and performs no implicit lookup or read-modify-write.

```sh
printf '%s' '{"title":"Draft outline","details":"Private working notes"}' |
  bb task add --json @- --key capture-20261006-002
bb task update TASK_ID --json @update.json --revision 3 --key edit-20261006-002
bb task list --fields id,title,state,revision --limit 20
bb task get TASK_ID --full
bb task get TASK_ID --fields subtasks.title,subtasks.completed
bb task add --title 'Preview only' --key preview-001 --dry-run
bb api GET /tags --limit 10
bb tree api GET /trees/TREE_ID
```

Named payload options and `--json` are exclusive. JSON input is one UTF-8 object, max1MiB. `--json @-` reads stdin, `@FILE` reads a regular file, and inline JSON is available for nonsensitive input. Preview performs no network/credential access and exposes only method/path, query names, body names/types and safe revision/key metadata.

Generic `api GET/POST/PUT/PATCH/DELETE PATH` covers deployed member operations under `/tasks`, `/projects`, `/tags`, `/trees`, `/crt`, `/brain-dump-operations`, `/brain-dump-providers`, `/agent-connections`, `/agent-runs`, `/agent-run-summaries`. Use repeated `--query KEY=VALUE`; values are URL encoded. Authorization/account/admin/public/operator routes are excluded; use specialized auth commands. Generic writes reject `--fields`; generic GET selectors are checked against the received data. Availability, ownership, flags and mutation semantics remain server controlled.

## Output and recovery

Success stdout is one compact JSON line with `data`. Task defaults are `id,title,state,revision,priority,due_date,project_id,tag_ids`. `--fields` selects documented dotted fields while retaining id/revision; `--full` includes all bounded task fields. Task lists retain `page.has_more` and the opaque `page.next_cursor`; copy that cursor into the next explicit `--cursor` call. There is no automatic paging. Default limit20, max200. An unpaginated list truncated locally reports `truncated:true,has_more:false,next_cursor:null`.

Errors are one JSON object on stderr, with safe status/correlation/retry metadata where available. Help/version are human-readable; explicit login may print waiting instructions on stderr. Requests use a10s connect/30s total timeout, max8MiB success and16KiB error responses, TLS verification, zero redirects and zero HTTP retries. Authentication polling follows its separate bounded grant interval.

| Exit | Meaning |
| --- | --- |
| 0 | Success |
| 2 | Invalid arguments/input |
| 3 | Missing/expired session |
| 4 | Forbidden |
| 5 | Missing resource/capability |
| 6 | Revision/conflict |
| 7 | Rate limit; respect retry timing |
| 8 | Transport failure |
| 9 | Server/protocol/response limit |
| 10 | Credential/configuration store unavailable |
| 11 | Authorization denied/expired/consumed |
| 130 | Login cancelled |

After a conflict, read current state and reconcile the intended change with a fresh explicit revision/key. After an interrupted write, `delivery_unknown:true` means inspect state before repeating. A2xx write followed by response-processing failure reports `mutation_confirmed:true,delivery_unknown:false`; inspect rather than starting another write. No automatic replay is performed. Server401 requires an explicit new login, and an inaccessible store requires you to unlock/repair it explicitly.

Connection selection is `--server/--api-prefix`, then `BB_SERVER/BB_API_PREFIX`, then saved defaults. Origins are HTTPS; HTTP is permitted only for loopback development. Configuration metadata is nonsecret and scoped to canonical origin plus API prefix; secret locators are random and do not encode tokens. `BB_CONFIG_DIR` selects a separate directory for disposable test/development accounts.
